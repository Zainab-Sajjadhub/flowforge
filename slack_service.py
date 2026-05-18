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

    def _build_blocks(self, summary: dict) -> list:
        action_items = summary.get("action_items", [])
        key_decisions = summary.get("key_decisions", [])
        blockers = summary.get("blockers", [])

        meeting_date = ""
        if summary.get("meeting_start"):
            try:
                dt = datetime.fromisoformat(summary["meeting_start"])
                meeting_date = dt.strftime("%A, %B %-d, %Y")
            except Exception:
                meeting_date = summary["meeting_start"][:10]

        attendance_count = len(summary.get("attendance") or summary.get("attendees", []))

        # Action items text
        if action_items:
            items_text = "\n".join(
                f"{i+1}. *{item['task']}* → {item['owner']} _({item['deadline']})_"
                for i, item in enumerate(action_items)
            )
        else:
            items_text = "_No action items extracted._"

        # Decisions text
        decisions_text = (
            "\n".join(f"• {d}" for d in key_decisions) if key_decisions else "_None recorded._"
        )

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"📋 {summary.get('meeting_title', 'Meeting Summary')}"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{meeting_date}*  •  {attendance_count} attendees",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Summary*\n{summary.get('summary', '—')}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Key Decisions*\n{decisions_text}"},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Action Items*\n{items_text}"},
            },
        ]

        if blockers:
            blockers_text = "\n".join(f"⚠ {b}" for b in blockers)
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Blockers / Risks*\n{blockers_text}"},
            })

        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Posted by Foundry Meeting Intelligence"}],
        })

        return blocks
