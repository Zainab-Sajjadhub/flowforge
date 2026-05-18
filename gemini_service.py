# ─────────────────────────────────────────────
#  FOUNDRY — CLAUDE SERVICE (via Anthropic API)
#  Summarizes transcripts and extracts action items
# ─────────────────────────────────────────────

import json
import logging
import re

import httpx

import config

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
HEADERS = {
    "x-api-key": config.ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}


class GeminiService:
    async def summarize(self, transcript_text: str, bot_record: dict) -> dict:
        """
        Send transcript to Claude and return structured summary.
        Returns dict with: summary, key_decisions, action_items,
                           topics, attendance, blockers
        """
        prompt = self._build_prompt(transcript_text, bot_record)

        payload = {
            "model": "claude-sonnet-4-5",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(ANTHROPIC_URL, headers=HEADERS, json=payload)
            res.raise_for_status()
            data = res.json()

        raw = data["content"][0]["text"]
        return self._parse_response(raw)

    def _build_prompt(self, transcript_text: str, bot_record: dict) -> str:
        attendees = ", ".join(bot_record.get("attendees", []))
        meeting_date = bot_record.get("meeting_start", "")[:10]

        return f"""You are an AI assistant helping The Foundry, a student-led nonprofit that supports East Coast startup founders.

Analyze this meeting transcript and return a JSON object with EXACTLY this structure:
{{
  "summary": "2-3 sentence high-level summary of what was discussed and decided",
  "key_decisions": ["decision 1", "decision 2"],
  "action_items": [
    {{
      "task": "clear description of what needs to be done",
      "owner": "person's name or email if mentioned, otherwise Unassigned",
      "deadline": "specific date or timeframe if mentioned, otherwise No deadline set",
      "priority": "high or medium or low"
    }}
  ],
  "topics": ["topic 1", "topic 2"],
  "attendance": ["name or email of each person who spoke"],
  "blockers": ["any blocker or risk mentioned"]
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
            log.error(f"Claude JSON parse error: {e}\nRaw: {raw[:500]}")
            return {
                "summary": "Could not parse summary.",
                "key_decisions": [],
                "action_items": [],
                "topics": [],
                "attendance": [],
                "blockers": [],
            }