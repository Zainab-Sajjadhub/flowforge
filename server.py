# ─────────────────────────────────────────────
#  FOUNDRY — SERVER
#  Google auth token comes from Chrome extension.
#  No server-side OAuth flow or credentials file needed.
# ─────────────────────────────────────────────

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

import config
from calendar_service import CalendarService
from claude_service import ClaudeService
from recall_service import RecallService, verify_recall_request
from slack_service import SlackService
from storage import Storage 

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def extract_token(authorization_header: str) -> str | None:
    if not authorization_header:
        return None
    if authorization_header.startswith("Bearer "):
        return authorization_header[7:]
    return None

REQUIRED = {
    "RECALL_REGION": config.RECALL_REGION,
    "RECALL_API_KEY": config.RECALL_API_KEY,
    "RECALL_WORKSPACE_VERIFICATION_SECRET": config.RECALL_WORKSPACE_VERIFICATION_SECRET,
    "PUBLIC_API_BASE_URL": config.PUBLIC_API_BASE_URL,
}

storage = Storage()
calendar_svc = CalendarService(storage)
recall_svc = RecallService(storage)
claude_svc = ClaudeService()
slack_svc = SlackService()

_webhook_queue: asyncio.Queue = asyncio.Queue()


async def webhook_worker():
    while True:
        got_item = False
        try:
            event_type, payload = await _webhook_queue.get()
            got_item = True
            log.info(f"Processing webhook: {event_type}")

            if event_type.startswith("bot."):
                recall_svc.handle_bot_status_change(payload)
            elif event_type == "recording.done":
                await recall_svc.handle_recording_done(payload)
            elif event_type == "transcript.done":
                await recall_svc.handle_transcript_done(payload, claude_svc, slack_svc)
            elif event_type in ("recording.failed", "transcript.failed"):
                log.error(f"Recall failure event: {event_type} — {payload}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Webhook worker error: {e}", exc_info=True)
        finally:
            if got_item:
                _webhook_queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = [k for k, v in REQUIRED.items() if not v or v.startswith("YOUR_")]
    if missing:
        log.error(f"Missing required config values: {', '.join(missing)}")
    else:
        log.info(f"Recall region: {config.RECALL_REGION}")
        log.info(f"Public API base URL: {config.PUBLIC_API_BASE_URL}")

    task = asyncio.create_task(webhook_worker())
    yield
    task.cancel()


app = FastAPI(title="Foundry Meeting Intelligence", lifespan=lifespan)


@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    origin = request.headers.get("origin", "")
    response = await call_next(request)
    if origin.startswith("chrome-extension://") or origin.startswith("http://localhost"):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    return response


@app.options("/{rest_of_path:path}")
async def preflight(rest_of_path: str, request: Request):
    origin = request.headers.get("origin", "")
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )


# ── Models ────────────────────────────────────
class MeetingPayload(BaseModel):
    id: str
    title: str
    start: str
    end: str
    meet_link: str
    attendees: list[str]
    organizer: str | None = None


# ── Calendar ──────────────────────────────────
@app.get("/meetings")
async def get_meetings(request: Request):
    """Returns cached meetings. Pass Google token to trigger a fresh poll."""
    token = extract_token(request.headers.get("Authorization", ""))
    if token:
        try:
            await calendar_svc.poll(token)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
    meetings = storage.get("meetings") or []
    return {"meetings": meetings, "last_polled": storage.get("last_calendar_poll")}


@app.post("/meetings/refresh")
async def refresh_meetings(request: Request):
    token = extract_token(request.headers.get("Authorization", ""))
    if not token:
        raise HTTPException(status_code=401, detail="Google token required")
    await calendar_svc.poll(token)
    return {"meetings": storage.get("meetings") or []}


# ── Bots ──────────────────────────────────────
@app.post("/bots/arm")
async def arm_bot(meeting: MeetingPayload):
    bot = await recall_svc.arm(meeting.model_dump())
    return {"ok": True, "bot_id": bot["id"]}


@app.get("/bots/active")
async def get_active_bots():
    active_bots = storage.get("active_bots") or {}
    active = {}
    for k, v in active_bots.items():
        if v.get("status") != "done":
            active[k] = {
                "botId": v.get("bot_id"),
                "meetingId": v.get("meeting_id"),
                "meetingTitle": v.get("meeting_title"),
                "meetingStart": v.get("meeting_start"),
                "attendees": v.get("attendees", []),
                "status": v.get("status"),
                "armedAt": v.get("armed_at"),
            }
    return {"bots": active}


# ── Summaries ─────────────────────────────────
@app.get("/summaries")
async def get_summaries():
    summaries = storage.get("meeting_summaries") or {}
    def to_camel(s: dict) -> dict:
        return {
            "meetingTitle": s.get("meeting_title", ""),
            "meetingStart": s.get("meeting_start", ""),
            "attendees": s.get("attendees", []),
            "attendance": s.get("attendance", []),
            "actionItems": s.get("action_items", []),
            "summary": s.get("summary", ""),
            "keyDecisions": s.get("key_decisions", []),
            "topics": s.get("topics", []),
            "blockers": s.get("blockers", []),
            "processedAt": s.get("processed_at", 0),
        }
    sorted_summaries = dict(
        sorted(summaries.items(), key=lambda x: x[1].get("processed_at", 0), reverse=True)
    )
    return {"summaries": {k: to_camel(v) for k, v in sorted_summaries.items()}}


@app.post("/summaries/{meeting_id}/slack")
async def post_summary_to_slack(meeting_id: str):
    summaries = storage.get("meeting_summaries") or {}
    summary = summaries.get(meeting_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    await slack_svc.post_summary(summary, meeting_id)
    return {"ok": True}


# ── Recall webhooks ───────────────────────────
@app.post("/webhooks/recall")
async def recall_webhook(request: Request):
    raw_body = await request.body()
    headers = dict(request.headers)

    log.info(f"Webhook headers: {list(headers.keys())}")
    if not verify_recall_request(raw_body, headers):
        log.warning("Recall webhook verification failed — rejecting")
        return Response(status_code=401)

    try:
        payload = await request.json()
        event_type = payload.get("event", "unknown")
        await _webhook_queue.put((event_type, payload))
        log.info(f"Webhook enqueued: {event_type}")
    except Exception as e:
        log.error(f"Failed to parse webhook payload: {e}")
        return Response(status_code=400)

    return Response(status_code=200)


# ── Health ────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "region": config.RECALL_REGION, "time": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    uvicorn.run("server:app", host=config.SERVER_HOST, port=config.SERVER_PORT, reload=True)