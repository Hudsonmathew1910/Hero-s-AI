/* ══════════════════════════════════════════════════════════════
   Infinsight Frontend JS
══════════════════════════════════════════════════════════════ */

// ── State ──────────────────────────────────────────────────────
const state = {
  currentSessionId: null,
  currentSession: null,
  sessions: [],
  selectedFile: null,
  polling: null,
};

// ── Init ───────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadSessions();
  // Restore theme
  const saved = localStorage.getItem("ins_theme") || localStorage.getItem("theme") || "dark";
  document.documentElement.setAttribute("data-theme", saved);
});

// ── Theme ──────────────────────────────────────────────────────
function toggleInsTheme() {
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("ins_theme", next);
}

// ── Sidebar ────────────────────────────────────────────────────
function toggleInsSidebar() {
  document.getElementById("insSidebar").classList.toggle("open");
}

// ── Notification ───────────────────────────────────────────────
function notify(msg, type = "info") {
  const el = document.getElementById("insNotif");
  el.textContent = msg;
  el.className = `ins-notif show ${type}`;
  setTimeout(() => el.classList.remove("show"), 3500);
}

// ── Load sessions ──────────────────────────────────────────────
async function loadSessions() {
  try {
    const res = await fetch("/infinsight/sessions/");
    if (!res.ok) return;
    const data = await res.json();
    if (data.status !== "success") return;
    state.sessions = data.sessions;
    renderSessionsList();
  } catch (e) {
    console.error("Load sessions:", e);
  }
}

function renderSessionsList() {
  const list = document.getElementById("sessionsList");
  const empty = document.getElementById("sessionsEmpty");

  // Remove all session items (keep empty state)
  list.querySelectorAll(".ins-session-item").forEach(el => el.remove());

  if (!state.sessions.length) {
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";

  state.sessions.forEach(s => {
    const item = document.createElement("div");
    item.className = "ins-session-item" + (s.session_id === state.currentSessionId ? " active" : "");
    item.dataset.sessionId = s.session_id;

    const icon = fileIcon(s.file_type);
    const msgs = s.message_count;
    const when = new Date(s.updated_at).toLocaleDateString();

    item.innerHTML = `
      <div class="ins-session-icon ${s.file_type}"><i class="${icon}"></i></div>
      <div class="ins-session-info">
        <div class="ins-session-name">${esc(s.session_name)}</div>
        <div class="ins-session-meta">${msgs} msg${msgs !== 1 ? 's' : ''} · ${when}</div>
      </div>
      <div class="ins-status-dot ${s.status}"></div>
      <button class="ins-session-del" onclick="deleteSession('${s.session_id}', event)" title="Delete">
        <i class="fa-solid fa-trash"></i>
      </button>
    `;
    item.addEventListener("click", () => openSession(s.session_id));
    list.appendChild(item);
  });
}

function fileIcon(type) {
  const icons = { csv: "fa-solid fa-file-csv", excel: "fa-solid fa-file-excel", pdf: "fa-solid fa-file-pdf" };
  return icons[type] || "fa-solid fa-file";
}

// ── Open session ───────────────────────────────────────────────
async function openSession(sessionId) {
  try {
    const res = await fetch(`/infinsight/session/${sessionId}/`);
    const data = await res.json();
    if (data.status !== "success") { notify("Could not load session.", "error"); return; }

    state.currentSessionId = sessionId;
    state.currentSession = data.session;

    // Update topbar
    document.getElementById("currentSessionTitle").textContent = data.session.session_name;
    const badge = document.getElementById("currentSessionBadge");
    badge.textContent = data.session.file_type.toUpperCase();
    badge.className = `ins-session-badge ${data.session.file_type}`;

    // Show chat area
    document.getElementById("insWelcome").style.display = "none";
    const chatArea = document.getElementById("insChatArea");
    chatArea.classList.add("active");

    // Render messages
    const messagesEl = document.getElementById("insMessages");
    messagesEl.innerHTML = "";
    data.messages.forEach(m => {
      appendMessage("user", m.user_message);
      appendMessage("ai", m.ai_response, m.model_used);
    });
    scrollToBottom();

    // Processing banner
    if (data.session.status === "processing") {
      startPolling(sessionId);
    } else {
      stopPolling();
      document.getElementById("processingBanner").classList.remove("visible");
    }

    // Update sidebar active state
    renderSessionsList();

    // Close sidebar on mobile
    document.getElementById("insSidebar").classList.remove("open");

  } catch (e) {
    notify("Failed to load session.", "error");
  }
}

// ── Status polling (for processing sessions) ───────────────────
function startPolling(sessionId) {
  document.getElementById("processingBanner").classList.add("visible");
  stopPolling();
  state.polling = setInterval(async () => {
    try {
      const res = await fetch(`/infinsight/session/${sessionId}/status/`);
      const data = await res.json();
      if (data.session_status === "ready") {
        stopPolling();
        document.getElementById("processingBanner").classList.remove("visible");
        notify("✅ File indexed! You can now ask questions.", "success");
        // Refresh sessions list
        await loadSessions();
        renderSessionsList();
        // Update current session
        state.currentSession.status = "ready";
      } else if (data.session_status === "error") {
        stopPolling();
        document.getElementById("processingBanner").classList.remove("visible");
        notify("❌ Indexing failed: " + (data.error || "Unknown error"), "error");
      }
    } catch (e) {}
  }, 4000);
}

function stopPolling() {
  if (state.polling) { clearInterval(state.polling); state.polling = null; }
}

// ── Message rendering ──────────────────────────────────────────
function appendMessage(role, content, model = "") {
  const messagesEl = document.getElementById("insMessages");
  const row = document.createElement("div");
  row.className = "ins-msg-row";

  const isUser = role === "user";
  const avatarLabel = isUser ? "Y" : "<i class='fa-solid fa-chart-line' style='font-size:0.7rem'></i>";
  const senderLabel = isUser ? "You" : "Infinsight";

  row.innerHTML = `
    <div class="ins-avatar ${isUser ? 'user' : 'ai'}">${avatarLabel}</div>
    <div class="ins-msg-content">
      <div class="ins-sender ${isUser ? 'user' : 'ai'}">${senderLabel}</div>
      <div class="ins-bubble">${isUser ? esc(content) : renderMarkdown(content)}</div>
    </div>
  `;
  messagesEl.appendChild(row);
}

function appendTyping() {
  const messagesEl = document.getElementById("insMessages");
  const row = document.createElement("div");
  row.className = "ins-msg-row";
  row.id = "ins-typing-row";
  row.innerHTML = `
    <div class="ins-avatar ai"><i class="fa-solid fa-chart-line" style="font-size:0.7rem"></i></div>
    <div class="ins-msg-content">
      <div class="ins-sender ai">Infinsight</div>
      <div class="ins-typing">
        <span class="ins-typing-label">Analyzing</span>
        <div class="ins-tb-wrap">
          <div class="ins-tb"></div><div class="ins-tb"></div><div class="ins-tb"></div>
        </div>
      </div>
    </div>
  `;
  messagesEl.appendChild(row);
  scrollToBottom();
  return row;
}

function removeTyping() {
  const el = document.getElementById("ins-typing-row");
  if (el) el.remove();
}

function scrollToBottom() {
  const el = document.getElementById("insMessages");
  el.scrollTop = el.scrollHeight;
}

// ── Simple Markdown renderer ───────────────────────────────────
function renderMarkdown(text) {
  let html = esc(text);

  // Code blocks (before inline code)
  html = html.replace(/```([a-z]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
  });
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Italic
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  // Headings
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // Unordered list
  html = html.replace(/^\- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>(\n)?)+/g, m => `<ul>${m}</ul>`);
  // Ordered list
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  // Tables
  html = renderTable(html);
  // Line breaks
  html = html.replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>');
  html = '<p>' + html + '</p>';
  // Clean up empty p tags
  html = html.replace(/<p><\/p>/g, '');

  return html;
}

function renderTable(html) {
  const tableRegex = /(\|.+\|[\r\n]+\|[-| :]+\|[\r\n]+(?:\|.+\|[\r\n]*)+)/g;
  return html.replace(tableRegex, tableText => {
    const rows = tableText.trim().split('\n');
    if (rows.length < 2) return tableText;
    const headers = rows[0].split('|').filter(c => c.trim()).map(c => `<th>${c.trim()}</th>`).join('');
    const bodyRows = rows.slice(2).map(r => {
      const cells = r.split('|').filter(c => c.trim()).map(c => `<td>${c.trim()}</td>`).join('');
      return `<tr>${cells}</tr>`;
    }).join('');
    return `<table><thead><tr>${headers}</tr></thead><tbody>${bodyRows}</tbody></table>`;
  });
}

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Send message ───────────────────────────────────────────────
async function sendInsMessage() {
  const input = document.getElementById("insInput");
  const msg = input.value.trim();
  if (!msg || !state.currentSessionId) return;

  if (state.currentSession && state.currentSession.status === "processing") {
    notify("File is still being indexed. Please wait.", "info");
    return;
  }

  input.value = "";
  input.style.height = "auto";
  document.getElementById("insSendBtn").disabled = true;

  appendMessage("user", msg);
  const typingRow = appendTyping();
  scrollToBottom();

  try {
    const res = await fetch("/infinsight/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.currentSessionId, message: msg }),
    });
    const data = await res.json();
    removeTyping();

    if (data.status === "success") {
      appendMessage("ai", data.reply, data.model);
      // Update message count in sidebar
      await loadSessions();
      renderSessionsList();
    } else {
      appendMessage("ai", "⚠️ " + (data.message || "Something went wrong."));
    }
  } catch (e) {
    removeTyping();
    appendMessage("ai", "⚠️ Network error. Please try again.");
  }
  scrollToBottom();
}

function handleInsKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendInsMessage();
  }
}

function insAutoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 180) + "px";
}

function insToggleSend() {
  const val = document.getElementById("insInput").value.trim();
  document.getElementById("insSendBtn").disabled = !val;
}

// ── Upload modal ───────────────────────────────────────────────
function openUploadModal() {
  document.getElementById("insUploadModal").classList.add("active");
}

function closeUploadModal() {
  document.getElementById("insUploadModal").classList.remove("active");
  clearSelectedFile();
}

function handleModalDrag(e) {
  e.preventDefault();
  document.getElementById("insFileDrop").classList.add("drag-over");
}

function handleModalDrop(e) {
  e.preventDefault();
  document.getElementById("insFileDrop").classList.remove("drag-over");
  const files = e.dataTransfer.files;
  if (files.length) applySelectedFile(files[0]);
}

function handleWelcomeDrag(e) { e.preventDefault(); document.getElementById("welcomeDropZone").classList.add("drag-over"); }
function handleWelcomeDrop(e) {
  e.preventDefault();
  document.getElementById("welcomeDropZone").classList.remove("drag-over");
  const files = e.dataTransfer.files;
  if (files.length) { openUploadModal(); setTimeout(() => applySelectedFile(files[0]), 100); }
}

function handleFileSelect(input) {
  if (input.files.length) applySelectedFile(input.files[0]);
}

function applySelectedFile(file) {
  const allowed = ["csv", "xlsx", "xls", "pdf"];
  const ext = file.name.split(".").pop().toLowerCase();
  if (!allowed.includes(ext)) { notify(`File type ".${ext}" not supported.`, "error"); return; }
  if (file.size > 20 * 1024 * 1024) { notify("File too large. Max 20MB.", "error"); return; }

  state.selectedFile = file;

  document.getElementById("selectedFileName").textContent = file.name;
  document.getElementById("selectedFileSize").textContent = formatBytes(file.size);
  document.getElementById("selectedFileDisplay").classList.add("visible");
  document.getElementById("insFileDrop").classList.add("has-file");
  document.getElementById("uploadSubmitBtn").disabled = false;
}

function clearSelectedFile() {
  state.selectedFile = null;
  document.getElementById("selectedFileDisplay").classList.remove("visible");
  document.getElementById("insFileDrop").classList.remove("has-file");
  document.getElementById("uploadSubmitBtn").disabled = true;
  document.getElementById("insFileInput").value = "";
  document.getElementById("uploadProgress").classList.remove("visible");
  document.getElementById("uploadProgressBar").style.width = "0%";
}

async function submitUpload() {
  if (!state.selectedFile) return;

  const btn = document.getElementById("uploadSubmitBtn");
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Uploading…';

  // Show progress
  document.getElementById("uploadProgress").classList.add("visible");
  animateProgress();

  const formData = new FormData();
  formData.append("file", state.selectedFile);

  try {
    const res = await fetch("/infinsight/upload/", { method: "POST", body: formData });
    const data = await res.json();

    if (data.status === "success") {
      notify("File uploaded! Indexing started…", "success");
      closeUploadModal();
      await loadSessions();
      renderSessionsList();
      // Auto-open the new session
      openSession(data.session.session_id);
    } else {
      notify(data.message || "Upload failed.", "error");
      btn.disabled = false;
      btn.innerHTML = '<i class="fa-solid fa-rocket"></i> Start Analysis';
      document.getElementById("uploadProgress").classList.remove("visible");
    }
  } catch (e) {
    notify("Network error. Please try again.", "error");
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-rocket"></i> Start Analysis';
  }
}

function animateProgress() {
  const bar = document.getElementById("uploadProgressBar");
  let w = 0;
  const iv = setInterval(() => {
    w = Math.min(w + Math.random() * 8, 90);
    bar.style.width = w + "%";
    if (w >= 90) clearInterval(iv);
  }, 200);
}

// ── Delete session ─────────────────────────────────────────────
async function deleteSession(sessionId, e) {
  e.stopPropagation();
  if (!confirm("Delete this analysis session? This cannot be undone.")) return;
  try {
    const res = await fetch(`/infinsight/session/${sessionId}/delete/`, { method: "POST" });
    const data = await res.json();
    if (data.status === "success") {
      notify("Session deleted.", "info");
      if (state.currentSessionId === sessionId) {
        state.currentSessionId = null;
        state.currentSession = null;
        document.getElementById("insChatArea").classList.remove("active");
        document.getElementById("insWelcome").style.display = "flex";
        document.getElementById("currentSessionTitle").textContent = "Infinsight";
        document.getElementById("currentSessionBadge").textContent = "AI Analyst";
        document.getElementById("currentSessionBadge").className = "ins-session-badge none";
      }
      await loadSessions();
      renderSessionsList();
    } else {
      notify("Delete failed.", "error");
    }
  } catch (e) {
    notify("Network error.", "error");
  }
}

// ── Helpers ────────────────────────────────────────────────────
function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}