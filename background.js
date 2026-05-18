// ─────────────────────────────────────────────
//  FOUNDRY — BACKGROUND
//  Gets Google token via chrome.identity and
//  passes it to the Python server on every request
// ─────────────────────────────────────────────

const API = "http://localhost:8000";

async function getToken() {
  return new Promise((resolve, reject) => {
    chrome.identity.getAuthToken({ interactive: false }, (token) => {
      if (chrome.runtime.lastError || !token) {
        reject(chrome.runtime.lastError?.message || "No token");
      } else {
        resolve(token);
      }
    });
  });
}

async function authHeaders() {
  const token = await getToken();
  return {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${token}`,
  };
}

// ── Polling ───────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("syncData", { periodInMinutes: 2 });
  syncData();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "syncData") syncData();
});

async function syncData() {
  try {
    const headers = await authHeaders();

    const [meetingsRes, botsRes, summariesRes] = await Promise.all([
      fetch(`${API}/meetings`, { headers }),
      fetch(`${API}/bots/active`, { headers }),
      fetch(`${API}/summaries`, { headers }),
    ]);

    const { meetings } = await meetingsRes.json();
    const { bots } = await botsRes.json();
    const { summaries } = await summariesRes.json();

    const prev = (await chrome.storage.local.get("meetingSummaries")).meetingSummaries || {};
    if (Object.keys(summaries).length > Object.keys(prev).length) {
      chrome.notifications.create({
        type: "basic",
        iconUrl: "icons/icon48.png",
        title: "Summary Ready",
        message: "A new meeting summary is available",
      });
    }

    await chrome.storage.local.set({
      meetings: meetings || [],
      activeBots: bots || {},
      meetingSummaries: summaries || {},
    });

    chrome.runtime.sendMessage({ type: "DATA_SYNCED", meetings, bots, summaries }).catch(() => {});
  } catch (err) {
    console.warn("Sync failed:", err.message);
  }
}

// ── Message listener ──────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.type === "AUTH_GOOGLE") {
    chrome.identity.getAuthToken({ interactive: true }, (token) => {
      if (chrome.runtime.lastError) {
        sendResponse({ ok: false, error: chrome.runtime.lastError.message });
      } else {
        syncData();
        sendResponse({ ok: true });
      }
    });
    return true;
  }

  if (msg.type === "ARM_BOT") {
    authHeaders().then(headers =>
      fetch(`${API}/bots/arm`, {
        method: "POST",
        headers,
        body: JSON.stringify(msg.meeting),
      })
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, ...data }))
      .catch(err => sendResponse({ ok: false, error: err.message }))
    );
    return true;
  }

  if (msg.type === "POST_SLACK") {
    authHeaders().then(headers =>
      fetch(`${API}/summaries/${msg.meetingId}/slack`, { method: "POST", headers })
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, ...data }))
      .catch(err => sendResponse({ ok: false, error: err.message }))
    );
    return true;
  }

  if (msg.type === "REFRESH_CALENDAR") {
    authHeaders().then(headers =>
      fetch(`${API}/meetings/refresh`, { method: "POST", headers })
      .then(() => syncData())
      .then(() => sendResponse({ ok: true }))
      .catch(err => sendResponse({ ok: false, error: err.message }))
    );
    return true;
  }

  if (msg.type === "CHECK_SERVER") {
    fetch(`${API}/health`)
      .then(r => r.json())
      .then(() => sendResponse({ ok: true }))
      .catch(() => sendResponse({ ok: false, error: "Server not running" }));
    return true;
  }
});