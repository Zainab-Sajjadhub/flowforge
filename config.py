import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CLIENT_SECRETS_FILE = "google_credentials.json"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/generative-language",
]

RECALL_REGION = os.getenv("RECALL_REGION", "us-west-2")
RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_BASE_URL = f"https://{RECALL_REGION}.recall.ai/api/v1"
RECALL_WORKSPACE_VERIFICATION_SECRET = os.getenv("RECALL_WORKSPACE_VERIFICATION_SECRET", "")
RECALL_SVIX_WEBHOOK_SECRET = os.getenv("RECALL_SVIX_WEBHOOK_SECRET", "")

PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "")

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "")
SLACK_TRANSCRIPT_CHANNEL_ID = os.getenv("SLACK_TRANSCRIPT_CHANNEL_ID", "")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SERVER_HOST = "localhost"
SERVER_PORT = 8000

CALENDAR_LOOKAHEAD_HOURS = 24
