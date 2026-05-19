# ─────────────────────────────────────────────
#  FOUNDRY — SLACK SERVICE
#  Posts formatted meeting summaries to Slack
# ─────────────────────────────────────────────

import logging
from datetime import datetime

import httpx

import config

log = logging.getLogger(__name__)

SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
HEADERS = {
    "Authorization": f"Bearer {config.SLACK_BOT_TOKEN}",
    "Content-Type": "application/json",
}


class SlackService:
    async def post_summary(self, summary: dict, meeting_id: str):
        blocks = self._build_blocks(summary)

        async with httpx.AsyncClient() as client:
            res = await client.post(
                SLACK_POST_URL,
                headers=HEADERS,
                json={"channel": config.SLACK_CHANNEL_ID, "blocks": blocks},
            )
            res.raise_for_status()
            data = res.json()

        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error')}")

        log.info(f"Summary posted to Slack for '{summary.get('meeting_title')}'")
        return data

    async def post_transcript(self, summary: dict, meeting_id: str):
        transcript = summary.get("transcript_raw", "")
        if not transcript:
            log.warning(f"No transcript to post for meeting {meeting_id}")
            return

        meeting_title = summary.get("meeting_title", "Meeting")
        meeting_date = ""
        if summary.get("meeting_start"):
            try:
                dt = datetime.fromisoformat(summary["meeting_start"])
                meeting_date = dt.strftime("%A, %B %-d, %Y")
            except Exception:
                meeting_date = summary["meeting_start"][:10]

        # Slack has a 3000 char limit per text block, so chunk if needed
        header = f"*Transcript — {meeting_title}*\n_{meeting_date}_\n\n"
        chunks = []
        text = header + transcript
        while text:
            chunks.append(text[:3000])
            text = text[3000:]

        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": chunk}} for chunk in chunks]

        async with httpx.AsyncClient() as client:
            res = await client.post(
                SLACK_POST_URL,
                headers=HEADERS,
                json={"channel": config.SLACK_TRANSCRIPT_CHANNEL_ID, "blocks": blocks},
            )
            res.raise_for_status()
            data = res.json()

        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error')}")

        log.info(f"Transcript posted to Slack for '{meeting_title}'")
        return data

    def _build_blocks(self, summary: dict) -> list:
        action_items = summary.get("action_items", [])

        meeting_date = ""
        if summary.get("meeting_start"):
            try:
                dt = datetime.fromisoformat(summary["meeting_start"])
                meeting_date = dt.strftime("%A, %B %-d, %Y")
            except Exception:
                meeting_date = summary["meeting_start"][:10]

        if action_items:
            items_text = "\n".join(
                f"{i+1}. *{item['task']}*\n    👤 {item['owner']}   📅 {item['deadline']}"
                for i, item in enumerate(action_items)
            )
        else:
            items_text = "_No action items found._"

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"⚡ Action Items — {summary.get('meeting_title', 'Meeting')}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{meeting_date}*"},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": items_text},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Posted by Foundry Meeting Intelligence"}],
            },
        ]

        return blocks
