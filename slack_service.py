# ─────────────────────────────────────────────
#  FOUNDRY — SLACK SERVICE
#  Posts attendance, action items, and transcripts to Slack
# ─────────────────────────────────────────────

import logging
from datetime import datetime

import httpx

import config
from storage import Storage

log = logging.getLogger(__name__)

SLACK_POST_URL    = "https://slack.com/api/chat.postMessage"
SLACK_LOOKUP_URL  = "https://slack.com/api/users.lookupByEmail"

HEADERS = {
    "Authorization": f"Bearer {config.SLACK_BOT_TOKEN}",
    "Content-Type": "application/json",
}


def _load_team() -> list:
    """Load team members from foundry_data.json."""
    return Storage().get("team") or []


def _build_email_map(emails: list[str]) -> dict:
    """Match attendee emails against the team list. Returns email→member map."""
    team = _load_team()
    result = {}
    for email in emails:
        for member in team:
            if member.get("google_email", "").lower() == email.lower():
                result[email.lower()] = member
                break
    return result


class SlackService:

    async def post_attendance(self, summary: dict, meeting_id: str):
        invited_emails = [e.lower() for e in (summary.get("attendees") or [])]
        present_names  = [n.lower() for n in (summary.get("attendance") or [])]

        email_map = _build_email_map(invited_emails)

        invited = list(email_map.values())
        present = [m for m in invited if any(m["name"].lower().split()[0] in n for n in present_names)]
        absent  = [m for m in invited if m not in present]

        def fmt(members):
            if not members:
                return "_None_"
            return "  ".join(f"<@{m['slack_id']}>" for m in members)

        meeting_date = _format_date(summary.get("meeting_start", ""))

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"📋 Attendance — {summary.get('meeting_title', 'Meeting')}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{meeting_date}*"}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*✅ Present*\n{fmt(present)}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*❌ Absent*\n{fmt(absent)}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "Posted by Foundry Meeting Intelligence"}]},
        ]

        await _post(config.SLACK_CHANNEL_ID, blocks)
        log.info(f"Attendance posted for '{summary.get('meeting_title')}'")

    async def post_summary(self, summary: dict, meeting_id: str):
        invited_emails = [e.lower() for e in (summary.get("attendees") or [])]
        email_map = _build_email_map(invited_emails)
        blocks = self._build_action_blocks(summary, email_map)
        await _post(config.SLACK_CHANNEL_ID, blocks)
        log.info(f"Action items posted for '{summary.get('meeting_title')}'")

    async def post_transcript(self, summary: dict, meeting_id: str):
        transcript = summary.get("transcript_raw", "")
        if not transcript:
            log.warning(f"No transcript to post for meeting {meeting_id}")
            return

        meeting_title = summary.get("meeting_title", "Meeting")
        meeting_date  = _format_date(summary.get("meeting_start", ""))

        header = f"*Transcript — {meeting_title}*\n_{meeting_date}_\n\n"
        text   = header + transcript
        blocks = []
        while text:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}})
            text = text[3000:]

        await _post(config.SLACK_TRANSCRIPT_CHANNEL_ID, blocks)
        log.info(f"Transcript posted for '{meeting_title}'")

    def _build_action_blocks(self, summary: dict, email_map: dict) -> list:
        action_items  = summary.get("action_items", [])
        meeting_date  = _format_date(summary.get("meeting_start", ""))

        def format_owners(owner: str) -> str:
            parts = [o.strip() for o in owner.replace(" and ", ",").split(",") if o.strip()]
            mentions = []
            for part in parts:
                matched = next(
                    (f"<@{m['slack_id']}>" for m in email_map.values() if part.lower() in m["name"].lower()),
                    part
                )
                mentions.append(matched)
            return " ".join(mentions)

        if action_items:
            items_text = "\n".join(
                f"{i+1}. *{item['task']}*\n    👤 {format_owners(item['owner'])}   📅 {item['deadline']}"
                for i, item in enumerate(action_items)
            )
        else:
            items_text = "_No action items found._"

        return [
            {"type": "header", "text": {"type": "plain_text", "text": f"⚡ Action Items — {summary.get('meeting_title', 'Meeting')}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{meeting_date}*"}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": items_text}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "Posted by Foundry Meeting Intelligence"}]},
        ]


async def _post(channel: str, blocks: list):
    async with httpx.AsyncClient() as client:
        res = await client.post(SLACK_POST_URL, headers=HEADERS, json={"channel": channel, "blocks": blocks})
        res.raise_for_status()
        data = res.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data.get('error')}")


def _format_date(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%A, %B %-d, %Y")
    except Exception:
        return iso[:10]
