# Foundry Meeting Intelligence — Chrome Extension

## Setup (5 steps)

### 1. Google Cloud Console
1. Go to https://console.cloud.google.com
2. Create a new project (e.g. "Foundry Meeting Intelligence")
3. Enable these APIs:
   - Google Calendar API
   - Generative Language API (for Gemini)
4. Go to **Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Chrome Extension**
6. Add your Extension ID (you'll get this after first loading it — see step 5)
7. Copy the **Client ID**

### 2. Recall.ai
1. Sign up at https://www.recall.ai
2. Go to Dashboard → API Keys
3. Copy your API key

### 3. Slack
1. Go to https://api.slack.com/apps → Create New App
2. Add these OAuth scopes under **Bot Token Scopes**:
   - `chat:write`
   - `channels:read`
3. Install to workspace and copy the **Bot User OAuth Token** (`xoxb-...`)
4. Add the bot to your target channel and copy the **Channel ID** (right-click channel → Copy Link, the ID is the last segment)

### 4. Fill in your .env
Create a `.env` file in the project root and fill in your keys:
```
RECALL_API_KEY=your-recall-key
RECALL_REGION=us-west-2
RECALL_WORKSPACE_VERIFICATION_SECRET=your-secret
PUBLIC_API_BASE_URL=https://your-ngrok-url.ngrok-free.app
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_CHANNEL_ID=C012AB3CD
ANTHROPIC_API_KEY=your-anthropic-key
PYTHONDONTWRITEBYTECODE=1
```

Also update `manifest.json` → `oauth2.client_id` to your Google OAuth client ID.

### 5. Load the Extension
1. Open Chrome → `chrome://extensions`
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select this folder
5. Copy your Extension ID → go back to Google Cloud Console → paste into the OAuth client's Item ID field

---

## Running the Backend

**Every time you want to use the extension, start the Python server first.**

```bash
# First time only — create and activate virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start the server
python server.py
```

The server runs at `http://localhost:8000`.

**Expose the server for Recall webhooks (required for summaries to work):**
```bash
ngrok http 8000
```
Copy the ngrok URL it gives you and update `PUBLIC_API_BASE_URL` in your `.env`.

---

## How it works

**Upcoming tab** — Shows your next 24 hours of Google Meet meetings pulled from your primary calendar. Click **⚡ Arm Bot** to deploy a Recall.ai notetaker bot into the meeting.

**Live tab** — Shows active bots with real-time status: joining → recording → processing.

**Summaries tab** — After a meeting ends, Gemini extracts a summary, action items with owners/deadlines/priority, key decisions, topics, and blockers. Click any card to open the full view. Use **Post to Slack** to send a formatted summary to your channel.

---

## Data Flow
```
Google Calendar API
      ↓
  Meeting detected
      ↓
  Recall.ai bot auto-joins Google Meet
      ↓
  Deepgram transcribes with speaker labels
      ↓
  Transcript stored in chrome.storage.local
      ↓
  Gemini 1.5 Flash extracts summary + action items
      ↓
  Chrome extension shows structured summary
      ↓
  One-click post to Slack
```
