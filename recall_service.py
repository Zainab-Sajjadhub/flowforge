# ─────────────────────────────────────────────
#  FOUNDRY — RECALL.AI SERVICE
#
#  Follows Recall.ai agent guide:
#  - Webhook-driven lifecycle (no polling)
#  - Post-meeting async transcription
#  - Retry logic for 429 / 503 / 507
#  - Request verification via workspace secret
# ─────────────────────────────────────────────

import asyncio
import hashlib
import hmac
import logging
import random
from datetime import datetime, timezone

import httpx

import config
from storage import Storage

log = logging.getLogger(__name__)

HEADERS = {
    "Authorization": f"Token {config.RECALL_API_KEY}",
    "Content-Type": "application/json",
}


# ── Retry-aware HTTP client ───────────────────

async def recall_request(method: str, path: str, **kwargs) -> dict:
    """
    Makes a request to the Recall API with retry logic.
    Handles 429 (rate limit), 503 (unavailable), 507 (bot pool drained).
    """
    url = f"{config.RECALL_BASE_URL}/{path.lstrip('/')}"
    max_attempts = 6

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(1, max_attempts + 1):
            res = await client.request(method, url, headers=HEADERS, **kwargs)

            wait_for = None
            if res.status_code == 429:
                wait_for = int(res.headers.get("Retry-After", "5"))
            elif res.status_code == 503:
                wait_for = 10
            elif res.status_code == 507:
                wait_for = 30

            if wait_for is not None:
                jitter = random.randint(1, 5)
                total = wait_for + jitter
                log.warning(f"Recall API {res.status_code} — retrying in {total}s (attempt {attempt}/{max_attempts})")
                await asyncio.sleep(total)
                continue

            res.raise_for_status()
            return res.json()

    raise RuntimeError(f"Max retry attempts reached for {method} {url}")


# ── Request verification ──────────────────────

def verify_recall_request(raw_body: bytes, headers: dict) -> bool:
    """
    Verifies that an incoming request genuinely came from Recall.ai.
    Uses RECALL_WORKSPACE_VERIFICATION_SECRET for all webhooks.
    For accounts created before Dec 15 2025, uses RECALL_SVIX_WEBHOOK_SECRET
    for dashboard webhooks if set.

    Returns True if verified, False if verification fails.
    """
    # Determine which secret to use
    # Dashboard webhooks from pre-Dec-2025 accounts use the svix secret
    svix_sig = headers.get("svix-signature") or headers.get("Svix-Signature")
    use_svix = bool(svix_sig and config.RECALL_SVIX_WEBHOOK_SECRET)
    secret = config.RECALL_SVIX_WEBHOOK_SECRET if use_svix else config.RECALL_WORKSPACE_VERIFICATION_SECRET

    if not secret:
        log.error("No verification secret configured — rejecting request")
        return False

    # Recall sends: X-Recall-Signature: sha256=<hex>
    recall_sig_header = (
        headers.get("x-recall-signature")
        or headers.get("X-Recall-Signature")
    )

    if use_svix and svix_sig:
        # Svix verification for legacy dashboard webhooks
        svix_id = headers.get("svix-id") or headers.get("Svix-Id", "")
        svix_ts = headers.get("svix-timestamp") or headers.get("Svix-Timestamp", "")
        signed_content = f"{svix_id}.{svix_ts}.{raw_body.decode('utf-8')}"
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        # svix-signature may contain multiple space-separated v1,<hex> pairs
        for part in svix_sig.split(" "):
            if part.startswith("v1,") and hmac.compare_digest(part[3:], expected):
                return True
        log.warning("Svix webhook signature verification failed")
        return False

    elif recall_sig_header:
        # Standard Recall workspace verification secret
        prefix = "sha256="
        if not recall_sig_header.startswith(prefix):
            log.warning("Unexpected signature format")
            return False
        provided_sig = recall_sig_header[len(prefix):]
        expected = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(provided_sig, expected):
            return True
        log.warning("Recall workspace signature verification failed")
        return False

    else:
        log.warning("No recognizable signature header found — rejecting request")
        return False


# ── Bot arming ────────────────────────────────

class RecallService:
    def __init__(self, storage: Storage):
        self.storage = storage

    async def arm(self, meeting: dict) -> dict:
        """
        Deploy a Recall.ai notetaker bot into a Google Meet.
        Uses post-meeting async transcription — transcript is created
        after the call via the recording.done webhook flow.
        """
        payload = {
            "meeting_url": meeting["meet_link"],
            "join_at": meeting["start"],  # ISO8601 — bot joins at meeting start time
            "bot_name": "Foundry Notetaker",
            "chat": {
                "on_bot_join": {
                    "send_to": "everyone",
                    "message": "This meeting is being recorded and summarized by The Foundry.",
                    "pin": True,
                }
            },
            # No recording_config here — we use post-meeting async transcription
            # triggered by the recording.done webhook, NOT real-time transcription
        }

        bot = await recall_request("POST", "/bot", json=payload)

        active_bots = self.storage.get("active_bots") or {}
        active_bots[meeting["id"]] = {
            "bot_id": bot["id"],
            "meeting_id": meeting["id"],
            "meeting_title": meeting["title"],
            "meeting_start": meeting["start"],
            "attendees": meeting.get("attendees", []),
            "status": "joining",
            "armed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.storage.set("active_bots", active_bots)

        log.info(f"Bot armed — {bot['id']} for '{meeting['title']}'")
        return bot

    # ── Webhook handlers (called from server.py) ──

    def handle_bot_status_change(self, payload: dict):
        """
        Updates bot status from a bot.* webhook event.
        This is the source of truth — we do NOT poll.
        """
        bot_id = payload.get("data", {}).get("bot", {}).get("id")
        status_data = payload.get("data", {}).get("data", {})
        new_status = status_data.get("code", "unknown")

        active_bots = self.storage.get("active_bots") or {}
        for meeting_id, record in active_bots.items():
            if record.get("bot_id") == bot_id:
                active_bots[meeting_id]["status"] = new_status
                log.info(f"Bot {bot_id} status → {new_status}")
                break

        self.storage.set("active_bots", active_bots)

    async def handle_recording_done(self, payload: dict):
        """
        Called when recording.done fires.
        Kicks off async (post-meeting) transcript creation.
        """
        recording_id = payload.get("data", {}).get("recording", {}).get("id")
        bot_id = payload.get("data", {}).get("bot", {}).get("id")

        if not recording_id:
            log.error("recording.done webhook missing recording ID")
            return

        log.info(f"Recording done — creating async transcript for recording {recording_id}")

        # Use Recall.ai's own transcription provider (no third-party setup needed)
        await recall_request(
            "POST",
            f"/recording/{recording_id}/create_transcript/",
            json={
                "provider": {
                    "recallai_async": {
                        "language_code": "auto"
                    }
                },
                "diarization": {
                    "use_separate_streams_when_available": True,
                },
            },
        )

        # Save the recording_id so we can match it when transcript.done arrives
        active_bots = self.storage.get("active_bots") or {}
        for meeting_id, record in active_bots.items():
            if record.get("bot_id") == bot_id:
                active_bots[meeting_id]["recording_id"] = recording_id
                break
        self.storage.set("active_bots", active_bots)

    async def handle_transcript_done(self, payload: dict, claude_svc, slack_svc=None):
        """
        Called when transcript.done fires.
        Downloads the transcript and runs Gemini summarization.
        """
        transcript_id = payload.get("data", {}).get("transcript", {}).get("id")
        bot_id = payload.get("data", {}).get("bot", {}).get("id")

        if not transcript_id:
            log.error("transcript.done webhook missing transcript ID")
            return

        log.info(f"Transcript done — downloading transcript {transcript_id}")

        # Fetch transcript metadata to get download URL
        transcript_meta = await recall_request("GET", f"/transcript/{transcript_id}/")
        download_url = transcript_meta.get("data", {}).get("download_url")

        if not download_url:
            log.error(f"No download_url in transcript metadata for {transcript_id}")
            return

        # Download the full transcript JSON
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.get(download_url)
            res.raise_for_status()
            transcript_data = res.json()

        # Format into readable speaker-labelled text
        transcript_text = self._format_transcript(transcript_data)

        # Find the matching bot record for meeting context
        active_bots = self.storage.get("active_bots") or {}
        bot_record = next(
            (r for r in active_bots.values() if r.get("bot_id") == bot_id),
            None,
        )

        if not bot_record:
            log.warning(f"No bot record found for bot_id {bot_id} — using minimal context")
            bot_record = {"meeting_title": "Unknown Meeting", "meeting_start": "", "attendees": []}

        # Run Gemini summarization
        summary = await claude_svc.summarize(transcript_text, bot_record)

        # Store summary
        meeting_summaries = self.storage.get("meeting_summaries") or {}
        meeting_id = bot_record.get("meeting_id", transcript_id)
        meeting_summaries[meeting_id] = {
            **summary,
            "meeting_title": bot_record["meeting_title"],
            "meeting_start": bot_record["meeting_start"],
            "attendees": bot_record["attendees"],
            "transcript_raw": transcript_text,
            "processed_at": datetime.now(timezone.utc).timestamp(),
        }
        self.storage.set("meeting_summaries", meeting_summaries)

        # Mark bot as done
        if bot_id:
            for mid, record in active_bots.items():
                if record.get("bot_id") == bot_id:
                    active_bots[mid]["status"] = "done"
                    break
            self.storage.set("active_bots", active_bots)

        log.info(f"Summary stored for '{bot_record['meeting_title']}' — {len(summary.get('action_items', []))} action items")

        if slack_svc:
            try:
                await slack_svc.post_summary(meeting_summaries[meeting_id], meeting_id)
                await slack_svc.post_transcript(meeting_summaries[meeting_id], meeting_id)
            except Exception as e:
                log.error(f"Failed to post to Slack: {e}")

    def _format_transcript(self, transcript_data: list) -> str:
        """Convert Recall's JSON transcript format into readable speaker-labelled text."""
        lines = []
        for entry in transcript_data:
            speaker = entry.get("participant", {}).get("name") or "Unknown"
            words = " ".join(w["text"] for w in entry.get("words", []))
            if words.strip():
                lines.append(f"[{speaker}]: {words.strip()}")
        return "\n".join(lines)