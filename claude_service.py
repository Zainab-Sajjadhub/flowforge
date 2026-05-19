# ─────────────────────────────────────────────
#  FOUNDRY — AI SERVICE (via Google Gemini)
#  Extracts action items from meeting transcripts
# ─────────────────────────────────────────────

import json
import logging
import re

import httpx

import config

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


class ClaudeService:
    async def summarize(self, transcript_text: str, bot_record: dict) -> dict:
        prompt = self._build_prompt(transcript_text, bot_record)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                GEMINI_URL,
                params={"key": config.GEMINI_API_KEY},
                json=payload,
            )
            res.raise_for_status()
            data = res.json()

        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        return self._parse_response(raw)

    def _build_prompt(self, transcript_text: str, bot_record: dict) -> str:
        attendees = ", ".join(bot_record.get("attendees", []))
        meeting_date = bot_record.get("meeting_start", "")[:10]

        return f"""You are an AI assistant helping The Foundry, a student-led nonprofit that supports East Coast startup founders.

Analyze this meeting transcript and extract ONLY the action items. Assign each to the person who said they would do it, or who it was assigned to. If no one is assigned, use "Unassigned".

Return a JSON object with EXACTLY this structure:
{{
  "action_items": [
    {{
      "task": "clear description of what needs to be done",
      "owner": "comma-separated first names if multiple people are assigned, otherwise Unassigned",
      "deadline": "specific date or timeframe if mentioned, otherwise No deadline set"
    }}
  ],
  "attendance": ["first name of each person who spoke"]
}}

Meeting: {bot_record.get("meeting_title", "Leadership Meeting")}
Date: {meeting_date}
Known attendees: {attendees}

TRANSCRIPT:
{transcript_text[:28000]}

Return ONLY valid JSON. No markdown, no code fences, no explanation."""

    def _parse_response(self, raw: str) -> dict:
        clean = re.sub(r"```json|```", "", raw).strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            log.error(f"Gemini JSON parse error: {e}\nRaw: {raw[:500]}")
            return {
                "action_items": [],
                "attendance": [],
            }
