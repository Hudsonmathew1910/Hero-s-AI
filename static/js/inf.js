/* ══════════════════════════════════════════════════════════════
   Infinsight Frontend JS
══════════════════════════════════════════════════════════════ */

/* ════════ CSRF TOKEN ════════ */
function getCsrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
}

// ── State ──────────────────────────────────────────────────────
const state = {
  currentSessionId: null,
  currentSession: null,
  sessions: [],
  selectedFile: null,
  polling: null,
  // Auth state
  loggedIn: false,
  user: null,
  hasGeminiKey: false,
};

// ── Init ───────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await bootstrapAuth();
  
  // Restore theme
  const saved = localStorage.getItem("ins_theme") || localStorage.getItem("theme") || "dark";
  document.documentElement.setAttribute("data-theme", saved);

  // Enter key in API key input
  const ki = document.getElementById("sidebarGeminiKey");
  if (ki) {
    ki.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); saveGeminiKey(); }
    });
  }
  // Enter key in auth forms
  ["signinEmail","signinPassword"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("keydown", (e) => { if (e.key === "Enter") doSignin(); });
  });
  ["signupName","signupEmail","signupPassword"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("keydown", (e) => { if (e.key === "Enter") doSignup(); });
  });
});

// ── Auth Logic ─────────────────────────────────────────────────
async function bootstrapAuth() {
  try {
    const res  = await fetch("/api/auth/check-session", { credentials: 'include' });
    const data = await res.json();

    if (data.logged_in) {
      state.loggedIn = true;
      state.user     = data.user;
      await checkGeminiStatus();
      renderAuthUI();
      loadSessions();
    } else {
      state.loggedIn = false;
      renderAuthUI();
      showAuthModal();
    }
  } catch (e) {
    console.error("Session check failed:", e);
    renderAuthUI();
    showAuthModal();
  }
}

function renderAuthUI() {
  const area = document.getElementById("authArea");
  if (!area) return;

  if (!state.loggedIn) {
    area.innerHTML = `<button class="ins-signin-btn" onclick="showAuthModal()">
      <i class="fa-solid fa-right-to-bracket"></i> Sign In
    </button>`;
    const apikeySection = document.getElementById("sidebarApikeySection");
    if (apikeySection) apikeySection.style.display = "none";
    const nokeyBanner = document.getElementById("nokeyBanner");
    if (nokeyBanner) nokeyBanner.classList.remove("visible");
    return;
  }

  const initials = (state.user.name || "?")[0].toUpperCase();
  area.innerHTML = `
    <div class="ins-user-menu" id="insUserMenu">
      <div class="ins-user-chip" onclick="toggleUserMenu(event)">
        <div class="ins-user-avatar">${initials}</div>
        <span class="ins-user-name">${esc(state.user.name)}</span>
        <i class="fa-solid fa-chevron-down" style="font-size:0.65rem;color:var(--ins-muted,#6b7280);"></i>
      </div>
      <div class="ins-user-dropdown" id="userDropdown">
        <div style="padding:0.4rem 0.75rem 0.6rem;border-bottom:1px solid var(--ins-border,rgba(255,255,255,0.08));margin-bottom:4px;">
          <div style="font-size:0.8rem;font-weight:700;color:var(--ins-text,#e8eaf0);">${esc(state.user.name)}</div>
          <div style="font-size:0.72rem;color:var(--ins-muted,#6b7280);margin-top:2px;">${esc(state.user.email)}</div>
        </div>
        <button class="ins-dd-item danger" id="logoutBtn">
          <i class="fa-solid fa-right-from-bracket"></i> Sign Out
        </button>
      </div>
    </div>`;

  const apikeySection = document.getElementById("sidebarApikeySection");
  if (apikeySection) apikeySection.style.display = "block";
  updateApikeyDot();

  // Attach logout listener
  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) {
    console.log("Found logoutBtn, attaching listener");
    logoutBtn.addEventListener("click", (e) => {
      console.log("logoutBtn clicked!");
      e.stopPropagation();
      doLogout();
    });
  }
}

function toggleUserMenu(e) {
  console.log("toggleUserMenu called");
  e.stopPropagation();
  const dd = document.getElementById("userDropdown");
  if (dd) {
    dd.classList.toggle("open");
    console.log("Dropdown open state:", dd.classList.contains("open"));
  }
}

document.addEventListener("click", () => {
  const dd = document.getElementById("userDropdown");
  if (dd) dd.classList.remove("open");
});

function showAuthModal() {
  const modal = document.getElementById("authModal");
  if (modal) modal.classList.add("active");
}

function hideAuthModal() {
  const modal = document.getElementById("authModal");
  if (modal) modal.classList.remove("active");
  clearAuthErrors();
}

// Backdrop check helper for modals
function handleBackdropClick(e, modalId, canClose) {
  if (e.target.id === modalId && canClose) {
    hideAuthModal();
  }
}

function switchAuthTab(tab) {
  clearAuthErrors();
  const signinTab = document.getElementById("tabSignin");
  const signupTab = document.getElementById("tabSignup");
  const signinForm = document.getElementById("signinForm");
  const signupForm = document.getElementById("signupForm");

  if (signinTab) signinTab.classList.toggle("active", tab === "signin");
  if (signupTab) signupTab.classList.toggle("active", tab === "signup");
  if (signinForm) signinForm.style.display = tab === "signin" ? "block" : "none";
  if (signupForm) signupForm.style.display = tab === "signup" ? "block" : "none";
}

function clearAuthErrors() {
  ["signinEmailErr","signinPassErr","signinGeneralErr",
   "signupNameErr","signupEmailErr","signupPassErr","signupGeneralErr"].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = ""; el.classList.remove("visible"); }
  });
  ["signinEmail","signinPassword","signupName","signupEmail","signupPassword"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove("error");
  });
}

function showFieldError(fieldId, errId, msg) {
  const field = document.getElementById(fieldId);
  const err   = document.getElementById(errId);
  if (field) field.classList.add("error");
  if (err)   { err.textContent = msg; err.classList.add("visible"); }
}

function showGeneralError(errId, msg) {
  const el = document.getElementById(errId);
  if (el) { el.textContent = msg; el.style.display = "block"; el.classList.add("visible"); }
}

async function doSignin() {
  clearAuthErrors();
  const email    = document.getElementById("signinEmail").value.trim();
  const password = document.getElementById("signinPassword").value;

  if (!email)    { showFieldError("signinEmail",    "signinEmailErr", "Email is required"); return; }
  if (!password) { showFieldError("signinPassword", "signinPassErr",  "Password is required"); return; }

  const btn = document.getElementById("signinBtn");
  btn.disabled = true;
  const origHtml = btn.innerHTML;
  btn.innerHTML = `<span class="spin"><i class="fa-solid fa-spinner"></i></span> Signing in…`;

  try {
    const res  = await fetch("/api/auth/login", {
      method:  "POST",
      headers: { 
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken()
      },
      credentials: 'include',
      body:    JSON.stringify({ email, password }),
    });
    const data = await res.json();

    if (data.status === "success") {
      state.loggedIn = true;
      state.user     = data.user;
      await checkGeminiStatus();
      hideAuthModal();
      renderAuthUI();
      loadSessions();
      notify("Welcome back, " + data.user.name + "! 👋", "success");
    } else {
      showGeneralError("signinGeneralErr", data.message || "Invalid credentials");
    }
  } catch (e) {
    showGeneralError("signinGeneralErr", "Network error. Please try again.");
  } finally {
    btn.disabled = false;
    btn.innerHTML = origHtml;
  }
}

async function doSignup() {
  clearAuthErrors();
  const name     = document.getElementById("signupName").value.trim();
  const email    = document.getElementById("signupEmail").value.trim();
  const password = document.getElementById("signupPassword").value;

  let hasError = false;
  if (!name)     { showFieldError("signupName",     "signupNameErr", "Name is required"); hasError = true; }
  if (!email)    { showFieldError("signupEmail",    "signupEmailErr", "Email is required"); hasError = true; }
  if (!password) { showFieldError("signupPassword", "signupPassErr",  "Password is required"); hasError = true; }
  if (hasError)  return;

  const btn = document.getElementById("signupBtn");
  btn.disabled = true;
  const origHtml = btn.innerHTML;
  btn.innerHTML = `<span class="spin"><i class="fa-solid fa-spinner"></i></span> Creating account…`;

  try {
    const res  = await fetch("/api/auth/signup", {
      method:  "POST",
      headers: { 
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken()
      },
      credentials: 'include',
      body:    JSON.stringify({ name, email, password }),
    });
    const data = await res.json();

    if (data.status === "success") {
      state.loggedIn = true;
      state.user     = data.user;
      state.hasGeminiKey = false;
      hideAuthModal();
      renderAuthUI();
      loadSessions();
      notify("Account created! Welcome, " + data.user.name + " 🎉", "success");
      setTimeout(() => focusApiKeyInput(), 600);
    } else {
      showGeneralError("signupGeneralErr", data.message || "Signup failed");
    }
  } catch (e) {
    showGeneralError("signupGeneralErr", "Network error. Please try again.");
  } finally {
    btn.disabled = false;
    btn.innerHTML = origHtml;
  }
}

async function doLogout() {
  console.log("Logout initiated...");
  const token = getCookie('csrftoken');
  console.log("Token:", token ? "Found" : "Missing");
  
  try {
    const res = await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
      credentials: "include",
    });
    console.log("Server responded:", res.status);
    const data = await res.json();
    console.log("Server data:", data);
  } catch (e) {
    console.error("Fetch error:", e);
  }
  
  console.log("Cleaning up local state...");
  state.loggedIn = false;
  state.user = null;
  state.hasGeminiKey = false;
  state.currentSessionId = null;
  state.currentSession = null;

  renderAuthUI();
  
  // UI cleanup
  const list = document.getElementById("sessionsList");
  if (list) list.querySelectorAll(".ins-session-item").forEach(el => el.remove());
  
  const empty = document.getElementById("sessionsEmpty");
  if (empty) empty.style.display = "block";
  
  const chat = document.getElementById("insChatArea");
  if (chat) chat.classList.remove("active");
  
  const welcome = document.getElementById("insWelcome");
  if (welcome) welcome.style.display = "flex";
  
  const title = document.getElementById("currentSessionTitle");
  if (title) title.textContent = "Infinsight";
  
  const badge = document.getElementById("currentSessionBadge");
  if (badge) {
    badge.textContent = "AI Analyst";
    badge.className = "ins-session-badge none";
  }

  showAuthModal();
  notify("Signed out successfully.", "info");
}

// Helper to get CSRF token
function getCookie(name) {
  // First try to get it from the meta tag (best for HttpOnly cookies)
  if (name === 'csrftoken') {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
  }

  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

function googleLogin() {
  const next = window.location.pathname;
  window.location.href = `/auth/google?flow=signin&next=${encodeURIComponent(next)}`;
}

function togglePwd(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const isHidden = input.type === "password";
  input.type = isHidden ? "text" : "password";
  btn.querySelector("i").className = isHidden ? "fa-regular fa-eye-slash" : "fa-regular fa-eye";
}

// ── API Key Management ───────────────────────────────────────────
async function checkGeminiStatus() {
  try {
    const res  = await fetch("/api/keys/check", { credentials: 'include' });
    const data = await res.json();
    if (data.status === "success") {
      state.hasGeminiKey = !!data.keys?.gemini;
    }
  } catch (e) {
    state.hasGeminiKey = false;
  }
  updateApikeyDot();
}

function updateApikeyDot() {
  const dot   = document.getElementById("apikeyStatusDot");
  const input = document.getElementById("sidebarGeminiKey");
  const banner = document.getElementById("nokeyBanner");

  if (dot) dot.className = "ins-apikey-status" + (state.hasGeminiKey ? " ok" : "");
  if (input) input.placeholder = state.hasGeminiKey ? "••••••••••••••••" : "AIza…";
  if (banner) {
    if (!state.hasGeminiKey && state.loggedIn) {
      banner.classList.add("visible");
    } else {
      banner.classList.remove("visible");
    }
  }
}

async function saveGeminiKey() {
  const input = document.getElementById("sidebarGeminiKey");
  const btn   = document.getElementById("sidebarApikeySaveBtn");
  const key   = input.value.trim();

  if (!key) {
    notify("Please enter your Gemini API key.", "error");
    input.focus();
    return;
  }

  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = "Saving…";

  try {
    const res  = await fetch("/api/keys/save", {
      method:  "POST",
      headers: { 
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken()
      },
      credentials: 'include',
      body:    JSON.stringify({ gemini: key }),
    });
    const data = await res.json();

    if (data.status === "success") {
      state.hasGeminiKey = true;
      input.value = "";
      updateApikeyDot();
      notify("Gemini API key saved ✓", "success");
    } else {
      notify(data.message || "Failed to save key.", "error");
    }
  } catch (e) {
    notify("Network error. Please try again.", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}

function focusApiKeyInput() {
  const input = document.getElementById("sidebarGeminiKey");
  if (input) {
    document.getElementById("insSidebar").classList.add("open");
    setTimeout(() => input.focus(), 100);
  }
}

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
  if (!el) return;
  el.textContent = msg;
  el.className = `ins-notif show ${type}`;
  setTimeout(() => el.classList.remove("show"), 3500);
}

// ── Load sessions ──────────────────────────────────────────────
async function loadSessions() {
  try {
    const res = await fetch("/infinsight/sessions/", { credentials: 'include' });
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
  if (!list || !empty) return;

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
    const res = await fetch(`/infinsight/session/${sessionId}/`, { credentials: 'include' });
    const data = await res.json();
    if (data.status !== "success") { notify("Could not load session.", "error"); return; }

    state.currentSessionId = sessionId;
    state.currentSession = data.session;

    // Update topbar
    const titleEl = document.getElementById("currentSessionTitle");
    if (titleEl) titleEl.textContent = data.session.session_name;
    const badge = document.getElementById("currentSessionBadge");
    if (badge) {
      badge.textContent = data.session.file_type.toUpperCase();
      badge.className = `ins-session-badge ${data.session.file_type}`;
    }

    // Show chat area
    const welcome = document.getElementById("insWelcome");
    if (welcome) welcome.style.display = "none";
    const chatArea = document.getElementById("insChatArea");
    if (chatArea) chatArea.classList.add("active");

    // Render messages
    const messagesEl = document.getElementById("insMessages");
    if (messagesEl) {
      messagesEl.innerHTML = "";
      data.messages.forEach(m => {
        appendMessage("user", m.user_message);
        appendMessage("ai", m.ai_response, m.model_used);
      });
      scrollToBottom();
    }

    // Processing banner
    if (data.session.status === "processing") {
      startPolling(sessionId);
    } else {
      stopPolling();
      const banner = document.getElementById("processingBanner");
      if (banner) banner.classList.remove("visible");
    }

    // Update sidebar active state
    renderSessionsList();

    // Close sidebar on mobile
    const sidebar = document.getElementById("insSidebar");
    if (sidebar) sidebar.classList.remove("open");

  } catch (e) {
    notify("Failed to load session.", "error");
  }
}

// ── Status polling (for processing sessions) ───────────────────
function startPolling(sessionId) {
  const banner = document.getElementById("processingBanner");
  if (banner) banner.classList.add("visible");
  stopPolling();
  state.polling = setInterval(async () => {
    try {
      const res = await fetch(`/infinsight/session/${sessionId}/status/`, { credentials: 'include' });
      const data = await res.json();
      if (data.session_status === "ready") {
        stopPolling();
        if (banner) banner.classList.remove("visible");
        notify("✅ File indexed! You can now ask questions.", "success");
        // Refresh sessions list
        await loadSessions();
        renderSessionsList();
        // Update current session
        if (state.currentSession) state.currentSession.status = "ready";
      } else if (data.session_status === "error") {
        stopPolling();
        if (banner) banner.classList.remove("visible");
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
  if (!messagesEl) return;
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
  if (!messagesEl) return null;
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
  if (el) el.scrollTop = el.scrollHeight;
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
  // Robust table detection: optional leading pipes, requires separator with at least one dash and at least one pipe
  const tableRegex = /^([ \t]*\|?.*\|.*)\n([ \t]*\|?[:\- ]*[-]+[:\- ]*\|[:\- |]*)\n((?:[ \t]*\|?.*\|.*\n?)*)/gm;
  return html.replace(tableRegex, tableText => {
    const rows = tableText.trim().split('\n');
    if (rows.length < 2) return tableText;
    
    const parseRow = (row) => {
      return row.trim().replace(/^\||\|$/g, '').split('|').map(c => {
        let cell = c.trim();
        // Restore <br> if it was escaped by esc() earlier
        cell = cell.replace(/&lt;br\s*\/?&gt;/gi, '<br>');
        return cell;
      });
    };

    const headers = parseRow(rows[0]).map(c => `<th>${c}</th>`).join('');
    const bodyRows = rows.slice(2).map(r => {
      const cells = parseRow(r).map(c => `<td>${c}</td>`).join('');
      return `<tr>${cells}</tr>`;
    }).join('');
    
    return `<div class="ins-table-wrap"><table><thead><tr>${headers}</tr></thead><tbody>${bodyRows}</tbody></table></div>`;
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
  if (!input) return;
  const msg = input.value.trim();
  if (!msg || !state.currentSessionId) return;

  if (state.currentSession && state.currentSession.status === "processing") {
    notify("File is still being indexed. Please wait.", "info");
    return;
  }

  input.value = "";
  input.style.height = "auto";
  const sendBtn = document.getElementById("insSendBtn");
  if (sendBtn) sendBtn.disabled = true;

  appendMessage("user", msg);
  const typingRow = appendTyping();
  scrollToBottom();

  try {
    const res = await fetch("/infinsight/chat/", {
      method: "POST",
      headers: { 
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken()
      },
      credentials: 'include',
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
  const input = document.getElementById("insInput");
  const sendBtn = document.getElementById("insSendBtn");
  if (input && sendBtn) {
    const val = input.value.trim();
    sendBtn.disabled = !val;
  }
}

// ── Upload gate (auth + API key checks) ──────────────────────────
function handleUploadClick() {
  if (!state.loggedIn) {
    notify("Please sign in to upload a file.", "info");
    showAuthModal();
    return;
  }
  if (!state.hasGeminiKey) {
    notify("Gemini API key not configured. Please provide your api key", "error");
    const banner = document.getElementById("nokeyBanner");
    if (banner) banner.classList.add("visible");
    focusApiKeyInput();
    return;
  }
  openUploadModal();
}

// ── Upload modal ───────────────────────────────────────────────
function openUploadModal() {
  const modal = document.getElementById("insUploadModal");
  if (modal) modal.classList.add("active");
}

function closeUploadModal() {
  const modal = document.getElementById("insUploadModal");
  if (modal) modal.classList.remove("active");
  clearSelectedFile();
}

function handleModalDrag(e) {
  e.preventDefault();
  const drop = document.getElementById("insFileDrop");
  if (drop) drop.classList.add("drag-over");
}

function handleModalDrop(e) {
  e.preventDefault();
  const drop = document.getElementById("insFileDrop");
  if (drop) drop.classList.remove("drag-over");
  const files = e.dataTransfer.files;
  if (files.length) applySelectedFile(files[0]);
}

function handleWelcomeDrag(e) { e.preventDefault(); const dz = document.getElementById("welcomeDropZone"); if (dz) dz.classList.add("drag-over"); }
function handleWelcomeDrop(e) {
  e.preventDefault();
  const dz = document.getElementById("welcomeDropZone");
  if (dz) dz.classList.remove("drag-over");
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

  const nameEl = document.getElementById("selectedFileName");
  const sizeEl = document.getElementById("selectedFileSize");
  const display = document.getElementById("selectedFileDisplay");
  const drop = document.getElementById("insFileDrop");
  const submit = document.getElementById("uploadSubmitBtn");

  if (nameEl) nameEl.textContent = file.name;
  if (sizeEl) sizeEl.textContent = formatBytes(file.size);
  if (display) display.classList.add("visible");
  if (drop) drop.classList.add("has-file");
  if (submit) submit.disabled = false;
}

function clearSelectedFile() {
  state.selectedFile = null;
  const display = document.getElementById("selectedFileDisplay");
  const drop = document.getElementById("insFileDrop");
  const submit = document.getElementById("uploadSubmitBtn");
  const input = document.getElementById("insFileInput");
  const progress = document.getElementById("uploadProgress");
  const bar = document.getElementById("uploadProgressBar");

  if (display) display.classList.remove("visible");
  if (drop) drop.classList.remove("has-file");
  if (submit) submit.disabled = true;
  if (input) input.value = "";
  if (progress) progress.classList.remove("visible");
  if (bar) bar.style.width = "0%";
}

async function submitUpload() {
  if (!state.selectedFile) return;

  const btn = document.getElementById("uploadSubmitBtn");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Uploading…';
  }

  // Show progress
  const progress = document.getElementById("uploadProgress");
  if (progress) progress.classList.add("visible");
  animateProgress();

  const formData = new FormData();
  formData.append("file", state.selectedFile);

  try {
    const res = await fetch("/infinsight/upload/", { 
      method: "POST", 
      headers: { "X-CSRFToken": getCsrfToken() },
      credentials: 'include',
      body: formData 
    });
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
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-rocket"></i> Start Analysis';
      }
      if (progress) progress.classList.remove("visible");
    }
  } catch (e) {
    notify("Network error. Please try again.", "error");
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<i class="fa-solid fa-rocket"></i> Start Analysis';
    }
  }
}

function animateProgress() {
  const bar = document.getElementById("uploadProgressBar");
  if (!bar) return;
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
    const res = await fetch(`/infinsight/session/${sessionId}/delete/`, { 
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
      credentials: 'include'
    });
    const data = await res.json();
    if (data.status === "success") {
      notify("Session deleted.", "info");
      if (state.currentSessionId === sessionId) {
        state.currentSessionId = null;
        state.currentSession = null;
        const chatArea = document.getElementById("insChatArea");
        const welcome = document.getElementById("insWelcome");
        const title = document.getElementById("currentSessionTitle");
        const badge = document.getElementById("currentSessionBadge");

        if (chatArea) chatArea.classList.remove("active");
        if (welcome) welcome.style.display = "flex";
        if (title) title.textContent = "Infinsight";
        if (badge) {
          badge.textContent = "AI Analyst";
          badge.className = "ins-session-badge none";
        }
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
