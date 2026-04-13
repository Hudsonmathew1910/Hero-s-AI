/* ════════════════════════════════════════════════════════════════
   HERO AI — app.js
   1. TTS / STT:  strips emojis AND links before speaking
   2. Toggle / Save animations fixed in Personalization modal
   3. Voice-chat AI reply panel is scrollable for long text
   4. AI waits 3 s of silence after user stops speaking, THEN replies
   5. TTS disabled for coding & file_handle modes
   6. Mute button added near input (default muted, no effect on voice chat)
   7. URLs in AI replies are rendered as clickable links
   8. Web search "Here is what I found for / Wikipedia:" prefix stripped
   ════════════════════════════════════════════════════════════════ */

/* ════════ GLOBAL STATE ════════ */
let messages = [];
let attachedFiles = [];
let isLoading = false;
let currentModel = 'Baymax';
let inlineMicOn = false;
let inlineRecog = null;
let userMenuOpen = false;
let currentUser = null;
let plusMenuOpen = false;
let activeMode = null;
let tempChatActive = false;
let currentSessionId = null;

/* Mute state — default MUTED */
let isMuted = true;

/* User Settings State */
let userSettings = {
  autoReadResponses: true,
  compactLayout: false,
  rememberHistory: true,
  syntaxHighlighting: true,
  enableCustomInstructions: true
};

/* Voice State */
let voiceActive = false;
let voiceRecog = null;
let audioCtx = null;
let analyser = null;
let animFrame = null;
let mediaStream = null;
let ballPhase = 0;
let isListening = false;
const VOICE_STATE = { IDLE: 'idle', LISTENING: 'listening', THINKING: 'thinking', SPEAKING: 'speaking' };
let voiceState = VOICE_STATE.IDLE;
let voiceFinalText = '';
let voiceInterimText = '';

/* FIX 4: 3-second silence timer before sending to AI */
let silenceTimer = null;
const SILENCE_DELAY_MS = 3000;

/* API Keys State */
let hasExistingApiKeys = false;

/* ════════ DOM HELPERS ════════ */
const $ = (id) => document.getElementById(id);
const $$ = (selector) => document.querySelectorAll(selector);

/* ── Helper to safely parse JSON from a response ── */
async function getJsonResponse(res) {
  const contentType = res.headers.get('content-type');
  if (!contentType || !contentType.includes('application/json')) {
    const text = await res.text();
    // Log for debugging but throw a clean user-facing error
    console.error(`Expected JSON but got ${contentType || 'unknown'}:`, text.slice(0, 500));
    throw new Error('Server returned an unexpected response format (HTML)');
  }
  return await res.json();
}

/* ════════ NOTIFICATION SYSTEM ════════ */
function showNotification(message, type = 'info') {
  const existing = document.querySelector('.custom-notification');
  if (existing) existing.remove();
  const notification = document.createElement('div');
  notification.className = `custom-notification ${type}`;
  notification.textContent = message;
  document.body.appendChild(notification);
  setTimeout(() => notification.classList.add('show'), 10);
  setTimeout(() => {
    notification.classList.remove('show');
    setTimeout(() => notification.remove(), 300);
  }, 3000);
}

/* ════════ CUSTOM CONFIRM DIALOG ════════ */
function showConfirm(message, onConfirm, onCancel, confirmText = 'Yes', cancelText = 'No') {
  const existing = document.querySelector('.custom-confirm');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.className = 'custom-confirm-overlay';
  const dialog = document.createElement('div');
  dialog.className = 'custom-confirm';
  dialog.innerHTML = `
    <div class="confirm-icon"><i class="fa-solid fa-circle-question"></i></div>
    <div class="confirm-message">${message}</div>
    <div class="confirm-buttons">
      <button class="confirm-btn cancel">${cancelText}</button>
      <button class="confirm-btn confirm">${confirmText}</button>
    </div>`;
  overlay.appendChild(dialog);
  document.body.appendChild(overlay);
  setTimeout(() => overlay.classList.add('show'), 10);
  const confirmBtn = dialog.querySelector('.confirm-btn.confirm');
  const cancelBtn  = dialog.querySelector('.confirm-btn.cancel');
  const close = (callback) => {
    overlay.classList.remove('show');
    setTimeout(() => { overlay.remove(); callback?.(); }, 300);
  };
  confirmBtn.onclick = () => close(onConfirm);
  cancelBtn.onclick  = () => close(onCancel);
  overlay.onclick    = (e) => { if (e.target === overlay) close(onCancel); };
}

/* ════════ SETTINGS MANAGEMENT ════════ */
async function loadUserSettings() {
  if (!currentUser) return;
  try {
    const res = await fetch('/api/user/profile', { method: 'GET', credentials: 'include' });
    const data = await getJsonResponse(res);
    if (data.status === 'success' && data.settings) {
      const s = data.settings;
      if ($('aboutName'))           $('aboutName').value           = s.user_name        || '';
      if ($('aboutRole'))           $('aboutRole').value           = s.user_role        || '';
      if ($('aboutInterests'))      $('aboutInterests').value      = s.user_interests   || '';
      if ($('instructionContext'))   $('instructionContext').value  = s.user_about_me    || '';
      if ($('instructionBehavior')) $('instructionBehavior').value = s.user_instruction || '';
      _loadDisplaySettings();
    }
  } catch (err) {
    console.error('Failed to load settings:', err);
    _loadDisplaySettings();
  }
}

function _loadDisplaySettings() {
  userSettings.autoReadResponses        = JSON.parse(localStorage.getItem('hero-auto-read')        ?? 'true');
  userSettings.compactLayout            = JSON.parse(localStorage.getItem('hero-compact-layout')   ?? 'false');
  userSettings.rememberHistory          = JSON.parse(localStorage.getItem('hero-remember-history') ?? 'true');
  userSettings.syntaxHighlighting       = JSON.parse(localStorage.getItem('hero-syntax-highlight') ?? 'true');
  userSettings.enableCustomInstructions = JSON.parse(localStorage.getItem('hero-custom-inst')      ?? 'true');
  _syncSettingsUI();
}

function _syncSettingsUI() {
  const map = {
    'autoReadResponses':       'autoReadResponses',
    'compactLayout':           'compactLayout',
    'rememberHistory':         'rememberHistory',
    'syntaxHighlighting':      'syntaxHighlighting',
    'enableCustomInstructions':'enableCustomInstructions',
  };
  Object.entries(map).forEach(([attr, key]) => {
    const btn = document.querySelector(`[data-setting="${attr}"]`);
    if (btn) btn.classList.toggle('on', !!userSettings[key]);
  });
  document.body.classList.toggle('compact-mode', userSettings.compactLayout);
}

function toggleSetting(settingName) {
  userSettings[settingName] = !userSettings[settingName];
  const storageKey = 'hero-' + settingName.replace(/([A-Z])/g, (m) => '-' + m.toLowerCase());
  localStorage.setItem(storageKey, JSON.stringify(userSettings[settingName]));
  const btn = document.querySelector(`[data-setting="${settingName}"]`);
  if (btn) {
    btn.style.transition = 'background 0.22s, transform 0.12s';
    btn.style.transform = 'scale(0.88)';
    setTimeout(() => { btn.style.transform = 'scale(1)'; }, 120);
  }
  _syncSettingsUI();
  showNotification(
    `${_getSettingLabel(settingName)} ${userSettings[settingName] ? 'enabled' : 'disabled'}`,
    'success'
  );
}

function _getSettingLabel(key) {
  const labels = {
    'autoReadResponses':       'Auto-read responses',
    'compactLayout':           'Compact layout',
    'rememberHistory':         'Conversation history',
    'syntaxHighlighting':      'Syntax highlighting',
    'enableCustomInstructions':'Custom instructions',
  };
  return labels[key] || key;
}

/* ════════ THEME MANAGEMENT ════════ */
function setTheme(theme, btn) {
  document.documentElement.setAttribute('data-theme', theme);
  $$('.theme-btn').forEach(b => b.classList.remove('active'));
  btn?.classList.add('active');
  localStorage.setItem('hero-theme', theme);
  _syncThemeSwitch(theme);
}

function _syncThemeSwitch(theme) {
  const checkbox = $('themeCheckbox');
  if (checkbox) checkbox.checked = (theme === 'light');
}

function toggleThemeSwitch(checkbox) {
  const theme = checkbox.checked ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('hero-theme', theme);
  const db = $('theme-dark-btn'), lb = $('theme-light-btn');
  if (theme === 'light') { lb?.classList.add('active'); db?.classList.remove('active'); }
  else                   { db?.classList.add('active'); lb?.classList.remove('active'); }
}

(function () {
  const saved = localStorage.getItem('hero-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  setTimeout(() => {
    _syncThemeSwitch(saved);
    if (saved === 'light') {
      $('theme-light-btn')?.classList.add('active');
      $('theme-dark-btn')?.classList.remove('active');
    }
  }, 50);
})();

/* ════════ MUTE BUTTON ════════ */
function toggleMute() {
  isMuted = !isMuted;
  _syncMuteBtn();
  if (isMuted) window.speechSynthesis?.cancel();
  showNotification(isMuted ? 'AI voice muted' : 'AI voice unmuted', 'info');
}

function _syncMuteBtn() {
  const btn = $('muteBtn');
  if (!btn) return;
  if (isMuted) {
    btn.innerHTML = '<i class="fa-solid fa-volume-xmark"></i>';
    btn.classList.remove('unmuted');
    btn.title = 'AI voice muted — click to unmute';
  } else {
    btn.innerHTML = '<i class="fa-solid fa-volume-high"></i>';
    btn.classList.add('unmuted');
    btn.title = 'AI voice on — click to mute';
  }
}

/* ════════ AUTHENTICATION ════════ */
function handleGoogleAuth(flow) { window.location.href = `/auth/google?flow=${flow || 'signin'}`; }

// Handle auth page loads with URL parameters
window.addEventListener('DOMContentLoaded', () => {
  const urlParams = new URLSearchParams(window.location.search);
  const action = urlParams.get('action');
  const error = urlParams.get('error');
  
  if (action === 'google_setup') {
    showAuthScreen();
    const tabLogin = $('tabLogin');
    const tabSignup = $('tabSignup');
    if (tabLogin) tabLogin.style.display = 'none';
    if (tabSignup) tabSignup.style.display = 'none';
    
    const loginForm = $('loginForm');
    const signupForm = $('signupForm');
    const googleSetupForm = $('googleSetupForm');
    
    if (loginForm) loginForm.style.display = 'none';
    if (signupForm) signupForm.style.display = 'none';
    if (googleSetupForm) googleSetupForm.style.display = 'flex';
    
    // Remove query param cleanly
    window.history.replaceState({}, document.title, "/");
  } else if (error) {
    showNotification(error.replace(/\+/g, ' '), 'error');
    window.history.replaceState({}, document.title, "/");
    showAuthScreen();
    switchAuthTab('signup');
  }
});

async function handleGoogleSetup() {
  const username = $('googleSetupName')?.value.trim();
  const password = $('googleSetupPassword')?.value;
  
  if (!username || !password) { showNotification('Please fill in all fields', 'error'); return; }
  
  try {
    const res = await fetch('/api/auth/google/complete-signup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify({ username, password })
    });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      showNotification('Account setup complete!', 'success');
      loginUser(data.user);
      if ($('googleSetupName')) $('googleSetupName').value = ''; 
      if ($('googleSetupPassword')) $('googleSetupPassword').value = '';
      
      // Restore tabs
      if ($('tabLogin')) $('tabLogin').style.display = 'block';
      if ($('tabSignup')) $('tabSignup').style.display = 'block';
      if ($('googleSetupForm')) $('googleSetupForm').style.display = 'none';
      switchAuthTab('login');
      
      hasExistingApiKeys = false;
      setTimeout(() => {
        showConfirm('API keys are required to use Hero\'s AI. Would you like to configure them now?',
          () => openApiKeys(), null, 'Configure Keys', 'Later');
      }, 500);
    } else { showNotification(data.message || 'Setup failed', 'error'); }
  } catch (err) { showNotification('Error: ' + err.message, 'error'); }
}

async function checkSession() {
  try {
    const res  = await fetch('/api/auth/check-session', { method: 'GET', credentials: 'include' });
    const data = await getJsonResponse(res);
    if (data.logged_in && data.user) {
      loginUser(data.user);
      hasExistingApiKeys = data.user.has_api_keys;
      if (!data.user.has_api_keys) {
        setTimeout(() => {
          showConfirm(
            'API keys are required to use Hero\'s AI. Would you like to configure them now?',
            () => openApiKeys(), null, 'Configure Keys', 'Later'
          );
        }, 1000);
      }
    } else {
      showAuthScreen();
    }
  } catch (err) {
    console.error('Session check failed:', err);
    showAuthScreen();
  }
}

function showAuthScreen() {
  const auth = $('authScreen');
  if (auth) auth.style.display = 'flex';
}

function hideAuthScreen() {
  const auth = $('authScreen');
  if (auth) {
    auth.style.cssText = 'opacity:0;transform:scale(0.97);transition:opacity 0.3s ease,transform 0.3s ease';
    setTimeout(() => auth.style.display = 'none', 300);
  }
}

async function handleSignup() {
  const name     = $('signupName')?.value.trim();
  const email    = $('signupEmail')?.value.trim();
  const password = $('signupPassword')?.value;
  if (!name || !email || !password) { showNotification('Please fill in all fields', 'error'); return; }
  if (password.length < 6) { showNotification('Password must be at least 6 characters', 'error'); return; }
  try {
    const res  = await fetch('/api/auth/signup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify({ name, email, password })
    });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      showNotification('Account created successfully!', 'success');
      loginUser(data.user);
      $('signupName').value = ''; $('signupEmail').value = ''; $('signupPassword').value = '';
      hasExistingApiKeys = false;
      setTimeout(() => {
        showConfirm('API keys are required to use Hero\'s AI. Would you like to configure them now?',
          () => openApiKeys(), null, 'Configure Keys', 'Later');
      }, 500);
    } else { showNotification(data.message || 'Signup failed', 'error'); }
  } catch (err) { showNotification('Error: ' + err.message, 'error'); }
}

async function handleLogin() {
  const email    = $('loginEmail')?.value.trim();
  const password = $('loginPassword')?.value;
  if (!email || !password) { showNotification('Please enter your email and password', 'error'); return; }
  try {
    const res  = await fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify({ email, password })
    });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      showNotification('Login successful!', 'success');
      loginUser(data.user);
      $('loginEmail').value = ''; $('loginPassword').value = '';
      hasExistingApiKeys = data.user.has_api_keys;
      if (!data.user.has_api_keys) {
        setTimeout(() => {
          showConfirm('API keys are required to use Hero\'s AI. Would you like to configure them now?',
            () => openApiKeys(), null, 'Configure Keys', 'Later');
        }, 500);
      }
    } else { showNotification(data.message || 'Login failed', 'error'); }
  } catch (err) { showNotification('Error: ' + err.message, 'error'); }
}

function loginUser(user) {
  const parts = user.name.trim().split(' ');
  user.initials = parts.length >= 2
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : parts[0].slice(0, 2).toUpperCase();
  currentUser = user;
  const sn = $('sidebarUserName'), se = $('sidebarUserEmail'), av = $('userAvatarInitials');
  if (sn) sn.textContent = user.name;
  if (se) se.textContent = user.email;
  if (av) av.textContent = user.initials;
  hideAuthScreen();
  _loadDisplaySettings();
  loadUserSettings();
  loadChatHistory();
  _syncMuteBtn();
}

async function handleLogout() {
  showConfirm('Are you sure you want to logout?', async () => {
    try {
      const res  = await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
      const data = await getJsonResponse(res);
      if (data.status === 'success') {
        currentUser = null; closeUserMenu();
        messages = []; attachedFiles = []; hasExistingApiKeys = false;
        currentSessionId = null;
        const md = $('messages'), ws = $('welcomeScreen'), ap = $('attachPreviewRow');
        if (md) { md.innerHTML = ''; md.style.display = 'none'; }
        if (ws) { ws.classList.remove('chat-bg'); ws.style.display = ''; }
        if (ap) ap.innerHTML = '';
        const hl = $('historyList');
        if (hl) hl.innerHTML = '<div class="history-item active"><i class="fa-regular fa-message"></i>Welcome chat</div>';
        const auth = $('authScreen');
        if (auth) {
          auth.style.cssText = 'display:flex;opacity:0;transform:scale(0.97);transition:opacity 0.3s ease,transform 0.3s ease';
          setTimeout(() => auth.style.cssText = 'display:flex;opacity:1;transform:scale(1)', 10);
        }
        const le = $('loginEmail'), lp = $('loginPassword');
        if (le) le.value = ''; if (lp) lp.value = '';
        showNotification('Logged out successfully', 'success');
      }
    } catch (err) { showNotification('Error: ' + err.message, 'error'); }
  }, null, 'Logout', 'Cancel');
}

function switchAuthTab(tab) {
  $('tabLogin')?.classList.toggle('active', tab === 'login');
  $('tabSignup')?.classList.toggle('active', tab === 'signup');
  const lf = $('loginForm'), sf = $('signupForm');
  if (lf) lf.style.display = tab === 'login'  ? 'flex' : 'none';
  if (sf) sf.style.display = tab === 'signup' ? 'flex' : 'none';
}

/* ════════ API KEYS ════════ */
async function openApiKeys() {
  closeUserMenu();
  try {
    const res  = await fetch('/api/keys/check', { method: 'GET', credentials: 'include' });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      hasExistingApiKeys = data.has_api_keys;
      const gi = $('geminiApiKey'), oi = $('openrouterApiKey'), gri = $('groqApiKey');
      if (gi)  gi.placeholder  = data.keys.gemini     ? 'Modify your Gemini API key'    : 'Enter your Gemini API key';
      if (oi)  oi.placeholder  = data.keys.openrouter ? 'Modify your OpenRouter API key' : 'Enter your OpenRouter API key';
      if (gri) gri.placeholder = data.keys.groq       ? 'Modify your Groq API key'       : 'Enter your Groq API key (optional)';
    }
  } catch (err) { console.error('Failed to check API keys:', err); }
  $('apiKeysModal')?.classList.add('active');
}

async function saveApiKeys() {
  const gemini     = $('geminiApiKey')?.value.trim()     || '';
  const openrouter = $('openrouterApiKey')?.value.trim() || '';
  const groq       = $('groqApiKey')?.value.trim()       || '';
  if (!gemini && !openrouter && !groq) {
    showNotification('Please enter at least one API key', 'error'); return;
  }
  try {
    const res  = await fetch('/api/keys/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify({ gemini, openrouter, groq })
    });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      const modal   = $('apiKeysModal');
      const saveBtn = modal?.querySelector('.modal-save-btn');
      if (saveBtn) {
        const orig = saveBtn.innerHTML;
        saveBtn.innerHTML = '<i class="fa-solid fa-check"></i> Saved Successfully!';
        saveBtn.style.background = 'linear-gradient(135deg, #0f8a55, var(--accent))';
        setTimeout(() => {
          saveBtn.innerHTML = orig; saveBtn.style.background = '';
          closeModal('apiKeysModal');
          showNotification('API keys saved successfully!', 'success');
          hasExistingApiKeys = true;
          if ($('geminiApiKey'))     $('geminiApiKey').value     = '';
          if ($('openrouterApiKey')) $('openrouterApiKey').value = '';
          if ($('groqApiKey'))       $('groqApiKey').value       = '';
        }, 1500);
      }
    } else { showNotification(data.message || 'Failed to save API keys', 'error'); }
  } catch (err) { showNotification('Error: ' + err.message, 'error'); }
}

/* ════════ PERSONALIZATION ════════ */
async function savePersonalization() {
  const saveBtn = document.querySelector('#personalizationModal .modal-save-btn');
  const payload = {
    user_name:         $('aboutName')?.value.trim()            || '',
    user_role:         $('aboutRole')?.value.trim()            || '',
    user_interests:    $('aboutInterests')?.value.trim()       || '',
    user_about_me:     $('instructionContext')?.value.trim()   || '',
    user_instruction:  $('instructionBehavior')?.value.trim()  || '',
    enable_custom_instructions: userSettings.enableCustomInstructions,
  };
  if (saveBtn) { saveBtn.disabled = true; saveBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving…'; }
  try {
    const res  = await fetch('/api/user/settings/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify(payload)
    });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      if (saveBtn) { saveBtn.innerHTML = '<i class="fa-solid fa-check"></i> Saved!'; saveBtn.style.background = 'linear-gradient(135deg, #0f8a55, #19c37d)'; }
      showNotification('Settings saved successfully!', 'success');
      setTimeout(() => {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Settings'; saveBtn.style.background = ''; }
        closeModal('personalizationModal');
      }, 1400);
    } else {
      showNotification(data.message || 'Failed to save settings', 'error');
      if (saveBtn) { saveBtn.disabled = false; saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Settings'; }
    }
  } catch (err) {
    showNotification('Error: ' + err.message, 'error');
    if (saveBtn) { saveBtn.disabled = false; saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Settings'; }
  }
}

/* ════════ MODEL SELECTION ════════ */
function onModelChange() {
  const select = $('modelSelect'); if (!select) return;
  const newModel = select.value;
  if (newModel === 'ZORVIN') {
    showConfirm('Download Hero\'s AI for ZORVIN Offline',
      () => { window.location.href = 'https://heroai.app/download'; },
      () => { select.value = currentModel; },
      'Download', 'Cancel');
  } else {
    currentModel = newModel;
    const chip = $('modelChipName');
    if (chip) chip.textContent = currentModel;
    const talkBtn = document.querySelector('.cssbuttons-io-button');
    if (talkBtn) {
      const textNode = Array.from(talkBtn.childNodes).find(n => n.nodeType === 3);
      if (textNode) textNode.textContent = 'Talk to ' + currentModel + ' ';
    }
    addSystemNote('Switched to ' + currentModel);
  }
}

/* ════════ WELCOME SCREEN ════════ */
function activateChatBg() {
  const ws = $('welcomeScreen'), md = $('messages');
  if (!ws || !md) return;
  ws.classList.add('chat-bg');
  md.style.display = 'block';
}

/* ════════ CHAT ════════ */
async function sendMessage() {
  if (isLoading) return;
  const inp = $('chatInput'); if (!inp) return;
  const text = inp.value.trim();
  if (!text && attachedFiles.length === 0) return;
  if (!currentUser) { showNotification('Please login first', 'error'); return; }

  activateChatBg();

  let taskType = activeMode;
  if (attachedFiles.length > 0) taskType = 'file_handle';
  else if (!taskType)            taskType = 'text';

  // Transient modes: Reset after use so the next message defaults to text
  if (activeMode === 'voice_message') {
    activeMode = null;
  }

  const userMsg = { role: 'user', content: text, files: [...attachedFiles], mode: taskType };
  messages.push(userMsg);
  renderMessage(userMsg);

  inp.value = ''; inp.style.height = 'auto'; attachedFiles = [];
  const ap = $('attachPreviewRow'); if (ap) ap.innerHTML = '';
  toggleSendBtn();

  const active = document.querySelector('.history-item.active');
  if (active && (active.textContent.includes('New chat') || active.textContent.includes('Welcome chat')) && text) {
    const icon = taskType === 'coding' ? 'fa-code' : taskType === 'websearch' ? 'fa-magnifying-glass' : 'fa-message';
    active.innerHTML = `<i class="fa-solid ${icon}"></i><span class="history-preview">${escHtml(text.slice(0, 40))}</span>`;
  }

  isLoading = true; toggleSendBtn();
  const typingRow = showTyping(taskType);

  try {
    let sessionHistory = [];
    if (userSettings.rememberHistory && messages.length > 2) {
      sessionHistory = messages.slice(0, -1);
    }

    // FIX: Send temporary_chat (not temporary) matching backend expectations
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        message:      text,
        model:        currentModel,
        mode:         taskType,
        session_id:   tempChatActive ? null : currentSessionId,  // FIX: Don't send session_id if temp
        temporary_chat: tempChatActive,  // FIX: Send the correct flag name
        has_files:    userMsg.files.length > 0,
        file_count:   userMsg.files.length,
        files:        userMsg.files,
      })
    });
    
    // Use the helper to avoid "Unexpected token <" if server crashes with HTML
    const data = await getJsonResponse(res);
    typingRow.remove();

    if (data.status === 'success') {
      // FIX: Don't update currentSessionId if this was a temporary chat
      if (data.session_id && !currentSessionId && !tempChatActive) {
        currentSessionId = data.session_id;
        loadChatHistory();
      }
      const aiMsg = { role: 'assistant', content: data.reply };
      messages.push(aiMsg);
      renderMessage(aiMsg);

      /* TTS: skip for coding & file_handle; skip if muted */
      const ttsBlockedModes = ['coding', 'file_handle'];
      if (userSettings.autoReadResponses && !ttsBlockedModes.includes(taskType) && !isMuted) {
        speakText(data.reply);
      }

      // FIX: Only reload chat history if it's not a temporary chat
      if (data.is_new_chat && !tempChatActive) {
        loadChatHistory();
      }
    } else {
      if (res.status === 401) {
        showNotification('Session expired. Please login again', 'error');
        handleLogout();
      } else {
        renderMessage({ role: 'assistant', content: `Error: ${data.message || 'Something went wrong'}` });
      }
    }
  } catch (err) {
    typingRow.remove();
    let userMsg = err.message;
    if (userMsg.includes('is not valid JSON') || userMsg.includes('unexpected response format')) {
      userMsg = "Hero's AI encountered a server processing error. Please try again or check your settings.";
    }
    renderMessage({ role: 'assistant', content: `Error: ${userMsg}` });
  }

  isLoading = false; toggleSendBtn();
}

/* ── Voice → Chat thread ── */
function pushVoiceToChat(userText, aiText) {
  if (!userText) return;
  activateChatBg();
  const userMsg = { role: 'user', content: userText, files: [], mode: 'voice' };
  messages.push(userMsg); renderMessage(userMsg);
  if (aiText) {
    const aiMsg = { role: 'assistant', content: aiText, mode: 'voice' };
    messages.push(aiMsg); renderMessage(aiMsg);
  }
  const active = document.querySelector('.history-item.active');
  if (active && (active.textContent.includes('Welcome chat') || active.textContent.includes('New chat'))) {
    active.innerHTML = '<i class="fa-solid fa-microphone"></i><span class="history-preview">' + escHtml(userText.slice(0, 40)) + '</span>';
  }
}

/* ════════ RENDER MESSAGE ════════ */
function renderMessage(msg) {
  const container = $('messages'); if (!container) return;
  const row = document.createElement('div');
  row.className = 'msg-row';
  if (userSettings.compactLayout) row.style.padding = '8px 0';

  const isUser     = msg.role === 'user';
  const initials   = (currentUser && isUser) ? currentUser.initials : (isUser ? 'U' : '');
  const avatarHTML = isUser
    ? initials
    : '<img src="/static/images/ai.png" width="34" height="34" style="border-radius:10px;object-fit:cover;display:block;" alt="AI">';

  let filesHTML = '';
  if (msg.files?.length > 0) {
    msg.files.forEach(f => {
      filesHTML += f.type?.startsWith('image/') && f.dataUrl
        ? `<img class="img-preview" src="${f.dataUrl}" alt="${escHtml(f.name)}"/>`
        : `<div class="file-badge"><i class="fa-regular fa-file" style="font-size:0.75rem;"></i>${escHtml(f.name)}</div>`;
    });
  }

  let modeTag = '';
  if (msg.mode) {
    let bgColor, tc, icon, label;
    if      (msg.mode === 'coding')    { bgColor='rgba(25,195,125,0.12)'; tc='var(--accent)'; icon='fa-code';            label='Coding';     }
    else if (msg.mode === 'websearch') { bgColor='rgba(245,166,35,0.12)'; tc='#f5a623';       icon='fa-magnifying-glass'; label='Web search'; }
    else if (msg.mode === 'voice')     { bgColor='rgba(99,102,241,0.12)'; tc='#818cf8';       icon='fa-microphone';       label='Voice';      }
    if (label) {
      modeTag = `<span style="display:inline-flex;align-items:center;gap:5px;font-size:0.7rem;padding:2px 8px;border-radius:6px;margin-bottom:6px;font-weight:600;background:${bgColor};color:${tc}">
        <i class="fa-solid ${icon}" style="font-size:0.65rem;"></i>${label}</span><br>`;
    }
  }

  const displayName = isUser ? (currentUser ? currentUser.name.split(' ')[0] : 'You') : "Hero's AI";

  row.innerHTML = `
    <div class="msg-avatar ${isUser ? 'user' : 'ai'}">${avatarHTML}</div>
    <div class="msg-content ${isUser ? 'user' : 'ai'}">
      <div class="sender-row">
        <span class="sender">${displayName}</span>
        <button class="copy-msg-btn" title="Copy" onclick="copyMsg(this)"><i class="fa-regular fa-copy"></i></button>
      </div>
      ${modeTag}${filesHTML}
      <div class="bubble">${formatContent(msg.content || '')}</div>
    </div>`;

  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
}

/* ════════ TYPING INDICATOR ════════ */
function showTyping(mode) {
  const container = $('messages');
  if (!container) return document.createElement('div');
  const labels = {
    coding:        'Coding',
    websearch:     'Searching',
    file_handle:   'Analyzing',
    'Voice Chat':  'Thinking',
    voice_message: 'Thinking',
  };
  const label = labels[mode] || '';
  const row = document.createElement('div');
  row.className = 'msg-row';
  row.innerHTML = `
    <div class="msg-avatar ai">
      <img src="/static/images/ai.png" width="34" height="34"
           style="border-radius:10px;object-fit:cover;display:block;" alt="AI">
    </div>
    <div class="msg-content ai">
      <div class="sender-row"><span class="sender">Hero's AI</span></div>
      <div class="typing-inline">
        ${label ? `<span class="typing-mode-label">${label}</span>` : ''}
        <div class="typing-balls">
          <div class="tb"></div><div class="tb"></div><div class="tb"></div>
        </div>
      </div>
    </div>`;
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
  return row;
}

function copyMsg(btn) {
  const bubble = btn.closest('.msg-content')?.querySelector('.bubble');
  if (!bubble) return;
  navigator.clipboard.writeText(bubble.innerText || bubble.textContent).then(() => {
    btn.innerHTML = '<i class="fa-solid fa-check"></i>';
    btn.style.color = 'var(--accent)';
    setTimeout(() => { btn.innerHTML = '<i class="fa-regular fa-copy"></i>'; btn.style.color = ''; }, 2000);
  }).catch(err => console.error('Copy failed:', err));
}

/* ════════════════════════════════════════════════════════════════
   FORMAT CONTENT
   — FIX 1: Strip web-search boilerplate prefix lines
   — FIX 2: Convert bare URLs into clickable <a> tags
   ════════════════════════════════════════════════════════════════ */

function copyCodeBlock(btn) {
  const code = btn.closest('.code-block')?.querySelector('code');
  if (!code) return;
  navigator.clipboard.writeText(code.innerText).then(() => {
    btn.innerHTML = '<i class="fa-solid fa-check"></i>';
    btn.style.color = 'var(--accent)';
    setTimeout(() => { btn.innerHTML = '<i class="fa-regular fa-copy"></i>'; btn.style.color = ''; }, 2000);
  });
}

/* ── FIX 1: Strip web-search boilerplate prefix ──────────────────
   Removes lines like:
     "Here is what I found for: ..."
     "Wikipedia:"
     "DuckDuckGo:"
     "Search results:"
   These are injected by perform_web_search() in web_search.py.
   We strip them client-side so no backend change is required,
   though the backend fix below is the cleaner solution.
─────────────────────────────────────────────────────────────────── */
function _stripWebSearchPrefix(text) {
  return text
    // "Here is what I found for: <query>" — any capitalisation
    .replace(/^here\s+is\s+what\s+i\s+found\s+for\s*:\s*.+\n?/im, '')
    // Source labels on their own line: "Wikipedia:", "DuckDuckGo:", "Search results:"
    .replace(/^(wikipedia|duckduckgo|search\s+results?)\s*:\s*\n?/gim, '')
    // Trim any leading blank lines left behind
    .replace(/^\s*\n/, '')
    .trimStart();
}

/* ── FIX 2: Convert bare URLs to clickable links ─────────────────
   Runs BEFORE HTML escaping so we work on raw text.
   Produces safe anchor tags with rel="noopener noreferrer".
   Supports http/https and www. URLs.
   Skips URLs already inside markdown []() links.
─────────────────────────────────────────────────────────────────── */
function _linkifyUrls(text) {
  const URL_RE = /(?<!\]\()(?<!\bhref=["'])((https?:\/\/|www\.)[^\s<>"')\]]+)/g;

  return text.replace(URL_RE, (match, _full, _proto) => {
    let href = match;
    if (match.startsWith('www.')) {
      href = 'https://' + match;
    }
    let display = match;
    try {
      const u = new URL(href);
      display = u.hostname + (u.pathname !== '/' ? u.pathname.slice(0, 30) + (u.pathname.length > 30 ? '…' : '') : '');
    } catch (_) { }
    return `\x00LINK:${href}||${display}\x00`;
  });
}

/* Restore link placeholders after HTML escaping */
function _restoreLinks(text) {
  return text.replace(/\x00LINK:([^\x00|]+)\|\|([^\x00]+)\x00/g, (_, href, display) => {
    let safeHref = href;
    try {
      new URL(safeHref);
    } catch (_) {
      return display;
    }
    return `<a href="${safeHref}" target="_blank" rel="noopener noreferrer" class="msg-link">${display}</a>`;
  });
}

function formatContent(raw) {
  let text = raw || '';

  // ── Step 0: strip web-search boilerplate prefix ──────────────
  text = _stripWebSearchPrefix(text);

  // ── Step 0b: linkify bare URLs before any HTML processing ────
  text = _linkifyUrls(text);

  // ── Protect code blocks (extract before escaping) ─────────────
  const codeBlocks = [];
  text = text.replace(/```(\w+)?\n?([\s\S]*?)```/g, (_, lang, code) => {
    const i = codeBlocks.length;
    const safeCode = code.trim()
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const highlightClass = userSettings.syntaxHighlighting ? `language-${lang || 'text'}` : '';
    codeBlocks.push(
      `<div class="code-block">
        <div class="code-lang-bar">
          <span class="code-lang">${lang || 'code'}</span>
          <button class="code-copy-btn" onclick="copyCodeBlock(this)" title="Copy code">
            <i class="fa-regular fa-copy"></i>
          </button>
        </div>
        <pre><code class="${highlightClass}">${safeCode}</code></pre>
      </div>`
    );
    return `%%CODEBLOCK_${i}%%`;
  });

  // ── Protect inline code ───────────────────────────────────────
  const inlineCodes = [];
  text = text.replace(/`([^`]+)`/g, (_, code) => {
    const i = inlineCodes.length;
    const safeCode = code.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    inlineCodes.push(`<code class="inline-code">${safeCode}</code>`);
    return `%%INLINE_${i}%%`;
  });

  // ── Protect tables ────────────────────────────────────────────
  const tables = [];
  text = text.replace(/^(\|.+\|[ \t]*)\n(\|[-| :]+\|[ \t]*)\n((?:\|.+\|[ \t]*\n?)*)/gm,
    (_, header, _sep, body) => {
      const i = tables.length;
      const parseRow = (row) => {
        return row.trim().replace(/^\||\|$/g, '').split('|').map(c => {
          let cell = c.trim();
          cell = cell.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
          cell = cell.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
          cell = cell.replace(/\*([^*]+?)\*/g, '<em>$1</em>');
          cell = cell.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
          return cell;
        });
      };
      const ths = parseRow(header).map(c => `<th>${c}</th>`).join('');
      const trs = body.trim().split('\n').filter(r => r.trim())
        .map(r => `<tr>${parseRow(r).map(c => `<td>${c}</td>`).join('')}</tr>`).join('');
      tables.push(
        `<div class="msg-table-wrap"><table class="msg-table">` +
        `<thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table></div>`
      );
      return `%%TABLE_${i}%%`;
    }
  );

  // ── HTML-escape everything else ───────────────────────────────
  text = text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');

  // ── Markdown: headings ────────────────────────────────────────
  text = text.replace(/^###### (.+)$/gm, '<h6 class="msg-h6">$1</h6>');
  text = text.replace(/^##### (.+)$/gm,  '<h5 class="msg-h5">$1</h5>');
  text = text.replace(/^#### (.+)$/gm,   '<h4 class="msg-h4">$1</h4>');
  text = text.replace(/^### (.+)$/gm,    '<h3 class="msg-h3">$1</h3>');
  text = text.replace(/^## (.+)$/gm,     '<h2 class="msg-h2">$1</h2>');
  text = text.replace(/^# (.+)$/gm,      '<h1 class="msg-h1">$1</h1>');

  // ── Markdown: bold / italic ───────────────────────────────────
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  text = text.replace(/\*\*(.+?)\*\*/g,     '<strong>$1</strong>');
  text = text.replace(/\*([^*\n]+?)\*/g,    '<em>$1</em>');

  // ── Markdown: lists ───────────────────────────────────────────
  text = text.replace(/^[ \t]*[-•*]\s+(.+)$/gm, '<li>$1</li>');
  text = text.replace(/((<li>(?!.*class=).*?<\/li>\n?)+)/gs, '<ul class="msg-list">$1</ul>');
  text = text.replace(/^[ \t]*\d+\.\s+(.+)$/gm, '<li class="ol-item">$1</li>');
  text = text.replace(/((<li class="ol-item">.*?<\/li>\n?)+)/gs, '<ol class="msg-list msg-ol">$1</ol>');

  // ── Horizontal rule ───────────────────────────────────────────
  text = text.replace(/^---$/gm, '<hr class="msg-hr">');

  // ── Newlines → <br> ──────────────────────────────────────────
  text = text.replace(/\n/g, '<br>');

  // ── Clean up double <br> around block elements ────────────────
  text = text.replace(/<br>\s*(<\/?(?:ul|ol|li|h[123]|hr|div|pre|table|thead|tbody|tr|th|td))/g, '$1');
  text = text.replace(/(<\/(?:ul|ol|h[123]|hr|div|pre|table|tbody|tr|th|td)>)\s*<br>/g, '$1');

  // ── Restore protected blocks ──────────────────────────────────
  codeBlocks.forEach((block, i) => { text = text.replace(`%%CODEBLOCK_${i}%%`, block); });
  inlineCodes.forEach((block, i) => { text = text.replace(`%%INLINE_${i}%%`,   block); });
  tables.forEach((block, i)      => { text = text.replace(`%%TABLE_${i}%%`,    block); });

  // ── FIX 2: Restore clickable link placeholders ────────────────
  text = _restoreLinks(text);

  return text;
}

function escHtml(str) {
  return (str || '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

/* ════════ UI CONTROLS ════════ */
function toggleTempChat() {
  tempChatActive = !tempChatActive;
  const btn = $('tempChatBtn');
  const banner = $('tempBanner');
  
  if (btn) btn.classList.toggle('active', tempChatActive);
  if (banner) banner.classList.toggle('visible', tempChatActive);
  
  // Provide user feedback
  if (tempChatActive) {
    showNotification('Temporary chat enabled — messages won\'t be saved', 'info');
  } else {
    showNotification('Temporary chat disabled — messages will be saved', 'info');
  }
}

function togglePlusMenu(e) {
  e?.stopPropagation();
  plusMenuOpen = !plusMenuOpen;
  $('plusMenu')?.classList.toggle('open', plusMenuOpen);
  $('plusBtn')?.classList.toggle('open', plusMenuOpen);
}

function closePlusMenu() {
  plusMenuOpen = false;
  $('plusMenu')?.classList.remove('open');
  $('plusBtn')?.classList.remove('open');
}

document.addEventListener('click', (e) => {
  const wrap = $('plusWrap');
  if (wrap && !wrap.contains(e.target)) closePlusMenu();
});

function triggerAttach() {
  closePlusMenu();
  if (activeMode) {
    showNotification(`Attach file is not available in ${activeMode === 'coding' ? 'Coding' : 'Web search'} mode. Remove the mode first.`, 'warning');
    return;
  }
  $('fileInput')?.click();
}

function setMode(mode) {
  closePlusMenu();
  if (attachedFiles.length > 0) {
    showNotification(`Cannot enable ${mode === 'coding' ? 'Coding' : 'Web search'} mode while a file is attached`, 'warning');
    return;
  }
  activeMode = mode;
  const badge = $('modeBadge'), badgeTxt = $('modeBadgeText');
  if (badge && badgeTxt) {
    badge.className = 'mode-badge visible ' + mode;
    badgeTxt.textContent = mode === 'coding' ? 'Coding' : 'Web search';
  }
  $('chatInput')?.focus();
}

function clearMode() {
  activeMode = null;
  const badge = $('modeBadge');
  if (badge) { badge.classList.remove('visible'); badge.className = 'mode-badge'; }
}

function switchPTab(name, btn) {
  $$('.p-tab').forEach(t => t.classList.remove('active'));
  $$('.p-panel').forEach(p => p.classList.remove('active'));
  btn?.classList.add('active');
  $('p-panel-' + name)?.classList.add('active');
}

function toggleUserMenu() {
  userMenuOpen = !userMenuOpen;
  $('userDropdown')?.classList.toggle('open', userMenuOpen);
  $('userChevron')?.classList.toggle('open', userMenuOpen);
}

function closeUserMenu() {
  userMenuOpen = false;
  $('userDropdown')?.classList.remove('open');
  $('userChevron')?.classList.remove('open');
}

async function openPersonalization() {
  closeUserMenu();
  loadUserSettings();
  $('personalizationModal')?.classList.add('active');
}

function openHelp()       { closeUserMenu(); $('helpModal')?.classList.add('active'); }
function openAboutHeros() { closeUserMenu(); $('aboutHerosModal')?.classList.add('active'); }
function closeModal(id)   { $(id)?.classList.remove('active'); }

document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(overlay.id); });
});

function toggleSidebar() { $('sidebar')?.classList.toggle('open'); }

function newChat() {
  messages = []; attachedFiles = []; clearMode();
  currentSessionId = null;
  const md = $('messages'), ws = $('welcomeScreen'), ap = $('attachPreviewRow');
  if (md) { md.innerHTML = ''; md.style.display = 'none'; }
  if (ws) { ws.classList.remove('chat-bg'); ws.style.display = ''; }
  if (ap) ap.innerHTML = '';
  const hist = $('historyList');
  if (hist) {
    hist.querySelectorAll('.history-item').forEach(i => i.classList.remove('active'));
    const el = document.createElement('div');
    el.className = 'history-item active';
    el.innerHTML = '<i class="fa-regular fa-message"></i><span class="history-preview">New chat</span>';
    hist.insertBefore(el, hist.firstChild);
  }
}

function addSystemNote(text) {
  const md = $('messages');
  if (!md || md.style.display === 'none') return;
  const note = document.createElement('div');
  note.style.cssText = 'text-align:center;color:var(--text-dim);font-size:0.72rem;padding:4px 0 8px;';
  note.textContent = `— ${text} —`;
  md.appendChild(note);
}

function fillSuggestion(text) {
  const inp = $('chatInput'); if (!inp) return;
  inp.value = text; autoResize(inp); toggleSendBtn(); inp.focus();
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const sendBtn = $('sendBtn');
    if (sendBtn && !sendBtn.disabled) sendMessage();
  }
}

function autoResize(el) {
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

function toggleSendBtn() {
  const inp = $('chatInput'), sendBtn = $('sendBtn'); if (!inp || !sendBtn) return;
  sendBtn.disabled = (!inp.value.trim() && attachedFiles.length === 0) || isLoading;
}

function handleFiles(files) {
  if (!files?.length) return;
  Array.from(files).forEach(file => {
    if (attachedFiles.length >= 5) { showNotification('Maximum 5 files allowed', 'warning'); return; }
    const item = { name: file.name, type: file.type, size: file.size, dataUrl: null };
    const reader = new FileReader();
    reader.onload = (e) => { 
      item.dataUrl = e.target.result; 
      renderChip(item); 
      // trigger toggleSendBtn after file is loaded
      toggleSendBtn();
    };
    reader.readAsDataURL(file);
    attachedFiles.push(item);
  });
  const fileInput = $('fileInput'); if (fileInput) fileInput.value = '';
}

function renderChip(item) {
  const row = $('attachPreviewRow'); if (!row) return;
  const chip = document.createElement('div');
  chip.className = 'attach-chip'; chip.dataset.name = item.name;
  const icon = item.type.startsWith('image/') ? 'fa-image' : 'fa-file';
  chip.innerHTML = `<i class="fa-regular ${icon}" style="font-size:0.75rem;flex-shrink:0;"></i>
    <span>${escHtml(item.name)}</span>
    <i class="fa-solid fa-xmark rm-chip" onclick="removeChip(this,'${escHtml(item.name)}')"></i>`;
  row.appendChild(chip);
}

function removeChip(btn, name) {
  btn.closest('.attach-chip')?.remove();
  attachedFiles = attachedFiles.filter(f => f.name !== name);
  toggleSendBtn();
}

function toggleInlineMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { showNotification('Speech recognition not supported. Try Chrome', 'error'); return; }
  if (inlineMicOn) {
    inlineRecog?.stop(); inlineMicOn = false;
    $('micBtn')?.classList.remove('listening'); return;
  }
  inlineRecog = new SR();
  inlineRecog.lang = 'en-US'; inlineRecog.continuous = false; inlineRecog.interimResults = true;
  inlineRecog.onresult = (e) => {
    const transcript = Array.from(e.results).map(r => r[0].transcript).join('');
    const inp = $('chatInput');
    if (inp) { 
      inp.value = transcript; 
      autoResize(inp); 
      toggleSendBtn(); 
      if (!activeMode) activeMode = 'voice_message'; 
    }
  };
  inlineRecog.onend = () => { inlineMicOn = false; $('micBtn')?.classList.remove('listening'); };
  inlineRecog.start();
  inlineMicOn = true; $('micBtn')?.classList.add('listening');
}

/* ══════════════════════════════════════════════════════
   TTS HELPERS
   ══════════════════════════════════════════════════════ */
function _sanitiseForTTS(raw) {
  let t = raw || '';
  t = t.replace(/<[^>]+>/g, '');
  t = t.replace(/```[\s\S]*?```/g, 'code block.');
  t = t.replace(/`([^`]+)`/g, '$1');
  t = t.replace(/https?:\/\/[^\s)>\]"']+/gi, '');
  t = t.replace(/www\.[^\s)>\]"']+/gi, '');
  t = t.replace(/\*\*(.*?)\*\*/g, '$1');
  t = t.replace(/\*(.*?)\*/g, '$1');
  t = t.replace(/#+\s/g, '');
  t = t.replace(
    /[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F700}-\u{1F77F}\u{1F780}-\u{1F7FF}\u{1F800}-\u{1F8FF}\u{1F900}-\u{1F9FF}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F1E0}-\u{1F1FF}\u{200D}\u{20E3}]/gu,
    ''
  );
  t = t.replace(/\s+/g, ' ').trim();
  return t;
}

function speakText(raw) {
  if (!window.speechSynthesis || isMuted) return;
  window.speechSynthesis.cancel();
  const clean = _sanitiseForTTS(raw).slice(0, 500);
  if (!clean) return;
  const utterance = new SpeechSynthesisUtterance(clean);
  utterance.rate = 1.1; utterance.pitch = 1; utterance.volume = 1.0;
  const voices    = window.speechSynthesis.getVoices();
  const preferred = voices.find(v => v.lang.startsWith('en') && v.name.toLowerCase().includes('google'));
  if (preferred) utterance.voice = preferred;
  window.speechSynthesis.speak(utterance);
}

/* ════════ VOICE MODAL STATE ════════ */
function _setVoiceState(state) {
  voiceState = state;
  const statusEl = $('voiceStatus'), speakBtn = $('speakBtn'), pauseBtn = $('pauseVoiceBtn');
  switch (state) {
    case VOICE_STATE.IDLE:
      if (statusEl) statusEl.textContent = '';
      if (speakBtn) { speakBtn.innerHTML = '<i class="fa-solid fa-microphone"></i> Speak'; speakBtn.style.background = ''; speakBtn.style.color = ''; }
      if (pauseBtn) pauseBtn.disabled = true;
      isListening = false; break;
    case VOICE_STATE.LISTENING:
      if (statusEl) statusEl.innerHTML = '<span style="display:inline-flex;align-items:center;gap:6px;"><span style="width:8px;height:8px;border-radius:50%;background:#e74c3c;animation:pulse-dot 1s infinite;display:inline-block;"></span>Listening…</span>';
      if (speakBtn) { speakBtn.innerHTML = '<i class="fa-solid fa-stop"></i> Stop'; speakBtn.style.background = '#e74c3c'; speakBtn.style.color = '#fff'; }
      if (pauseBtn) pauseBtn.disabled = true;
      isListening = true; break;
    case VOICE_STATE.THINKING:
      if (statusEl) statusEl.innerHTML = '<span style="display:inline-flex;align-items:center;gap:6px;"><span class="typing-dots" style="display:inline-flex;gap:3px;"><span style="width:5px;height:5px;border-radius:50%;background:var(--accent);animation:bounce-dot 0.8s infinite 0s;display:inline-block;"></span><span style="width:5px;height:5px;border-radius:50%;background:var(--accent);animation:bounce-dot 0.8s infinite 0.15s;display:inline-block;"></span><span style="width:5px;height:5px;border-radius:50%;background:var(--accent);animation:bounce-dot 0.8s infinite 0.3s;display:inline-block;"></span></span> Thinking…</span>';
      if (pauseBtn) pauseBtn.disabled = true;
      isListening = false; break;
    case VOICE_STATE.SPEAKING:
      if (statusEl) statusEl.innerHTML = '<span style="display:inline-flex;align-items:center;gap:6px;"><i class="fa-solid fa-volume-high" style="color:var(--accent);animation:pulse-dot 0.8s infinite;"></i> Speaking…</span>';
      if (pauseBtn) pauseBtn.disabled = false;
      isListening = true; break;
  }
}

function setModeCodingAndPrompt() {
  closePlusMenu();
  if (attachedFiles.length > 0) {
    showNotification('Cannot enable Coding mode while a file is attached', 'warning');
    return;
  }
  activeMode = 'coding';
  const badge = $('modeBadge'), badgeTxt = $('modeBadgeText');
  if (badge && badgeTxt) {
    badge.className = 'mode-badge visible coding';
    badgeTxt.textContent = 'Coding';
  }
  const inp = $('chatInput');
  if (inp) {
    inp.value = 'Generate code: ';
    autoResize(inp); toggleSendBtn(); inp.focus();
    setTimeout(() => { inp.selectionStart = inp.selectionEnd = inp.value.length; }, 0);
  }
}

function _showTranscript(userText, aiText) {
  const el = $('voiceTranscript'); if (!el) return;
  if (!userText && !aiText) { el.textContent = 'Speak now…'; return; }
  let html = '';
  if (userText) html += `<div style="margin-bottom:0.65rem;padding:0.6rem 0.85rem;background:rgba(255,255,255,0.05);border-radius:8px;">
    <div style="font-size:0.72rem;color:var(--accent);font-weight:600;margin-bottom:3px;">YOU</div>
    <div style="font-size:0.9rem;">${escHtml(userText)}</div></div>`;
  if (aiText)   html += `<div style="padding:0.6rem 0.85rem;background:rgba(25,195,125,0.07);border-radius:8px;">
    <div style="font-size:0.72rem;color:var(--accent);font-weight:600;margin-bottom:3px;">HERO AI</div>
    <div style="font-size:0.9rem;">${formatContent(aiText)}</div></div>`;
  el.innerHTML = html;
  requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
}

function _showInterim(text) {
  const el = $('voiceTranscript'); if (!el || !text) return;
  el.innerHTML = `<div style="padding:0.6rem 0.85rem;border-radius:8px;border:0.5px dashed rgba(25,195,125,0.3);">
    <div style="font-size:0.72rem;color:var(--accent);font-weight:600;margin-bottom:3px;">YOU</div>
    <div style="font-size:0.9rem;color:var(--text-dim);">${escHtml(text)}</div></div>`;
  el.scrollTop = el.scrollHeight;
}

function openVoiceModal()  { $('voiceOverlay')?.classList.add('active'); initBallCanvas(); }
function closeVoiceModal() { stopVoiceSession(); $('voiceOverlay')?.classList.remove('active'); }
function toggleVoiceSession() { voiceActive ? stopVoiceSession() : startVoiceSession(); }
function pauseVoiceReply() {
  if (!voiceActive || voiceState !== VOICE_STATE.SPEAKING) return;
  window.speechSynthesis?.cancel();
  _setVoiceState(VOICE_STATE.LISTENING);
  const el = $('voiceTranscript'); if (el) el.textContent = 'Speak now...';
  _startRecognition();
}

async function startVoiceSession() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { showNotification('Speech recognition not supported. Please use Chrome', 'error'); return; }
  try { mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (err) { showNotification('Microphone permission denied', 'error'); return; }
  audioCtx  = new (window.AudioContext || window.webkitAudioContext)();
  analyser  = audioCtx.createAnalyser();
  analyser.fftSize = 512; analyser.smoothingTimeConstant = 0.8;
  audioCtx.createMediaStreamSource(mediaStream).connect(analyser);
  voiceActive = true; voiceFinalText = ''; voiceInterimText = '';
  _startRecognition();
  _setVoiceState(VOICE_STATE.LISTENING);
  _showTranscript('', '');
  const el = $('voiceTranscript'); if (el) el.textContent = 'Speak now…';
}

function _startRecognition() {
  if (!voiceActive) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  voiceRecog = new SR();
  voiceRecog.lang = 'en-US'; voiceRecog.continuous = true; voiceRecog.interimResults = true;

  voiceRecog.onresult = (event) => {
    if (voiceState !== VOICE_STATE.LISTENING) return;
    let interim = '', final = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const t = event.results[i][0].transcript;
      event.results[i].isFinal ? (final += t + ' ') : (interim += t);
    }
    if (final.trim()) voiceFinalText += final;
    voiceInterimText = interim;
    _showInterim((voiceFinalText + voiceInterimText).trim());
    clearTimeout(silenceTimer);
    if ((voiceFinalText + voiceInterimText).trim()) {
      silenceTimer = setTimeout(() => {
        const text = (voiceFinalText + voiceInterimText).trim();
        if (text && voiceState === VOICE_STATE.LISTENING && voiceActive) {
          try { voiceRecog.stop(); } catch (_) {}
          _setVoiceState(VOICE_STATE.THINKING);
          _sendToAI(text);
        }
      }, SILENCE_DELAY_MS);
    }
  };

  voiceRecog.onspeechend = () => {};
  voiceRecog.onend = () => {
    if (voiceActive && voiceState === VOICE_STATE.LISTENING) {
      setTimeout(() => {
        if (voiceActive && voiceState === VOICE_STATE.LISTENING) _startRecognition();
      }, 150);
    }
  };
  voiceRecog.onerror = (e) => {
    if (e.error === 'aborted' || e.error === 'no-speech') return;
    console.warn('Speech recognition error:', e.error);
  };
  try { voiceRecog.start(); } catch (_) {}
}

async function _sendToAI(userText) {
  if (!voiceActive || !userText) return;
  if (!currentUser) {
    const el = $('voiceStatus'); if (el) el.textContent = 'Please login first.';
    _setVoiceState(VOICE_STATE.LISTENING); _startRecognition(); return;
  }
  if (voiceState !== VOICE_STATE.THINKING) _setVoiceState(VOICE_STATE.THINKING);
  _showTranscript(userText, '');
  voiceFinalText = ''; voiceInterimText = '';
  try {
    const res  = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify({ message: userText, model: currentModel, mode: 'Voice Chat', session_id: currentSessionId })
    });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      if (data.session_id && !currentSessionId) { currentSessionId = data.session_id; loadChatHistory(); }
      const reply = (data.reply || '').trim();
      _showTranscript(userText, reply);
      _setVoiceState(VOICE_STATE.SPEAKING);
      pushVoiceToChat(userText, reply);
      _speakReply(reply, () => {
        if (voiceActive && voiceState === VOICE_STATE.SPEAKING) {
          _setVoiceState(VOICE_STATE.LISTENING);
          const el = $('voiceTranscript'); if (el) el.textContent = 'Speak now…';
          _startRecognition();
        }
      });
    } else {
      const el = $('voiceStatus'); if (el) el.textContent = 'Error: ' + (data.message || 'AI failed');
      if (voiceActive) { _setVoiceState(VOICE_STATE.LISTENING); _startRecognition(); }
    }
  } catch (err) {
    console.error('Voice AI error:', err);
    const el = $('voiceStatus'); if (el) el.textContent = 'Network error. Listening again…';
    if (voiceActive) { _setVoiceState(VOICE_STATE.LISTENING); _startRecognition(); }
  }
}

function _speakReply(raw, onDone) {
  if (!window.speechSynthesis) { onDone?.(); return; }
  window.speechSynthesis.cancel();
  const clean = _sanitiseForTTS(raw).slice(0, 800);
  if (!clean) { onDone?.(); return; }
  const utter = new SpeechSynthesisUtterance(clean);
  utter.rate = 1.1; utter.pitch = 1.0; utter.volume = 1.0;
  const voices    = window.speechSynthesis.getVoices();
  const preferred = voices.find(v => v.lang.startsWith('en') && v.name.toLowerCase().includes('google'))
    || voices.find(v => v.lang.startsWith('en'));
  if (preferred) utter.voice = preferred;
  utter.onend = () => onDone?.(); utter.onerror = () => onDone?.();
  window.speechSynthesis.speak(utter);
}

function stopVoiceSession() {
  clearTimeout(silenceTimer); silenceTimer = null;
  voiceActive = false;
  try { voiceRecog?.stop(); } catch (_) {}
  mediaStream?.getTracks().forEach(t => t.stop());
  audioCtx?.close();
  window.speechSynthesis?.cancel();
  cancelAnimationFrame(animFrame);
  voiceFinalText = ''; voiceInterimText = '';
  _setVoiceState(VOICE_STATE.IDLE);
  const el = $('voiceTranscript'); if (el) el.textContent = 'Your speech will appear here…';
  animateBall(false);
}

/* ════════ CHAT HISTORY ════════ */
async function loadChatHistory() {
  if (!currentUser) return;
  const historyList = $('historyList');
  if (historyList) {
    historyList.innerHTML = '<div style="padding:10px 16px;color:var(--text-dim);font-size:0.78rem;display:flex;align-items:center;gap:8px;"><i class="fa-solid fa-circle-notch fa-spin" style="font-size:0.7rem;"></i> Loading…</div>';
  }
  try {
    const res  = await fetch('/api/chat/history', { method: 'GET', credentials: 'include' });
    const data = await getJsonResponse(res);
    if (data.status === 'success') renderChatHistory(data.chats || []);
  } catch (err) {
    console.error('Failed to load chat history:', err);
    if (historyList) historyList.innerHTML = '<div class="history-item active"><i class="fa-regular fa-message"></i><span class="history-preview">Welcome chat</span></div>';
  }
}

function renderChatHistory(chats) {
  const historyList = $('historyList');
  if (!historyList) return;
  const frag = document.createDocumentFragment();
  if (chats.length === 0) {
    const el = document.createElement('div');
    el.className = 'history-item active';
    el.innerHTML = '<i class="fa-regular fa-message"></i><span class="history-preview">Welcome chat</span>';
    frag.appendChild(el);
    historyList.innerHTML = ''; historyList.appendChild(frag); return;
  }
  const grouped   = {};
  const today     = new Date(); today.setHours(0,0,0,0);
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
  chats.forEach(chat => {
    const chatDate = new Date(chat.date); chatDate.setHours(0,0,0,0);
    let dateKey;
    if      (chatDate.getTime() === today.getTime())     dateKey = 'Today';
    else if (chatDate.getTime() === yesterday.getTime()) dateKey = 'Yesterday';
    else    dateKey = chatDate.toLocaleDateString('en-US', { month:'short', day:'numeric', year:'numeric' });
    if (!grouped[dateKey]) grouped[dateKey] = [];
    grouped[dateKey].push(chat);
  });
  const dateOrder = ['Today', 'Yesterday'];
  Object.keys(grouped).forEach(k => { if (!dateOrder.includes(k)) dateOrder.push(k); });
  dateOrder.forEach(dateKey => {
    if (!grouped[dateKey]) return;
    const header = document.createElement('div');
    header.className = 'history-date-header';
    header.textContent = dateKey;
    frag.appendChild(header);
    grouped[dateKey].forEach((chat, index) => {
      const item = document.createElement('div');
      item.className = 'history-item' + (index === 0 && dateKey === 'Today' ? ' active' : '');
      item.dataset.chatId    = chat.chat_id;
      item.dataset.sessionId = chat.session_id;
      let icon = 'fa-message';
      if      (chat.task_type === 'coding')                                   icon = 'fa-code';
      else if (chat.task_type === 'websearch')                                icon = 'fa-magnifying-glass';
      else if (chat.task_type === 'voice' || chat.task_type === 'Voice Chat') icon = 'fa-microphone';
      item.innerHTML = `
        <i class="fa-solid ${icon}"></i>
        <span class="history-preview">${escHtml(chat.preview)}</span>
        <button class="history-delete-btn" onclick="deleteChatHistory(event,'${chat.chat_id}')">
          <i class="fa-solid fa-trash"></i>
        </button>`;
      item.onclick = (e) => {
        if (e.target.closest('.history-delete-btn')) return;
        loadChatMessages(chat.session_id);
      };
      frag.appendChild(item);
    });
  });
  historyList.innerHTML = ''; historyList.appendChild(frag);
}

async function loadChatMessages(sessionId) {
  if (!currentUser || !sessionId) return;
  try {
    const res  = await fetch(`/api/chat/history/${sessionId}`, { method: 'GET', credentials: 'include' });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      messages = [];
      const md = $('messages');
      if (md) md.innerHTML = '';
      activateChatBg();
      $$('.history-item').forEach(item => item.classList.remove('active'));
      const activeItem = document.querySelector(`[data-session-id="${sessionId}"]`);
      if (activeItem) activeItem.classList.add('active');
      currentSessionId = sessionId;
      (data.messages || []).forEach(msg => { messages.push(msg); renderMessage(msg); });
    }
  } catch (err) {
    console.error('Failed to load chat messages:', err);
    showNotification('Failed to load chat', 'error');
  }
}

async function deleteChatHistory(event, chatId) {
  event.stopPropagation();
  showConfirm('Delete this chat?', async () => {
    try {
      const res  = await fetch(`/api/chat/history/${chatId}/delete`, { method: 'POST', credentials: 'include' });
      const data = await getJsonResponse(res);
      if (data.status === 'success') { showNotification('Chat deleted', 'success'); loadChatHistory(); }
      else { showNotification(data.message || 'Failed to delete chat', 'error'); }
    } catch (err) { showNotification('Error: ' + err.message, 'error'); }
  }, null, 'Delete', 'Cancel');
}

/* ════════ BALL CANVAS ════════ */
function initBallCanvas() {
  ballPhase = 0; isListening = false;
  drawBall._sv = 0; drawBall._bars = new Array(120).fill(0);
  drawBall._tBars = new Array(120).fill(0); drawBall._innerR = 0;
  drawBall._waves = []; drawBall._lastSv = 0;
  animateBall(false);
}

function animateBall(listening) { isListening = listening; cancelAnimationFrame(animFrame); drawBall(); }

function drawBall() {
  const canvas = $('voiceCanvas'); if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height, cx = W/2, cy = H/2;
  ctx.clearRect(0,0,W,H); ballPhase += 0.018;
  let volume = 0;
  if (analyser && isListening) {
    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(data);
    volume = data.reduce((a,b) => a+b, 0) / data.length / 128;
  }
  drawBall._sv = drawBall._sv || 0;
  drawBall._sv += (volume - drawBall._sv) * 0.12;
  const sv = drawBall._sv;
  const BAR_COUNT = 120, OUTER_R = Math.min(W,H)*0.40, MAX_BAR_H = Math.min(W,H)*0.165;
  const targetOuterR = isListening
    ? OUTER_R + sv*5 + Math.sin(ballPhase*2.0)*(1.5+sv*3)
    : OUTER_R + Math.sin(ballPhase*0.75)*2.5;
  drawBall._innerR = drawBall._innerR || OUTER_R;
  drawBall._innerR += (targetOuterR - drawBall._innerR) * 0.10;
  const outerR = drawBall._innerR;
  drawBall._bars  = drawBall._bars  || new Array(BAR_COUNT).fill(0);
  drawBall._tBars = drawBall._tBars || new Array(BAR_COUNT).fill(0);
  if (isListening && analyser) {
    const fftData = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(fftData);
    const binPerBar = Math.floor(fftData.length / BAR_COUNT);
    for (let i = 0; i < BAR_COUNT; i++) {
      let sum = 0;
      for (let b = 0; b < binPerBar; b++) sum += fftData[i*binPerBar+b];
      drawBall._tBars[i] = (sum/binPerBar)/255;
    }
  } else if (isListening) {
    for (let i = 0; i < BAR_COUNT; i++) {
      const t = i/BAR_COUNT;
      drawBall._tBars[i] = Math.max(0,
        Math.sin(t*Math.PI*4+ballPhase*2.1)*sv*0.50+
        Math.sin(t*Math.PI*8+ballPhase*3.4)*sv*0.30+
        Math.sin(i*0.4+ballPhase*2.8)*sv*0.35);
    }
  } else {
    for (let i = 0; i < BAR_COUNT; i++)
      drawBall._tBars[i] = Math.max(0,
        Math.sin(i*0.18+ballPhase*0.9)*0.038+Math.sin(i*0.35+ballPhase*0.5)*0.022);
  }
  const lerpSpeed = isListening ? 0.22 : 0.07;
  for (let i = 0; i < BAR_COUNT; i++)
    drawBall._bars[i] += (drawBall._tBars[i] - drawBall._bars[i]) * lerpSpeed;
  const glowA = 0.07+sv*0.11;
  const halo = ctx.createRadialGradient(cx,cy,outerR*0.55,cx,cy,outerR*1.40);
  halo.addColorStop(0,`rgba(25,195,125,${glowA})`);
  halo.addColorStop(0.45,`rgba(15,155,90,${glowA*0.40})`);
  halo.addColorStop(1,'rgba(0,0,0,0)');
  ctx.beginPath(); ctx.arc(cx,cy,outerR*1.40,0,Math.PI*2); ctx.fillStyle=halo; ctx.fill();
  ctx.beginPath(); ctx.arc(cx,cy,outerR,0,Math.PI*2);
  ctx.strokeStyle=`rgba(25,195,125,${0.20+sv*0.28})`; ctx.lineWidth=5; ctx.stroke();
  ctx.beginPath(); ctx.arc(cx,cy,outerR,0,Math.PI*2);
  ctx.strokeStyle=`rgba(50,235,155,${0.55+sv*0.38})`; ctx.lineWidth=1.5; ctx.stroke();
  const df = ctx.createRadialGradient(cx-outerR*0.22,cy-outerR*0.22,0,cx,cy,outerR);
  df.addColorStop(0,'hsl(210,45%,10%)'); df.addColorStop(0.58,'hsl(215,55%,5%)'); df.addColorStop(1,'hsl(220,70%,2%)');
  ctx.beginPath(); ctx.arc(cx,cy,outerR-1,0,Math.PI*2); ctx.fillStyle=df; ctx.fill();
  for (let i = 0; i < BAR_COUNT; i++) {
    const angle = (i/BAR_COUNT)*Math.PI*2-Math.PI/2;
    const barH  = drawBall._bars[i]*MAX_BAR_H;
    const r1=outerR-1, r2=outerR-barH-1.5;
    const x1=cx+Math.cos(angle)*r1, y1=cy+Math.sin(angle)*r1;
    const x2=cx+Math.cos(angle)*r2, y2=cy+Math.sin(angle)*r2;
    const intensity = Math.min(1,drawBall._bars[i]*2.4);
    const hue=155+intensity*28, lit=44+intensity*36, alpha=0.30+intensity*0.70;
    ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2);
    ctx.strokeStyle=`hsla(${hue},100%,${lit}%,${alpha*0.28})`; ctx.lineWidth=4.5; ctx.lineCap='round'; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2);
    ctx.strokeStyle=`hsla(${hue},100%,${lit+14}%,${alpha})`; ctx.lineWidth=1.6; ctx.stroke();
    if (intensity > 0.5) {
      ctx.beginPath(); ctx.arc(x2,y2,1.8,0,Math.PI*2);
      ctx.fillStyle=`rgba(180,255,220,${(intensity-0.5)*2*alpha})`; ctx.fill();
    }
  }
  const innerZoneR = outerR-MAX_BAR_H-10;
  const coreA = isListening ? 0.18+sv*0.35 : 0.08;
  const core = ctx.createRadialGradient(cx,cy,0,cx,cy,innerZoneR*0.90);
  core.addColorStop(0,`rgba(80,220,155,${coreA})`); core.addColorStop(0.5,`rgba(30,160,100,${coreA*0.45})`); core.addColorStop(1,'rgba(0,0,0,0)');
  ctx.save(); ctx.beginPath(); ctx.arc(cx,cy,innerZoneR,0,Math.PI*2); ctx.clip();
  ctx.beginPath(); ctx.arc(cx,cy,innerZoneR*0.90,0,Math.PI*2); ctx.fillStyle=core; ctx.fill(); ctx.restore();
  const sX=cx-outerR*0.26, sY=cy-outerR*0.28;
  const spec = ctx.createRadialGradient(sX,sY,0,sX,sY,outerR*0.38);
  spec.addColorStop(0,'rgba(255,255,255,0.55)'); spec.addColorStop(0.28,'rgba(200,255,225,0.18)'); spec.addColorStop(1,'rgba(255,255,255,0)');
  ctx.save(); ctx.beginPath(); ctx.arc(cx,cy,outerR-1,0,Math.PI*2); ctx.clip();
  ctx.beginPath(); ctx.arc(sX,sY,outerR*0.38,0,Math.PI*2); ctx.fillStyle=spec; ctx.fill(); ctx.restore();
  drawBall._waves = drawBall._waves || []; drawBall._lastSv = drawBall._lastSv || 0;
  if (isListening && sv-drawBall._lastSv > 0.15 && sv > 0.30) drawBall._waves.push({ r:outerR*1.04, life:1.0 });
  drawBall._lastSv = sv;
  for (let w = drawBall._waves.length-1; w >= 0; w--) {
    const wv = drawBall._waves[w]; wv.r += 2.5; wv.life -= 0.030;
    if (wv.life <= 0) { drawBall._waves.splice(w,1); continue; }
    ctx.beginPath(); ctx.arc(cx,cy,wv.r,0,Math.PI*2);
    ctx.strokeStyle=`rgba(25,210,130,${wv.life*0.25})`; ctx.lineWidth=wv.life*5; ctx.stroke();
    ctx.beginPath(); ctx.arc(cx,cy,wv.r,0,Math.PI*2);
    ctx.strokeStyle=`rgba(60,240,160,${wv.life*0.55})`; ctx.lineWidth=wv.life*1.2; ctx.stroke();
  }
  animFrame = requestAnimationFrame(drawBall);
}

/* ════════ INIT ════════ */
if (window.speechSynthesis) window.speechSynthesis.getVoices();
setTimeout(() => { initBallCanvas(); _syncMuteBtn(); }, 100);
document.addEventListener('DOMContentLoaded', checkSession);
console.log('✅ Hero AI loaded.');
