# Foundry Meeting Intelligence — Chrome Extension

Automatically records, transcribes, and extracts action items from Google Meet meetings. Posts attendance, action items with @mentions, and full transcripts to Slack.

## Setup

### 1. Google Cloud Console
1. Go to https://console.cloud.google.com
2. Create a new project (e.g. "Foundry Meeting Intelligence")
3. Enable the **Google Calendar API**
4. Go to **Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Chrome Extension**
6. Add your Extension ID (you'll get this after first loading it — see step 5)
7. Copy the **Client ID**

### 2. Recall.ai
1. Sign up at https://www.recall.ai
2. Go to **Dashboard → API Keys** → copy your API key
3. Go to **Webhooks → Add Endpoint** → set URL to:
   ```
   https://your-ngrok-url.ngrok-free.app/webhooks/recall
   ```
4. Subscribe to events: `recording.done` and `transcript.done`
5. Copy the **Signing Secret** from the webhook page

### 3. Slack
1. Go to https://api.slack.com/apps → **Create New App → From scratch**
2. Add these **Bot Token Scopes** under OAuth & Permissions:
   - `chat:write`
   - `channels:join`
   - `users:read`
   - `users:read.email`
3. Install to workspace → copy the **Bot User OAuth Token** (`xoxb-...`)
4. Create two channels in Slack:
   - One for **action items** (invite the bot: `/invite @FlowForge`)
   - One for **transcripts** (invite the bot: `/invite @FlowForge`)
5. Copy both **Channel IDs** (right-click channel → Copy Link, ID is the last segment)

### 4. Google Gemini
1. Go to https://aistudio.google.com
2. Click **Get API Key → Create API key**
3. Copy the key

### 5. Fill in your .env
```
RECALL_REGION=us-west-2
RECALL_API_KEY=your-recall-key
RECALL_WORKSPACE_VERIFICATION_SECRET=your-webhook-signing-secret
PUBLIC_API_BASE_URL=https://your-ngrok-url.ngrok-free.app
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_CHANNEL_ID=C012AB3CD        # action items channel
SLACK_TRANSCRIPT_CHANNEL_ID=C012AB3CE  # transcripts channel
GEMINI_API_KEY=your-gemini-key
PYTHONDONTWRITEBYTECODE=1
```

Also update `manifest.json` → `oauth2.client_id` to your Google OAuth client ID.

### 6. Add your team to foundry_data.json
Add each team member's name, Google (Gmail) email, and Slack user ID to the `team` array. This is used to map attendees to Slack @mentions — no code changes needed to add new members.

```json
"team": [
  {"name": "Your Name", "google_email": "you@gmail.com", "slack_id": "UXXXXXXXXX"}
]
```

To find a Slack user ID: click their profile → three dots → **Copy member ID**.

### 7. Load the Extension
1. Open Chrome → `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** → select this folder
4. Copy your Extension ID → go back to Google Cloud Console → paste into the OAuth client's Item ID field

---

## Running the Backend

```bash
# First time only
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Every time
python server.py
```

The server runs at `http://localhost:8000`.

**Expose for Recall webhooks (required):**
```bash
ngrok http 8000
```
Copy the ngrok URL → update `PUBLIC_API_BASE_URL` in `.env` → update the webhook URL in Recall dashboard.

---

## How it works

**Upcoming tab** — Shows your next 24 hours of Google Meet meetings from your primary calendar. Click **⚡ Arm Bot** to deploy a Recall.ai notetaker into the meeting.

**Live tab** — Shows active bots with status: joining → recording → processing.

**Summaries tab** — After a meeting ends, summaries and action items appear here automatically.

**Automatic Slack posts (after every meeting):**
1. **Attendance** — who was invited, who attended, who was absent (with @mentions)
2. **Action items** — tasks with @mentions and deadlines
3. **Full transcript** — speaker-labelled transcript posted to the transcripts channel

---

## Data Flow
```
Google Calendar API
      ↓
  Meeting detected
      ↓
  Recall.ai bot joins Google Meet at start time
      ↓
  recording.done webhook → async transcription starts
      ↓
  transcript.done webhook → transcript downloaded
      ↓
  Gemini 2.5 Flash extracts action items + attendance
      ↓
  Slack: attendance + action items (@mentions) + transcript
```

---

## Adding a new team member
Edit `foundry_data.json` → add to the `team` array:
```json
{"name": "New Person", "google_email": "them@gmail.com", "slack_id": "UXXXXXXXXX"}
```
