# ─────────────────────────────────────────────
#  FOUNDRY — CALENDAR SERVICE
#  Token is passed in from the Chrome extension
# ─────────────────────────────────────────────

import logging
from datetime import datetime, timedelta, timezone

import httpx

import config
from storage import Storage

log = logging.getLogger(__name__)


class CalendarService:
    def __init__(self, storage: Storage):
        self.storage = storage

    async def poll(self, token: str):
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=config.CALENDAR_LOOKAHEAD_HOURS)

        params = {
            "timeMin": now.isoformat(),
            "timeMax": future.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "20",
        }

        async with httpx.AsyncClient() as client:
            res = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            if res.status_code == 401:
                raise ValueError("Invalid or expired Google token")
            res.raise_for_status()
            data = res.json()

        meetings = []
        for event in data.get("items", []):
            conference = event.get("conferenceData", {})
            entry_points = conference.get("entryPoints", [])
            video_ep = next((ep for ep in entry_points if ep.get("entryPointType") == "video"), None)

            if not video_ep:
                continue

            meetings.append({
                "id": event["id"],
                "title": event.get("summary", "Untitled Meeting"),
                "start": event["start"].get("dateTime") or event["start"].get("date"),
                "end": event["end"].get("dateTime") or event["end"].get("date"),
                "meet_link": video_ep["uri"],
                "attendees": [a["email"] for a in event.get("attendees", [])],
                "organizer": event.get("organizer", {}).get("email"),
            })

        self.storage.set("meetings", meetings)
        self.storage.set("last_calendar_poll", datetime.now(timezone.utc).isoformat())
        log.info(f"Calendar polled — {len(meetings)} meeting(s) found")
        return meetings