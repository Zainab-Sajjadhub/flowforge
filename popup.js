// ─────────────────────────────────────────────
//  FOUNDRY — POPUP SCRIPT
// ─────────────────────────────────────────────

// ── State ─────────────────────────────────────
let activeSummary = null;
let activeSummaryId = null;

// ── Init ──────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  setupModal();
  setupButtons();
  listenToBackground();
  await loadAll();
});

// ── Tab switching ─────────────────────────────
function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");
    });
  });
}

// ── Buttons ───────────────────────────────────
function setupButtons() {
  document.getElementById("btn-refresh").addEventListener("click", async () => {
    const btn = document.getElementById("btn-refresh");
    btn.innerHTML = `<span class="spinner"></span>`;
    await chrome.runtime.sendMessage({ type: "REFRESH_CALENDAR" });
    await loadAll();
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`;
  });

  document.getElementById("btn-auth")?.addEventListener("click", async () => {
    const res = await chrome.runtime.sendMessage({ type: "AUTH_GOOGLE" });
    if (res.ok) {
      await loadAll();
    } else {
      toast(res.error || "Auth failed", "error");
    }
  });
}

// ── Load all data ─────────────────────────────
async function loadAll() {
  const { meetings = [], activeBots = {}, meetingSummaries = {} } =
    await chrome.storage.local.get(["meetings", "activeBots", "meetingSummaries"]);

  renderMeetings(meetings, activeBots);
  renderActiveBots(activeBots);
  renderSummaries(meetingSummaries);
}

// ── Meetings Tab ──────────────────────────────
function renderMeetings(meetings, activeBots) {
  const container = document.getElementById("meetings-list");

  if (!meetings.length) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No upcoming meetings with video links found</p>
        <button class="btn-primary" id="btn-signin">Connect Google Calendar</button>
        <span class="empty-hint">Or meetings may not have Google Meet links</span>
      </div>`;
    document.getElementById("btn-signin")?.addEventListener("click", async () => {
      const res = await chrome.runtime.sendMessage({ type: "AUTH_GOOGLE" });
      if (res.ok) {
        await chrome.runtime.sendMessage({ type: "REFRESH_CALENDAR" });
        await loadAll();
      } else {
        toast("Sign-in failed: " + res.error, "error");
      }
    });
    return;
  }

  container.innerHTML = "";
  meetings.forEach((meeting) => {
    const startDate = new Date(meeting.start);
    const endDate = new Date(meeting.end);
    const now = new Date();
    const diffMs = startDate - now;
    const diffMin = Math.round(diffMs / 60000);

    let badgeClass = "badge-upcoming";
    let badgeText = formatRelativeTime(startDate);

    if (diffMs < 0 && diffMs > -2 * 60 * 60 * 1000) {
      badgeClass = "badge-live";
      badgeText = "LIVE";
    } else if (diffMin <= 30 && diffMin > 0) {
      badgeClass = "badge-soon";
      badgeText = `in ${diffMin}m`;
    } else if (startDate.toDateString() === now.toDateString()) {
      badgeClass = "badge-today";
      badgeText = "Today " + formatTime(startDate);
    }

    const isArmed = Object.values(activeBots).some(
      (b) => b.meetingId === meeting.id && b.status !== "done"
    );

    const card = document.createElement("div");
    card.className = "meeting-card";
    card.innerHTML = `
      <div class="meeting-card-top">
        <div class="meeting-title">${escHtml(meeting.title)}</div>
        <span class="badge ${badgeClass}">${badgeText}</span>
      </div>
      <div class="meeting-meta">
        <span class="meeting-time">${formatTime(startDate)} – ${formatTime(endDate)}</span>
        <span class="meeting-attendees">· ${meeting.attendees.length} attendees</span>
      </div>
      <div class="meeting-card-actions">
        <button class="btn-arm" data-id="${meeting.id}" ${isArmed ? "disabled" : ""}>
          ${isArmed ? "Notetaker Added" : "Add Notetaker"}
        </button>
        ${meeting.meetLink ? `<a href="${meeting.meetLink}" target="_blank" class="btn-join">Join ↗</a>` : ""}
      </div>`;

    card.querySelector(".btn-arm").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span> Arming…`;
      const res = await chrome.runtime.sendMessage({ type: "ARM_BOT", meeting });
      if (res.ok) {
        btn.innerHTML = "Notetaker Added";
        toast("Notetaker added to " + meeting.title, "success");
        await loadAll();
      } else {
        btn.disabled = false;
        btn.innerHTML = "Add Notetaker";
        toast("Error: " + res.error, "error");
      }
    });

    container.appendChild(card);
  });
}

// ── Active Bots Tab ───────────────────────────
function renderActiveBots(activeBots) {
  const container = document.getElementById("active-bots-list");
  const now = Date.now();
  const active = Object.entries(activeBots).filter(([, b]) => {
    if (b.status === "done") return false;
    if (!b.meetingStart) return false;
    const start = new Date(b.meetingStart).getTime();
    const hoursSinceStart = (now - start) / 3600000;
    return hoursSinceStart >= 0 && hoursSinceStart < 72;
  });

  if (!active.length) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No active bots right now</p>
        <span class="empty-hint">No meetings in the past 72 hours</span>
      </div>`;
    return;
  }

  container.innerHTML = "";
  active.forEach(([, bot]) => {
    const start = new Date(bot.meetingStart).getTime();
    const hoursSinceStart = (now - start) / 3600000;
    const callLikelyOver = hoursSinceStart > 2;
    const stuckStatuses = ["joining", "in_call_not_recording", "unknown"];
    const effectiveStatus = callLikelyOver && stuckStatuses.includes(bot.status)
      ? "call_ended"
      : bot.status;

    const statusLabel = {
      joining: "Joining meeting…",
      in_call_not_recording: "In call, waiting to record",
      in_call_recording: "Recording & transcribing",
      call_ended: "Call ended",
      unknown: "Connecting…",
    }[effectiveStatus] || effectiveStatus;

    const isRecording = effectiveStatus === "in_call_recording";

    const card = document.createElement("div");
    card.className = "bot-card";
    card.innerHTML = `
      <div class="bot-card-title">${escHtml(bot.meetingTitle)}</div>
      <div class="bot-status-row">
        <div class="bot-status-dot ${isRecording ? "" : "idle"}"></div>
        <span class="bot-status-text">${statusLabel}</span>
      </div>
      <div class="bot-id">Bot ID: ${bot.botId}</div>`;
    container.appendChild(card);
  });
}

// ── Summaries Tab ─────────────────────────────
function renderSummaries(summaries) {
  const container = document.getElementById("summaries-list");
  const entries = Object.entries(summaries).sort((a, b) => b[1].processedAt - a[1].processedAt);

  if (!entries.length) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No summaries yet</p>
        <span class="empty-hint">Summaries appear after meetings end</span>
      </div>`;
    return;
  }

  container.innerHTML = "";
  entries.forEach(([id, s]) => {
    const card = document.createElement("div");
    card.className = "summary-card";
    card.innerHTML = `
      <div class="summary-card-title">${escHtml(s.meetingTitle)}</div>
      <div class="summary-card-meta">${formatDateFull(new Date(s.meetingStart))} · ${s.attendance?.length || 0} attendees</div>
      <div class="summary-card-preview">${escHtml(s.summary || "")}</div>
      ${s.actionItems?.length ? `<div class="action-count">${s.actionItems.length} action items</div>` : ""}`;

    card.addEventListener("click", () => openSummaryModal(id, s));
    container.appendChild(card);
  });
}

// ── Summary Modal ─────────────────────────────
function setupModal() {
  document.getElementById("modal-overlay").addEventListener("click", (e) => {
    if (e.target === document.getElementById("modal-overlay")) closeModal();
  });
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("btn-post-slack").addEventListener("click", postToSlack);
  document.getElementById("btn-copy-summary").addEventListener("click", copySummary);
}

function openSummaryModal(id, summary) {
  activeSummary = summary;
  activeSummaryId = id;

  document.getElementById("modal-title").textContent = summary.meetingTitle;
  document.getElementById("modal-date").textContent = formatDateFull(new Date(summary.meetingStart));

  const body = document.getElementById("modal-body");
  body.innerHTML = "";

  // Summary section
  appendSection(body, "Summary", `<p class="modal-section-body">${escHtml(summary.summary || "—")}</p>`);

  // Action Items
  if (summary.actionItems?.length) {
    const itemsHtml = summary.actionItems
      .map(
        (item, i) => `
        <div class="action-item">
          <div class="action-num">${i + 1}</div>
          <div class="action-body">
            <div class="action-task">${escHtml(item.task)}</div>
            <div class="action-meta">
              <span>${escHtml(item.owner)}</span>
              <span>${escHtml(item.deadline)}</span>
              <span class="priority-${item.priority}">${item.priority}</span>
            </div>
          </div>
        </div>`
      )
      .join("");
    appendSection(body, `Action Items (${summary.actionItems.length})`, itemsHtml);
  }

  // Key Decisions
  if (summary.keyDecisions?.length) {
    const decisionsHtml = summary.keyDecisions
      .map((d) => `<div class="pill">${escHtml(d)}</div>`)
      .join("");
    appendSection(body, "Key Decisions", decisionsHtml);
  }

  // Topics
  if (summary.topics?.length) {
    const topicsHtml = summary.topics.map((t) => `<span class="pill">${escHtml(t)}</span>`).join("");
    appendSection(body, "Topics", topicsHtml);
  }

  // Attendance
  if (summary.attendance?.length) {
    const attHtml = summary.attendance.map((a) => `<span class="pill">${escHtml(a)}</span>`).join("");
    appendSection(body, "Attendance", attHtml);
  }

  // Blockers
  if (summary.blockers?.length) {
    const blockersHtml = summary.blockers
      .map((b) => `<div class="pill" style="border-color:var(--accent);color:var(--accent)">${escHtml(b)}</div>`)
      .join("");
    appendSection(body, "Blockers / Risks", blockersHtml);
  }

  document.getElementById("modal-overlay").classList.remove("hidden");
}

function appendSection(parent, label, contentHtml) {
  const div = document.createElement("div");
  div.innerHTML = `<div class="modal-section-label">${label}</div>${contentHtml}`;
  parent.appendChild(div);
}

function closeModal() {
  document.getElementById("modal-overlay").classList.add("hidden");
  activeSummary = null;
  activeSummaryId = null;
}

async function postToSlack() {
  if (!activeSummary) return;
  const btn = document.getElementById("btn-post-slack");
  btn.innerHTML = `<span class="spinner"></span> Posting…`;
  btn.disabled = true;

  const res = await chrome.runtime.sendMessage({
    type: "POST_SLACK",
    summary: activeSummary,
    meetingId: activeSummaryId,
  });

  btn.disabled = false;
  btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22.08 9C19.56 1.96 11.81-1.07 4.77 1.46S-1.07 12.19 1.46 19.23 12.19 25.07 19.23 22.54 25.07 14.81 22.08 9z"/><path d="M14.31 14.31L9.69 9.69M14.31 9.69L9.69 14.31"/></svg> Post to Slack`;

  if (res.ok) {
    toast("Posted to Slack", "success");
  } else {
    toast("Slack error: " + res.error, "error");
  }
}

function copySummary() {
  if (!activeSummary) return;
  const lines = [
    `# ${activeSummary.meetingTitle}`,
    `Date: ${formatDateFull(new Date(activeSummary.meetingStart))}`,
    "",
    "## Summary",
    activeSummary.summary,
    "",
    "## Action Items",
    ...(activeSummary.actionItems || []).map(
      (i, n) => `${n + 1}. ${i.task} → ${i.owner} (${i.deadline})`
    ),
    "",
    "## Key Decisions",
    ...(activeSummary.keyDecisions || []).map((d) => `- ${d}`),
  ];
  navigator.clipboard.writeText(lines.join("\n"));
  toast("Copied to clipboard", "success");
}

// ── Background messages ───────────────────────
function listenToBackground() {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "MEETINGS_UPDATED") renderMeetings(msg.meetings, {});
    if (msg.type === "BOT_ARMED") loadAll();
    if (msg.type === "BOT_STATUS") loadAll();
    if (msg.type === "SUMMARY_READY") {
      loadAll();
      toast(`Summary ready: ${msg.summary?.meetingTitle || "meeting"}`, "success");
    }
  });
}

// ── Helpers ───────────────────────────────────
function formatTime(date) {
  return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

function formatDateFull(date) {
  return date.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

function formatRelativeTime(date) {
  const diff = date - new Date();
  const hours = Math.round(diff / 3600000);
  const days = Math.round(diff / 86400000);
  if (hours < 1) return "< 1hr";
  if (hours < 24) return `in ${hours}h`;
  if (days === 1) return "Tomorrow";
  return `in ${days}d`;
}

function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function toast(msg, type = "") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = `toast ${type}`;
  setTimeout(() => (el.className = "toast hidden"), 3000);
}
