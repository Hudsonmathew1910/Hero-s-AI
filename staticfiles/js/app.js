/* ════════════════════════════════════════════════════════════════
   Heros — app.js
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

// --- CSRF Fetch Wrapper ---
(function() {
    const originalFetch = window.fetch;
    window.fetch = async function() {
        let [resource, config] = arguments;
        if (!config) config = {};
        const method = (config.method || 'GET').toUpperCase();
        if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
            const csrfMeta = document.querySelector('meta[name="csrf-token"]');
            if (csrfMeta) {
                if (!config.headers) config.headers = {};
                if (config.headers instanceof Headers) {
                    if (!config.headers.has('X-CSRFToken')) config.headers.append('X-CSRFToken', csrfMeta.content);
                } else {
                    if (!config.headers['X-CSRFToken']) config.headers['X-CSRFToken'] = csrfMeta.content;
                }
            }
        }
        return originalFetch(resource, config);
    };
})();
// --------------------------

let messages = [];
let attachedFiles = [];
let isLoading = false;
let currentModel = 'Halo';
let inlineMicOn = false;
let inlineRecog = null;
let userMenuOpen = false;
let currentUser = null;
let plusMenuOpen = false;
let activeMode = null;
let isSearchMode = true;
let isCodeMode = false;
let tempChatActive = false;
let currentSessionId = null;

/* Mute state — default MUTED */
let isMuted = true;

/* ════════ CSRF TOKEN ════════ */
function getCsrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
}

/* User Settings State */
let userSettings = {
  autoReadResponses: false,
  compactLayout: false,
  rememberHistory: false,
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
let ignoreVoiceUntil = 0;
let currentAITextClean = '';

/* 1-second silence timer before sending to AI (fast response) */
let silenceTimer = null;
const SILENCE_DELAY_MS = 1000;

/* API Keys State */
let hasExistingApiKeys = false;
let hasGroqKey = false;

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
  userSettings.autoReadResponses        = JSON.parse(localStorage.getItem('hero-auto-read')        ?? 'false');
  userSettings.compactLayout            = JSON.parse(localStorage.getItem('hero-compact-layout')   ?? 'false');
  userSettings.rememberHistory          = JSON.parse(localStorage.getItem('hero-remember-history') ?? 'false');
  userSettings.syntaxHighlighting       = JSON.parse(localStorage.getItem('hero-syntax-highlight') ?? 'true');
  userSettings.enableCustomInstructions = JSON.parse(localStorage.getItem('hero-custom-inst')      ?? 'true');
  userSettings.developerOption          = JSON.parse(localStorage.getItem('hero-developer-option') ?? 'false');
  
  isMuted = !userSettings.autoReadResponses;
  _syncMuteBtn();
  _syncSettingsUI();
}

function _syncSettingsUI() {
  const map = {
    'autoReadResponses':       'autoReadResponses',
    'compactLayout':           'compactLayout',
    'rememberHistory':         'rememberHistory',
    'syntaxHighlighting':      'syntaxHighlighting',
    'enableCustomInstructions':'enableCustomInstructions',
    'developerOption':         'developerOption',
  };
  Object.entries(map).forEach(([attr, key]) => {
    const btn = document.querySelector(`[data-setting="${attr}"]`);
    if (btn) btn.classList.toggle('on', !!userSettings[key]);
  });
  document.body.classList.toggle('compact-mode', userSettings.compactLayout);
  
  // Handle Developer Option in model selects
  const devSelects = [document.getElementById('modelSelect'), document.getElementById('devModelSelect'), document.getElementById('sideDevModelSelect')];
  devSelects.forEach(select => {
    if (!select) return;
    let opt = select.querySelector('option[value="Developer"]');
    if (userSettings.developerOption && currentUser) {
      if (!opt) {
        opt = document.createElement('option');
        opt.value = 'Developer';
        opt.textContent = 'Developer Mode';
        select.appendChild(opt);
      }
    } else {
      if (opt) {
        if (select.value === 'Developer') {
          select.value = select.options[0].value;
          if (select.onchange) select.onchange();
        }
        opt.remove();
      }
    }
  });
}

function toggleSetting(settingName) {
  userSettings[settingName] = !userSettings[settingName];
  if (settingName === 'autoReadResponses') {
    isMuted = !userSettings.autoReadResponses;
    _syncMuteBtn();
    if (isMuted) window.speechSynthesis?.cancel();
  }
  if (settingName === 'compactLayout') {
    document.body.classList.toggle('compact-mode', userSettings.compactLayout);
  }
  if (settingName === 'syntaxHighlighting') {
    if (userSettings.syntaxHighlighting && window.hljs) {
      document.querySelectorAll('#messages pre code').forEach((block) => {
        try { hljs.highlightElement(block); } catch(e) {}
      });
    } else {
      loadChatHistory();
    }
  }
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
    'developerOption':         'Developer option',
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
  // Keeping this function for backwards compatibility with the Settings menu buttons
  const db = $('theme-dark-btn'), lb = $('theme-light-btn');
  if (theme === 'light') { lb?.classList.add('active'); db?.classList.remove('active'); }
  else                   { db?.classList.add('active'); lb?.classList.remove('active'); }
}

function toggleThemeSimple() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const newTheme = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', newTheme);
  localStorage.setItem('hero-theme', newTheme);
  _syncThemeSwitch(newTheme);
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
  userSettings.autoReadResponses = !isMuted;
  localStorage.setItem('hero-auto-read', JSON.stringify(userSettings.autoReadResponses));
  _syncMuteBtn();
  _syncSettingsUI();
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
      method: 'POST', 
      headers: { 
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      }, 
      credentials: 'include',
      body: JSON.stringify({ username, password })
    });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      showNotification('Account setup complete!', 'success');
      loginUser(data.user);
      if (data.redirect_url && data.redirect_url !== '/') {
        window.location.href = data.redirect_url;
        return;
      }
      if ($('googleSetupName')) $('googleSetupName').value = ''; 
      if ($('googleSetupPassword')) $('googleSetupPassword').value = '';
      
      // Restore tabs
      if ($('tabLogin')) $('tabLogin').style.display = 'block';
      if ($('tabSignup')) $('tabSignup').style.display = 'block';
      if ($('googleSetupForm')) $('googleSetupForm').style.display = 'none';
      switchAuthTab('login');
      
      hasExistingApiKeys = false;
      hasGroqKey = false;
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
      hasGroqKey = data.user.has_groq_key;
      updateFastModeDefault();
      
      if (!data.user.has_api_keys) {
        setTimeout(() => {
          showConfirm(
            'API keys are required to use Hero\'s AI. Would you like to configure them now?',
            () => openSettings('apikeys'), null, 'Configure Keys', 'Later'
          );
        }, 3000);
      }
    } else {
      handleLoggedOutState();
    }
  } catch (err) {
    console.error('Session check failed:', err);
    handleLoggedOutState();
  }
  const searchBtn = $('searchToggleBtn');
  if (searchBtn) {
    searchBtn.classList.toggle('active', isSearchMode);
  }
  onModelChange(); // Init UI based on default model
}

function handleLoggedOutState() {
  const rowIn = $('userInfoRowLoggedIn'); if (rowIn) rowIn.style.display = 'none';
  const rowOut = $('userInfoRowLoggedOut'); if (rowOut) rowOut.style.display = 'flex';
  
  const modelSelect = $('modelSelect');
  if (modelSelect) {
      Array.from(modelSelect.options).forEach(opt => {
          if (opt.value !== 'Halo' && opt.value !== 'Baymax') opt.disabled = true;
      });
      if (modelSelect.value !== 'Halo' && modelSelect.value !== 'Baymax') {
          modelSelect.value = 'Halo';
          onModelChange();
      }
  }
}

function showAuthScreen() {
  const auth = $('authScreen');
  if (auth) {
    auth.style.cssText = 'display:flex;opacity:1;transform:scale(1);';
  }
}

function hideAuthScreen() {
  const auth = $('authScreen');
  if (auth) {
    auth.style.cssText = 'display:none;';
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
      method: 'POST', 
      headers: { 
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      }, 
      credentials: 'include',
      body: JSON.stringify({ name, email, password })
    });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      showNotification('Account created successfully!', 'success');
      loginUser(data.user);
      $('signupName').value = ''; $('signupEmail').value = ''; $('signupPassword').value = '';
      hasExistingApiKeys = false;
      hasGroqKey = false;
      updateFastModeDefault();
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
      method: 'POST', 
      headers: { 
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      }, 
      credentials: 'include',
      body: JSON.stringify({ email, password })
    });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      showNotification('Login successful!', 'success');
      loginUser(data.user);
      $('loginEmail').value = ''; $('loginPassword').value = '';
      hasExistingApiKeys = data.user.has_api_keys;
      hasGroqKey = data.user.has_groq_key;
      updateFastModeDefault();
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
  hasExistingApiKeys = !!user.has_api_keys;
  hasGroqKey = !!user.has_groq_key;

  const rowIn = $('userInfoRowLoggedIn'); if (rowIn) rowIn.style.display = 'flex';
  const rowOut = $('userInfoRowLoggedOut'); if (rowOut) rowOut.style.display = 'none';
  
  const modelSelect = $('modelSelect');
  if (modelSelect) {
      Array.from(modelSelect.options).forEach(opt => opt.disabled = false);
      if (modelSelect.value === 'Halo') {
          modelSelect.value = 'Baymax';
          onModelChange();
      }
  }
  
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
      const res  = await fetch('/api/auth/logout', { 
        method: 'POST', 
        headers: { 'X-CSRFToken': getCsrfToken() },
        credentials: 'include' 
      });
      const data = await getJsonResponse(res);
      if (data.status === 'success') {
        currentUser = null; closeUserMenu();
        _syncSettingsUI();
        messages = []; attachedFiles = []; hasExistingApiKeys = false; hasGroqKey = false;
        updateFastModeDefault();
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
async function updateApiKeysPlaceholders() {
  try {
    const res  = await fetch('/api/keys/check', { method: 'GET', credentials: 'include' });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      hasExistingApiKeys = data.has_api_keys;
      hasGroqKey = data.has_groq_key;
      updateFastModeDefault();
      const gi = $('geminiApiKey'), oi = $('openrouterApiKey'), gri = $('groqApiKey'), hfi = $('huggingfaceApiKey');
      if (gi)  gi.placeholder  = data.keys.gemini      ? 'Modify your Gemini API key'     : 'Enter your Gemini API key';
      if (oi)  oi.placeholder  = data.keys.openrouter  ? 'Modify your OpenRouter API key'  : 'Enter your OpenRouter API key';
      if (gri) gri.placeholder = data.keys.groq        ? 'Modify your Groq API key'        : 'Enter your Groq API key (optional)';
      if (hfi) hfi.placeholder = data.keys.huggingface ? 'Modify your Hugging Face API key': 'Enter your Hugging Face API key (optional)';
    }
  } catch (err) { console.error('Failed to check API keys:', err); }
}

async function openApiKeys() {
  closeUserMenu();
  await updateApiKeysPlaceholders();
  openSettings('apikeys');
}

async function saveApiKeys() {
  const gemini      = $('geminiApiKey')?.value.trim()      || '';
  const openrouter  = $('openrouterApiKey')?.value.trim()  || '';
  const groq        = $('groqApiKey')?.value.trim()        || '';
  const huggingface = $('huggingfaceApiKey')?.value.trim() || '';
  if (!gemini && !openrouter && !groq && !huggingface) {
    showNotification('Please enter at least one API key', 'error'); return;
  }
  try {
    const res  = await fetch('/api/keys/save', {
      method: 'POST', 
      headers: { 
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      }, 
      credentials: 'include',
      body: JSON.stringify({ gemini, openrouter, groq, huggingface })
    });
    const data = await getJsonResponse(res);
    if (data.status === 'success') {
      const saveBtn = document.querySelector('#spanel-apikeys .modal-save-btn');
      if (saveBtn) {
        const orig = saveBtn.innerHTML;
        saveBtn.innerHTML = '<i class="fa-solid fa-check"></i> Saved Successfully!';
        saveBtn.style.background = 'linear-gradient(135deg, #0f8a55, var(--accent))';
        setTimeout(() => {
          saveBtn.innerHTML = orig; saveBtn.style.background = '';
          closeModal('personalizationModal');
          showNotification('API keys saved successfully!', 'success');
          // Re-evaluate API keys state from inputs
          hasExistingApiKeys = !!(gemini || openrouter);
          hasGroqKey = !!groq;
          updateFastModeDefault();
          updateApiKeysPlaceholders();
          if ($('geminiApiKey'))      $('geminiApiKey').value      = '';
          if ($('openrouterApiKey'))  $('openrouterApiKey').value  = '';
          if ($('groqApiKey'))        $('groqApiKey').value        = '';
          if ($('huggingfaceApiKey')) $('huggingfaceApiKey').value = '';
        }, 1500);
      } else {
        closeModal('personalizationModal');
        showNotification('API keys saved successfully!', 'success');
        hasExistingApiKeys = !!(gemini || openrouter);
        hasGroqKey = !!groq;
        updateFastModeDefault();
        updateApiKeysPlaceholders();
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
      method: 'POST', 
      headers: { 
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      }, 
      credentials: 'include',
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
function syncFastModeVisibility(model) {
  const fastBtn = $('fastModeBtn');
  if (fastBtn) {
    const hideFast = ['Halo', 'ZORVIN', 'Developer'].includes(model);
    fastBtn.style.display = hideFast ? 'none' : 'flex';
    if (hideFast) {
      isFastMode = false;
      fastBtn.classList.remove('active');
    }
  }
}

function toggleSearchMode() {
  isSearchMode = !isSearchMode;
  const btn = $('searchToggleBtn');
  if (btn) {
    btn.classList.toggle('active', isSearchMode);
  }
}

function onModelChange() {
  const select = $('modelSelect'); if (!select) return;
  const newModel = select.value;
  if (newModel === 'ZORVIN') {
    showConfirm('Download Hero\'s AI for ZORVIN Offline',
      () => {
        showNotification('Currently in development status', 'info');
        select.value = currentModel;
        syncFastModeVisibility(currentModel);
      },
      () => {
        select.value = currentModel;
        syncFastModeVisibility(currentModel);
      },
      'Download', 'Cancel');
  } else if (newModel === 'Developer') {
    openDeveloperModal();
    syncFastModeVisibility('Developer');
  } else {
    if (isDeveloperMode) {
      isDeveloperMode = false;
      const devSidebar = $('developerSidebar');
      if (devSidebar) devSidebar.style.display = 'none';
      const toggleBtn = $('devSidebarToggleBtn');
      if (toggleBtn) toggleBtn.style.display = 'none';
      newChat();
    }
    currentModel = newModel;
    const chip = $('modelChipName');
    if (chip) chip.textContent = currentModel;
    
    const voiceModelSpan = $('voiceModelName');
    if (voiceModelSpan) {
      voiceModelSpan.textContent = select.options[select.selectedIndex].text;
    }
    
    if (currentModel === 'Baymax' && !hasExistingApiKeys) {
        showNotification('Please add Gemini or OpenRouter API key in profile / settings / api key to use Baymax.', 'info');
    }
    
    syncFastModeVisibility(currentModel);
    updateFastModeDefault();
    addSystemNote('Switched to ' + currentModel);
  }
}

/* ════════ WELCOME SCREEN ════════ */
function activateChatBg() {
  const ws = $('welcomeScreen'), md = $('messages');
  if (!ws || !md) return;
  ws.classList.add('chat-bg');
  ws.style.display = 'none';
  md.style.display = 'block';
}

/* ════════ CHAT ════════ */
let isFastMode = false;

function toggleFastModeBtn(btn) {
  if (!isFastMode && !hasGroqKey) {
    showNotification('Please add Groq API key in profile / settings / api key for Fast response.', 'error');
    return;
  }
  isFastMode = !isFastMode;
  if (isFastMode) {
    btn.classList.add('active');
    showNotification('Fast mode enabled', 'info');
  } else {
    btn.classList.remove('active');
  }
}

function updateFastModeDefault() {
  const fastBtn = $('fastModeBtn');
  if (fastBtn) {
    if (hasGroqKey) {
      isFastMode = true;
      fastBtn.classList.add('active');
    } else {
      isFastMode = false;
      fastBtn.classList.remove('active');
    }
  }
}

async function sendMessage() {
  if (isLoading) return;
  const inp = $('chatInput'); if (!inp) return;
  const text = inp.value.trim();
  if (!text && attachedFiles.length === 0) return;

  activateChatBg();

  let taskType = activeMode;
  if (isDeveloperMode) {
    taskType = 'developer';
  } else {
    const hasFile = attachedFiles.length > 0;
    if (isSearchMode && isCodeMode && hasFile) taskType = 'search_code_file';
    else if (isSearchMode && isCodeMode) taskType = 'search_code';
    else if (isSearchMode && hasFile) taskType = 'search_file';
    else if (isCodeMode && hasFile) taskType = 'code_file';
    else if (hasFile) taskType = 'file_handle';
    else if (isSearchMode) taskType = 'websearch';
    else if (isCodeMode) taskType = 'coding';
    else if (!taskType) taskType = 'text';
  }

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
    if (messages.length > 1) {
      sessionHistory = messages.slice(0, -1);
    }

    // FIX: Send temporary_chat (not temporary) matching backend expectations
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
      },
      credentials: 'include',
      body: JSON.stringify({
        message:          text,
        model:            currentModel,
        mode:             taskType,
        session_id:       (tempChatActive || isDeveloperMode) ? null : currentSessionId,
        temporary_chat:   isDeveloperMode ? true : tempChatActive,
        is_fast:          isFastMode,
        has_files:        userMsg.files.length > 0,
        file_count:       userMsg.files.length,
        files:            userMsg.files,
        is_developer:     isDeveloperMode,
        dev_provider:     isDeveloperMode ? devConfig.provider : '',
        dev_model_name:   isDeveloperMode ? devConfig.model : '',
        send_history:     sessionHistory,
        remember_history: !!userSettings.rememberHistory
      })
    });
    
    // Use the helper to avoid "Unexpected token <" if server crashes with HTML
    const data = await getJsonResponse(res);
    typingRow.remove();

    if (data.status === 'success') {
      // FIX: Don't update currentSessionId if this was a temporary chat
      if (data.session_id && !currentSessionId && !tempChatActive && !isDeveloperMode) {
        currentSessionId = data.session_id;
        loadChatHistory();
      }
      const aiMsg = { 
        role: 'assistant', 
        content: data.reply,
        is_developer: isDeveloperMode,
        status_code: data.status_code,
        error: data.error,
        dev_model: data.dev_model,
        time_taken: data.time_taken
      };
      messages.push(aiMsg);
      renderMessage(aiMsg);

      /* Auto-read AI responses aloud when enabled in settings */
      const ttsBlockedModes = ['coding', 'file_handle'];
      if (userSettings.autoReadResponses && !ttsBlockedModes.includes(taskType)) {
        speakText(data.reply);
      }

      // FIX: Only reload chat history if it's not a temporary chat
      if (data.is_new_chat && !tempChatActive && !isDeveloperMode) {
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
      userMsg = "Heros encountered a server processing error. Please try again or check your settings.";
    }
    renderMessage({ role: 'assistant', content: `Error: ${userMsg}` });
  }

  isLoading = false; toggleSendBtn();
}

/* ── Voice → Chat thread ── */
function pushVoiceToChat(userText, aiText, data, filesPayload = []) {
  if (!userText) return;
  activateChatBg();
  const userMsg = { role: 'user', content: userText, files: filesPayload ? [...filesPayload] : [], mode: 'voice' };
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
  const isUser     = msg.role === 'user';
  const row = document.createElement('div');
  row.className = 'msg-row' + (isUser ? ' user-row' : '');
  if (userSettings.compactLayout) row.style.padding = '8px 0';

  const initials   = (currentUser && isUser) ? currentUser.initials : (isUser ? 'U' : '');
  const avatarHTML = isUser
    ? initials
    : '<img src="/static/images/Hero_ai.png" width="30" height="30" style="object-fit:contain;display:block;" alt="Heros">';

  let filesHTML = '';
  if (msg.files?.length > 0) {
    msg.files.forEach(f => {
      filesHTML += f.type?.startsWith('image/') && f.dataUrl
        ? `<img class="img-preview" src="${f.dataUrl}" alt="${escHtml(f.name)}"/>`
        : `<div class="file-badge"><i class="fa-regular fa-file" style="font-size:0.75rem;"></i>${escHtml(f.name)}</div>`;
    });
  }

  let modeTag = '';
  // Removed modeTag rendering per user request

  const displayName = isUser ? (currentUser ? currentUser.name.split(' ')[0] : 'You') : (msg.is_developer ? 'Developer AI' : "Heros");

  let devFooter = '';
  if (msg.is_developer) {
    devFooter = `<div style="margin-top: 10px; padding: 10px; background: rgba(0,0,0,0.2); border-left: 3px solid var(--accent); font-family: monospace; font-size: 0.85em; border-radius: 4px;">
      <strong style="color: var(--accent);">Model:</strong> <span style="color: #ccc;">${msg.dev_model || 'Unknown'}</span><br>
      <strong style="color: ${msg.status_code === 200 ? '#4ade80' : '#f87171'};">Status Code: ${msg.status_code || 'Unknown'}</strong><br>
      <strong style="color: var(--accent);">Time Taken:</strong> <span style="color: #ccc;">${msg.time_taken ? msg.time_taken + 's' : 'Unknown'}</span><br>
      <strong style="color: var(--accent);">Error:</strong> <span style="color: #999;">${msg.error ? escHtml(msg.error) : 'None'}</span>
    </div>`;
  }

  row.innerHTML = `
    <div class="msg-avatar ${isUser ? 'user' : 'ai'}">${avatarHTML}</div>
    <div class="msg-content ${isUser ? 'user' : 'ai'}">
      <div class="sender-row">
        <span class="sender">${displayName}</span>
        <button class="copy-msg-btn" title="Copy" onclick="copyMsg(this)"><i class="fa-regular fa-copy"></i></button>
      </div>
      ${modeTag}${filesHTML}
      <div class="bubble">${formatContent(msg.content || '')}${devFooter}</div>
    </div>`;

  // If the reply is a login-required alert, inject navigation buttons into the bubble
  if (!isUser && msg.content && msg.content.includes('Login Required')) {
    const bubble = row.querySelector('.bubble');
    if (bubble) {
      const btnRow = document.createElement('div');
      btnRow.style.cssText = 'display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;';
      btnRow.innerHTML = `
        <a href="/" style="display:inline-flex;align-items:center;gap:6px;padding:7px 18px;border-radius:30px;background:linear-gradient(135deg,#7b2cbf,#c77dff);color:#fff;font-size:0.9rem;font-weight:600;text-decoration:none;transition:transform 0.2s,box-shadow 0.2s;box-shadow:0 4px 14px rgba(123,44,191,0.35);" onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 8px 22px rgba(123,44,191,0.5)'" onmouseout="this.style.transform='';this.style.boxShadow='0 4px 14px rgba(123,44,191,0.35)'">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 16 16"><path d="M8.354 1.146a.5.5 0 0 0-.708 0l-6 6A.5.5 0 0 0 1.5 7.5v7a.5.5 0 0 0 .5.5h4.5a.5.5 0 0 0 .5-.5v-4h2v4a.5.5 0 0 0 .5.5H14a.5.5 0 0 0 .5-.5v-7a.5.5 0 0 0-.146-.354L13 5.793V2.5a.5.5 0 0 0-.5-.5h-1a.5.5 0 0 0-.5.5v1.293L8.354 1.146z"/></svg>
          Go to Home
        </a>
        <a href="http://127.0.0.1:8000/" target="_blank" style="display:inline-flex;align-items:center;gap:6px;padding:7px 18px;border-radius:30px;background:transparent;color:#c77dff;font-size:0.9rem;font-weight:600;text-decoration:none;border:1.5px solid #c77dff;transition:transform 0.2s,background 0.2s;" onmouseover="this.style.transform='translateY(-2px)';this.style.background='rgba(199,125,255,0.1)'" onmouseout="this.style.transform='';this.style.background='transparent'">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 16 16"><path d="M0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8zm7.5-6.923c-.67.204-1.335.82-1.887 1.855A7.97 7.97 0 0 0 5.145 4H7.5V1.077zM4.09 4a9.267 9.267 0 0 1 .64-1.539 6.7 6.7 0 0 1 .597-.933A7.025 7.025 0 0 0 2.255 4H4.09zm-.582 3.5c.03-.877.138-1.718.312-2.5H1.674a6.958 6.958 0 0 0-.656 2.5h2.49zM4.847 5a12.5 12.5 0 0 0-.338 2.5H7.5V5H4.847zM8.5 5v2.5h2.99a12.495 12.495 0 0 0-.337-2.5H8.5zM4.51 8.5a12.5 12.5 0 0 0 .337 2.5H7.5V8.5H4.51zm3.99 0V11h2.653c.187-.765.306-1.608.338-2.5H8.5zM5.145 12c.138.386.295.744.468 1.068.552 1.035 1.218 1.65 1.887 1.855V12H5.145zm.182 2.472a6.696 6.696 0 0 1-.597-.933A9.268 9.268 0 0 1 4.09 12H2.255a7.024 7.024 0 0 0 3.072 2.472zM3.82 11a13.652 13.652 0 0 1-.312-2.5h-2.49c.062.89.291 1.733.656 2.5H3.82zm6.853 3.472A7.024 7.024 0 0 0 13.745 12H11.91a9.27 9.27 0 0 1-.64 1.539 6.688 6.688 0 0 1-.597.933zM8.5 12v2.923c.67-.204 1.335-.82 1.887-1.855.173-.324.33-.682.468-1.068H8.5zm3.68-1h2.146c.365-.767.594-1.61.656-2.5h-2.49a13.65 13.65 0 0 1-.312 2.5zm2.802-3.5a6.959 6.959 0 0 0-.656-2.5H11.68c.174.782.282 1.623.312 2.5h2.49zM11.27 2.461c.247.464.462.98.64 1.539h1.835a7.024 7.024 0 0 0-3.072-2.472c.218.284.418.598.597.933zM10.855 4a7.966 7.966 0 0 0-.468-1.068C9.835 1.897 9.17 1.282 8.5 1.077V4h2.355z"/></svg>
          Go to Localhost
        </a>`;
      bubble.appendChild(btnRow);
    }
  }

  container.appendChild(row);
  
  if (isUser) {
    container.scrollTop = container.scrollHeight;
  } else {
    const offset = row.offsetTop - 20; 
    container.scrollTo({ top: Math.max(0, offset), behavior: 'smooth' });
    // Render math in the new bubble using KaTeX auto-render
    const bubble = row.querySelector('.bubble');
    if (bubble && window.renderMathInElement) {
      try {
        renderMathInElement(bubble, {
          delimiters: [
            { left: '$$', right: '$$', display: true },
            { left: '$',  right: '$',  display: false }
          ],
          throwOnError: false
        });
      } catch(e) {}
    }
    // Highlight code blocks if syntax highlighting is enabled
    if (bubble && userSettings.syntaxHighlighting && window.hljs) {
      bubble.querySelectorAll('pre code').forEach((block) => {
        try { hljs.highlightElement(block); } catch(e) {}
      });
    }
  }
  return row;
}


/* ════════ TYPING INDICATOR ════════ */
function showTyping(mode) {
  const container = $('messages');
  if (!container) return document.createElement('div');
  const row = document.createElement('div');
  row.className = 'msg-row';
  
  // Decide the list of task words
  let tasks = ['Processing query', 'Identifying task', 'Formulating response', 'Finalizing response'];
  if (mode === 'websearch' || mode === 'voice_search') {
    tasks = ['Processing query', 'Identifying task', 'Searching the web', 'Synthesizing search data', 'Finalizing response'];
  } else if (mode === 'coding' || mode === 'search_code') {
    tasks = ['Processing query', 'Identifying task', 'Generating code', 'Finalizing response'];
  } else if (mode === 'file_handle' || mode === 'code_file' || mode === 'voice_file') {
    tasks = ['Processing query', 'Identifying task', 'Reading attachments', 'Analyzing file data', 'Finalizing response'];
  } else if (mode === 'search_file' || mode === 'search_code_file' || mode === 'voice_search_file') {
    tasks = ['Processing query', 'Identifying task', 'Reading attachments', 'Searching the web', 'Analyzing file data', 'Finalizing response'];
  } else if (mode === 'Voice Chat' || mode === 'voice_message' || mode === 'zeno_voice') {
    tasks = ['Processing query', 'Formulating response', 'Finalizing response'];
  }

  row.innerHTML = `
    <div class="msg-avatar ai">
      <img src="/static/images/Hero_ai.png" width="30" height="30"
           style="object-fit:contain;display:block;" alt="Heros">
    </div>
    <div class="msg-content ai">
      <div class="sender-row"><span class="sender">Heros</span></div>
      <div class="typing-inline">
        <div class="spinnerContainer">
          <div class="spinner"></div>
          <div class="loader">
            <div class="words-wrapper">
              <span class="word active-word">Processing query</span>
              <span class="word next-word"></span>
            </div>
          </div>
        </div>
      </div>
    </div>`;

  // Animation controller
  const wrapper = row.querySelector('.words-wrapper');
  const activeWord = row.querySelector('.active-word');
  const nextWord = row.querySelector('.next-word');
  
  if (wrapper && activeWord && nextWord) {
    let index = 0;
    activeWord.textContent = tasks[0];

    const intervalId = setInterval(() => {
      if (index >= tasks.length - 1) {
        clearInterval(intervalId);
        return;
      }
      index++;
      
      nextWord.textContent = tasks[index];
      wrapper.classList.remove('no-transition');
      wrapper.classList.add('slide-up');
      
      setTimeout(() => {
        activeWord.textContent = tasks[index];
        wrapper.classList.add('no-transition');
        wrapper.classList.remove('slide-up');
      }, 350); // Matches CSS transition duration
    }, 1500); // Shift every 1.5s

    row._loaderInterval = intervalId;
  }

  // Override remove to clean up the interval automatically
  const originalRemove = row.remove;
  row.remove = function() {
    if (row._loaderInterval) {
      clearInterval(row._loaderInterval);
    }
    originalRemove.call(row);
  };

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

  // ── Protect raw HTML blocks (extracted before escaping) ───────
  const rawHtmlBlocks = [];
  text = text.replace(/<div data-raw[^>]*>[\s\S]*?<\/div>/g, (match) => {
    const i = rawHtmlBlocks.length;
    rawHtmlBlocks.push(match);
    return `%%RAWHTML_${i}%%`;
  });

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
  // Updated regex: optional leading pipes, requires a separator line with at least one dash AND at least one pipe
  text = text.replace(/^([ \t]*\|?.*\|.*)\n([ \t]*\|?[:\- ]*[-]+[:\- ]*\|[:\- |]*)\n((?:[ \t]*\|?.*\|.*\n?)*)/gm,
    (_, header, _sep, body) => {
      const i = tables.length;
      const parseRow = (row) => {
        // Remove leading/trailing pipes and split by pipe
        return row.trim().replace(/^\||\|$/g, '').split('|').map(c => {
          let cell = c.trim();
          // Escape HTML for security but preserve <br> tags
          cell = cell.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
          cell = cell.replace(/&lt;br\s*\/?&gt;/gi, '<br>');

          // Apply basic markdown formatting within cells
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

  // ── Protect LaTeX math blocks before HTML escaping ─────────────
  const mathBlocks = [];
  // Block math: $$...$$
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, inner) => {
    const i = mathBlocks.length;
    mathBlocks.push(`<span class="math-block">$$${inner}$$</span>`);
    return `%%MATHBLOCK_${i}%%`;
  });
  // Inline math: $...$  (not $$)
  text = text.replace(/(?<!\$)\$([^$\n]+?)\$(?!\$)/g, (_, inner) => {
    const i = mathBlocks.length;
    mathBlocks.push(`<span class="math-inline">$${inner}$</span>`);
    return `%%MATHBLOCK_${i}%%`;
  });

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
  // First: fix "number on its own line" pattern — join `1.\nText` into `1. Text`
  text = text.replace(/^([ \t]*\d+\.)\n+(?=\S)/gm, '$1 ');
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
  codeBlocks.forEach((block, i) => { text = text.replace(`%%CODEBLOCK_${i}%%`, () => block); });
  inlineCodes.forEach((block, i) => { text = text.replace(`%%INLINE_${i}%%`,   () => block); });
  tables.forEach((block, i)      => { text = text.replace(`%%TABLE_${i}%%`,    () => block); });
  rawHtmlBlocks.forEach((block, i) => { text = text.replace(`%%RAWHTML_${i}%%`, () => block); });
  mathBlocks.forEach((block, i)    => { text = text.replace(`%%MATHBLOCK_${i}%%`, () => block); });

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
  $('fileInput')?.click();
}

function toggleCodingMode() {
  isCodeMode = !isCodeMode;
  const btn = $('codeToggleBtn');
  if (btn) {
    btn.classList.toggle('active', isCodeMode);
  }
}

function setMode(mode) {
  closePlusMenu();
  if (mode === 'websearch') {
    isSearchMode = true;
    $('searchToggleBtn')?.classList.add('active');
  } else if (mode === 'coding') {
    isCodeMode = true;
    $('codeToggleBtn')?.classList.add('active');
  } else {
    activeMode = mode;
  }
  $('chatInput')?.focus();
}

function clearMode() {
  activeMode = null;
  isSearchMode = false;
  isCodeMode = false;
  const badge = $('modeBadge');
  if (badge) { badge.classList.remove('visible'); badge.className = 'mode-badge'; }
  const searchBtn = $('searchToggleBtn');
  if (searchBtn) {
    searchBtn.classList.remove('active');
  }
  const codeBtn = $('codeToggleBtn');
  if (codeBtn) {
    codeBtn.classList.remove('active');
  }
}

function switchSettingsNav(name) {
  document.querySelectorAll('.settings-nav-item').forEach(i => i.classList.remove('active'));
  document.querySelectorAll('.settings-panel').forEach(p => p.classList.remove('active'));
  $('snav-' + name)?.classList.add('active');
  $('spanel-' + name)?.classList.add('active');
  if (name === 'apikeys') {
    updateApiKeysPlaceholders();
  }
}

/* Legacy tab switcher kept for any old references */
function switchPTab(name, btn) {
  const map = { interface: 'general', about: 'personalization', instructions: 'instructions' };
  switchSettingsNav(map[name] || name);
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

async function openPersonalization() { openSettings('personalization'); }

async function openSettings(panel) {
  closeUserMenu();
  loadUserSettings();
  switchSettingsNav(panel || 'general');
  $('personalizationModal')?.classList.add('active');
}


function openHelp()       { openSettings('help'); }
function openAboutHeros() { openSettings('about'); }
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
    const inp = $('chatInput');
    const hasContent = (inp && (inp.value.trim().length > 0 || attachedFiles.length > 0));
    if (hasContent && !isLoading) sendMessage();
  }
}

function autoResize(el) {
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

function handleSendMicClick() {
  const inp = $('chatInput');
  const hasContent = (inp && (inp.value.trim().length > 0 || attachedFiles.length > 0));
  if (hasContent || isLoading) {
    sendMessage();
  } else {
    toggleInlineMic();
  }
}

function toggleSendBtn() {
  const inp = $('chatInput'), btn = $('sendMicBtn'), icon = $('sendMicIcon');
  if (!inp || !btn || !icon) return;
  
  const hasContent = (inp.value.trim().length > 0 || attachedFiles.length > 0);
  
  if (hasContent || isLoading) {
    btn.className = 'send-btn';
    btn.style.background = 'var(--accent)';
    btn.style.color = '#000';
    btn.title = 'Send message';
    icon.className = 'fa-solid fa-paper-plane';
    btn.disabled = isLoading;
  } else {
    btn.className = inlineMicOn ? 'mic-btn listening' : 'mic-btn';
    btn.style.background = inlineMicOn ? 'rgba(25,195,125,0.15)' : 'transparent';
    btn.style.color = inlineMicOn ? 'var(--accent)' : 'var(--text-muted)';
    btn.title = inlineMicOn ? 'Listening...' : 'Talk to AI';
    icon.className = 'fa-solid fa-microphone';
    btn.disabled = false;
  }
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
    toggleSendBtn(); return;
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
  inlineRecog.onend = () => { inlineMicOn = false; toggleSendBtn(); };
  inlineRecog.start();
  inlineMicOn = true;
  toggleSendBtn();
}

/* ══════════════════════════════════════════════════════
   TTS HELPERS
   ══════════════════════════════════════════════════════ */
function _sanitiseForTTS(raw) {
  let t = raw || '';
  t = t.replace(/<[^>]+>/g, ' ');          // strip HTML tags
  t = t.replace(/```[\s\S]*?```/g, ' code block. ');  // code blocks → spoken label
  t = t.replace(/`([^`]+)`/g, '$1');       // inline code → just text
  t = t.replace(/\$\$[\s\S]+?\$\$/g, ' ');  // strip block math
  t = t.replace(/(?<!\$)\$[^$\n]+?\$/g, ' ');  // strip inline math
  t = t.replace(/https?:\/\/[^\s)>\]"']+/gi, '');  // strip URLs
  t = t.replace(/www\.[^\s)>\]"']+/gi, '');
  t = t.replace(/\*\*(.*?)\*\*/g, '$1');   // bold → plain
  t = t.replace(/\*(.*?)\*/g, '$1');       // italic → plain
  t = t.replace(/^#+\s*/gm, '');          // headings → plain
  t = t.replace(/[-*_]{2,}/g, ' ');       // horizontal rules / decorations
  t = t.replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '');
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
  const statusEl = $('voiceStatus'), speakBtn = $('speakBtn'), pauseBtn = $('pauseVoiceBtn'), waitBtn = $('waitVoiceBtn'), mainWaitBtn = $('mainWaitBtn');
  switch (state) {
    case VOICE_STATE.IDLE:
      if (statusEl) statusEl.textContent = '';
      if (speakBtn) { speakBtn.innerHTML = '<i class="fa-solid fa-microphone"></i> Speak'; speakBtn.style.background = ''; speakBtn.style.color = ''; }
      if (pauseBtn) pauseBtn.disabled = true;
      if (waitBtn) waitBtn.disabled = true;
      if (mainWaitBtn) { mainWaitBtn.disabled = true; mainWaitBtn.style.display = 'none'; }
      isListening = false; break;
    case VOICE_STATE.LISTENING:
      if (statusEl) statusEl.innerHTML = '<span style="display:inline-flex;align-items:center;gap:6px;"><span style="width:8px;height:8px;border-radius:50%;background:#e74c3c;animation:pulse-dot 1s infinite;display:inline-block;"></span>Listening…</span>';
      if (speakBtn) { speakBtn.innerHTML = '<i class="fa-solid fa-stop"></i> Stop'; speakBtn.style.background = '#e74c3c'; speakBtn.style.color = '#fff'; }
      if (pauseBtn) pauseBtn.disabled = true;
      if (waitBtn) waitBtn.disabled = true;
      if (mainWaitBtn) { mainWaitBtn.disabled = true; mainWaitBtn.style.display = 'none'; }
      isListening = true; 
      restartMicStream();
      break;
    case VOICE_STATE.THINKING:
      if (statusEl) statusEl.innerHTML = '<span style="display:inline-flex;align-items:center;gap:6px;"><span class="typing-dots" style="display:inline-flex;gap:3px;"><span style="width:5px;height:5px;border-radius:50%;background:var(--accent);animation:bounce-dot 0.8s infinite 0s;display:inline-block;"></span><span style="width:5px;height:5px;border-radius:50%;background:var(--accent);animation:bounce-dot 0.8s infinite 0.15s;display:inline-block;"></span><span style="width:5px;height:5px;border-radius:50%;background:var(--accent);animation:bounce-dot 0.8s infinite 0.3s;display:inline-block;"></span></span> Thinking…</span>';
      if (pauseBtn) pauseBtn.disabled = true;
      if (waitBtn) waitBtn.disabled = true;
      if (mainWaitBtn) { mainWaitBtn.disabled = true; mainWaitBtn.style.display = 'none'; }
      isListening = false; 
      stopMicStream();
      break;
    case VOICE_STATE.SPEAKING:
      if (statusEl) statusEl.innerHTML = '<span style="display:inline-flex;align-items:center;gap:6px;"><i class="fa-solid fa-volume-high" style="color:var(--accent);animation:pulse-dot 0.8s infinite;"></i> Speaking… (Press Space to interrupt)</span>';
      if (pauseBtn) pauseBtn.disabled = false;
      if (waitBtn) waitBtn.disabled = false;
      if (mainWaitBtn) { mainWaitBtn.disabled = false; mainWaitBtn.style.display = 'inline-flex'; }
      isListening = true; 
      stopMicStream();
      break;
  }
}

function handleWaitButtonClick(e) {
  if (e) {
    try { e.preventDefault(); e.stopPropagation(); } catch(_) {}
  }
  if (voiceActive && voiceState === VOICE_STATE.SPEAKING) {
    try {
      stopCurrentTTSAudio(true);
    } catch(err) {
      console.warn('Error during TTS interruption:', err);
    }
    _setVoiceState(VOICE_STATE.LISTENING);
    const el = $('voiceTranscript'); if (el) el.textContent = 'Speak now…';
    ignoreVoiceUntil = Date.now() + 200;
    restartMicStream().finally(() => {
      if (voiceActive && voiceState === VOICE_STATE.LISTENING) {
        _startRecognition();
      }
    });
  }
}

document.addEventListener('keydown', (e) => {
  if (e.code === 'Space' || e.key === ' ' || e.keyCode === 32) {
    if (voiceActive && voiceState === VOICE_STATE.SPEAKING) {
      const tag = document.activeElement ? document.activeElement.tagName : '';
      if (['INPUT', 'TEXTAREA'].includes(tag) || document.activeElement?.isContentEditable) {
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      handleWaitButtonClick(e);
    }
  }
}, true);

function setModeCodingAndPrompt() {
  setMode('coding');
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
  
  const isInline = el.classList.contains('inline-mode');
  let html = '';
  
  if (userText) {
    if (isInline) {
      html += `<div style="font-size:0.95rem;color:var(--text);">${escHtml(userText)}</div>`;
    } else {
      html += `<div style="margin-bottom:0.65rem;padding:0.6rem 0.85rem;background:rgba(255,255,255,0.05);border-radius:8px;">
        <div style="font-size:0.72rem;color:var(--accent);font-weight:600;margin-bottom:3px;">YOU</div>
        <div style="font-size:0.9rem;">${escHtml(userText)}</div></div>`;
    }
  }
  
  if (aiText && !isInline) {
    html += `<div style="padding:0.6rem 0.85rem;background:rgba(25,195,125,0.07);border-radius:8px;">
      <div style="font-size:0.72rem;color:var(--accent);font-weight:600;margin-bottom:3px;">Heros</div>
      <div style="font-size:0.9rem;">${formatContent(aiText)}</div></div>`;
  }
  
  el.innerHTML = html;
  requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
}

function _showInterim(text) {
  const el = $('voiceTranscript'); if (!el || !text) return;
  const isInline = el.classList.contains('inline-mode');
  
  if (isInline) {
    el.innerHTML = `<div style="font-size:0.95rem;color:var(--text-dim);">${escHtml(text)}</div>`;
  } else {
    el.innerHTML = `<div style="padding:0.6rem 0.85rem;border-radius:8px;border:0.5px dashed rgba(25,195,125,0.3);">
      <div style="font-size:0.72rem;color:var(--accent);font-weight:600;margin-bottom:3px;">YOU</div>
      <div style="font-size:0.9rem;color:var(--text-dim);">${escHtml(text)}</div></div>`;
  }
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
  try { mediaStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }); }
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
  if (voiceRecog) {
    try { voiceRecog.onend = null; voiceRecog.onerror = null; voiceRecog.abort(); } catch (_) {}
    voiceRecog = null;
  }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return;
  voiceRecog = new SR();
  voiceRecog.lang = 'en-US'; voiceRecog.continuous = true; voiceRecog.interimResults = true;

  voiceRecog.onresult = (event) => {
    if (Date.now() < ignoreVoiceUntil) return;
    
    let interim = '', final = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const t = event.results[i][0].transcript;
      event.results[i].isFinal ? (final += t + ' ') : (interim += t);
    }

    // While model is THINKING, allow user to modify / add to their spoken message
    if (voiceState === VOICE_STATE.THINKING) {
      const added = (final + interim).trim();
      if (added.length > 0) {
        const lastMsg = messages[messages.length - 1];
        if (lastMsg && lastMsg.role === 'user') {
          lastMsg.content = (lastMsg.content + ' ' + added).trim();
          const bubbles = document.querySelectorAll('.msg-row.user-row .bubble');
          if (bubbles.length > 0) {
            bubbles[bubbles.length - 1].innerHTML = formatContent(lastMsg.content);
          }
        }
        const currentPrompt = messages[messages.length - 1]?.content || added;
        _showTranscript(currentPrompt, 'Thinking…');
      }
      return;
    }

    // Mic is OFF while AI is SPEAKING — ignore any residual events
    if (voiceState === VOICE_STATE.SPEAKING) {
      return;
    }

    if (voiceState !== VOICE_STATE.LISTENING) return;
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
    if (voiceActive && (voiceState === VOICE_STATE.LISTENING || voiceState === VOICE_STATE.SPEAKING)) {
      setTimeout(() => {
        if (voiceActive) _startRecognition();
      }, 150);
    }
  };
  voiceRecog.onerror = (e) => {
    if (e.error === 'aborted' || e.error === 'no-speech') return;
    console.warn('Speech recognition error:', e.error);
  };
  try { voiceRecog.start(); } catch (_) {}
}

function muteMicStream() {
  if (mediaStream) {
    try { mediaStream.getAudioTracks().forEach(t => t.enabled = false); } catch(_) {}
  }
}

async function unmuteMicStream() {
  if (!mediaStream) {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (audioCtx && analyser) {
        audioCtx.createMediaStreamSource(mediaStream).connect(analyser);
      }
    } catch (e) {
      console.warn('Failed to get mic stream:', e);
    }
  } else {
    try { mediaStream.getAudioTracks().forEach(t => t.enabled = true); } catch(_) {}
  }
}

function stopMicStream() {
  muteMicStream();
}

function closeMicStream() {
  if (mediaStream) {
    try { mediaStream.getTracks().forEach(t => t.stop()); } catch(_) {}
    mediaStream = null;
  }
}

async function restartMicStream() {
  await unmuteMicStream();
}

async function _sendToAI(userText) {
  if (!voiceActive || !userText) return;
  if (voiceState !== VOICE_STATE.THINKING) _setVoiceState(VOICE_STATE.THINKING);
  _showTranscript(userText, '');
  voiceFinalText = ''; voiceInterimText = '';
  
  let mode = 'Voice Chat';
  let filesPayload = [];
  const hasFile = attachedFiles.length > 0;
  if (hasFile) {
    filesPayload = [...attachedFiles];
    attachedFiles = [];
    const ap = $('attachPreviewRow'); if (ap) ap.innerHTML = '';
    toggleSendBtn();
  }

  if (isSearchMode && isCodeMode && hasFile) mode = 'voice_search_code_file';
  else if (isSearchMode && isCodeMode) mode = 'voice_search_code';
  else if (isSearchMode && hasFile) mode = 'voice_search_file';
  else if (isCodeMode && hasFile) mode = 'voice_code_file';
  else if (isCodeMode) mode = 'voice_code';
  else if (isSearchMode) mode = 'voice_search';
  else if (hasFile) mode = 'voice_file';
  
  // Render user message to the main chat screen immediately
  activateChatBg();
  const userMsg = { role: 'user', content: userText, files: filesPayload ? [...filesPayload] : [], mode: 'voice' };
  messages.push(userMsg);
  renderMessage(userMsg);
  
  const active = document.querySelector('.history-item.active');
  if (active && (active.textContent.includes('Welcome chat') || active.textContent.includes('New chat'))) {
    active.innerHTML = '<i class="fa-solid fa-microphone"></i><span class="history-preview">' + escHtml(userText.slice(0, 40)) + '</span>';
  }

  // Show thinking typing row in chat interface
  const typingRow = showTyping('Voice Chat');
  
  let sessionHistory = [];
  if (typeof userSettings !== 'undefined' && userSettings.rememberHistory && messages.length > 0) {
    sessionHistory = messages.slice();
  } else if (messages.length > 0) {
    sessionHistory = messages.slice(); // Safe fallback if userSettings isn't available
  }
  
  try {
    const res  = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify({ 
        message:          userText, 
        model:            currentModel, 
        mode:             mode, 
        session_id:       currentSessionId,
        has_files:        filesPayload.length > 0,
        file_count:       filesPayload.length,
        files:            filesPayload,
        send_history:     sessionHistory,
        remember_history: !!userSettings.rememberHistory
      })
    });
    const data = await getJsonResponse(res);
    
    // Remove the typing indicator row
    if (typingRow) typingRow.remove();
    
    if (data.status === 'success') {
      if (data.session_id && !currentSessionId) { currentSessionId = data.session_id; loadChatHistory(); }
      const reply = (data.reply || '').trim();
      _showTranscript(userText, reply);
      _setVoiceState(VOICE_STATE.SPEAKING);
      
      // Render only AI message now
      const aiMsg = { role: 'assistant', content: reply, mode: 'voice' };
      messages.push(aiMsg);
      const aiMsgRow = renderMessage(aiMsg);
      
      currentAITextClean = _sanitiseForTTS(reply).toLowerCase().replace(/[^a-z0-9 ]/g, '').replace(/\s+/g, ' ').trim();

      // Immediately shut off microphone and STT BEFORE starting TTS playback
      try { voiceRecog?.stop(); } catch(_) {}
      stopMicStream();

      _speakReply(reply, aiMsgRow, () => {
        if (!voiceActive) return;
        _setVoiceState(VOICE_STATE.LISTENING);
        const el = $('voiceTranscript'); if (el) el.textContent = 'Speak now…';
        ignoreVoiceUntil = Date.now() + 1500;
        setTimeout(() => {
          if (voiceActive && voiceState === VOICE_STATE.LISTENING) {
            restartMicStream().then(() => _startRecognition());
          }
        }, 1500);
      });
    } else {
      const el = $('voiceStatus'); if (el) el.textContent = 'Error: ' + (data.message || 'AI failed');
      if (voiceActive) { _setVoiceState(VOICE_STATE.LISTENING); _startRecognition(); }
    }
  } catch (err) {
    if (typingRow) typingRow.remove();
    console.error('Voice AI error:', err);
    const el = $('voiceStatus'); if (el) el.textContent = 'Network error. Listening again…';
    if (voiceActive) { _setVoiceState(VOICE_STATE.LISTENING); _startRecognition(); }
  }
}

function _wrapBubbleWords(msgRow) {
  if (!msgRow) return [];
  const bubble = msgRow.querySelector('.bubble');
  if (!bubble) return [];
  // Only wrap text nodes — don't touch code blocks or other HTML
  const wordSpans = [];
  const treeWalker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  let node;
  while ((node = treeWalker.nextNode())) {
    // Skip text inside <code>, <pre>, <script>, <style>
    let parent = node.parentElement;
    let skip = false;
    while (parent && parent !== bubble) {
      if (['CODE','PRE','SCRIPT','STYLE'].includes(parent.tagName)) { skip = true; break; }
      parent = parent.parentElement;
    }
    if (!skip && node.textContent.trim().length > 0) textNodes.push(node);
  }
  textNodes.forEach(textNode => {
    const frag = document.createDocumentFragment();
    const parts = textNode.textContent.split(/(\s+)/);
    parts.forEach(part => {
      if (/\S/.test(part)) {
        const span = document.createElement('span');
        span.className = 'tts-word';
        span.textContent = part;
        wordSpans.push(span);
        frag.appendChild(span);
      } else {
        frag.appendChild(document.createTextNode(part));
      }
    });
    textNode.parentNode.replaceChild(frag, textNode);
  });
  return wordSpans;
}

let currentAudioSource = null;
let ttsAnimFrame = null;
let ttsQueueCancelled = false;
let activeTTSWordSpans = [];
let activeTTSWordIdx = -1;
let activeTTSMsgRow = null;

function stopCurrentTTSAudio(isUserInterruption = false) {
  ttsQueueCancelled = true;
  if (isUserInterruption && activeTTSWordSpans.length > 0 && activeTTSWordIdx >= 0) {
    const spokenWords = activeTTSWordSpans.slice(0, activeTTSWordIdx + 1).map(s => s.textContent).join(' ');
    if (spokenWords.length > 0) {
      if (messages.length > 0) {
        const lastAi = messages[messages.length - 1];
        if (lastAi && lastAi.role === 'assistant') {
          lastAi.content = spokenWords + ' ... [User interrupted AI response here]';
        }
      }
      if (activeTTSMsgRow) {
        const bubble = activeTTSMsgRow.querySelector('.bubble');
        if (bubble) {
          bubble.innerHTML = formatContent(spokenWords + ' ...');
        }
      }
    }
  }

  if (currentAudioSource) {
    try { currentAudioSource.stop(); } catch (_) {}
    currentAudioSource = null;
  }
  if (ttsAnimFrame) {
    cancelAnimationFrame(ttsAnimFrame);
    ttsAnimFrame = null;
  }
  activeTTSWordSpans = [];
  activeTTSWordIdx = -1;
  activeTTSMsgRow = null;
  window.speechSynthesis?.cancel();
}

async function fetchTTSBuffer(text) {
  try {
    const res = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    });
    if (!res.ok) return null;
    const arrayBuffer = await res.arrayBuffer();
    if (!arrayBuffer || arrayBuffer.byteLength === 0) return null;
    return await audioCtx.decodeAudioData(arrayBuffer);
  } catch (err) {
    return null;
  }
}

async function _speakReply(raw, msgRow, onDone) {
  stopCurrentTTSAudio(false);
  ttsQueueCancelled = false;
  const clean = _sanitiseForTTS(raw);
  if (!clean) { onDone?.(); return; }

  // Split into sentence chunks for ultra-fast initial playback start (~200ms instead of 3500ms)
  const sentences = clean.split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(s => s.length > 0);
  if (sentences.length === 0) { onDone?.(); return; }

  const wordSpans = _wrapBubbleWords(msgRow);
  activeTTSMsgRow = msgRow;
  activeTTSWordSpans = wordSpans;
  activeTTSWordIdx = 0;

  try {
    if (!audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (AC) audioCtx = new AC();
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      await audioCtx.resume();
    }

    // Pre-fetch sentence 1 first for immediate start
    let nextBufferPromise = fetchTTSBuffer(sentences[0]);
    let globalWordIdx = 0;

    for (let i = 0; i < sentences.length; i++) {
      if (ttsQueueCancelled || !voiceActive) break;

      const audioBuffer = await nextBufferPromise;
      // Start fetching the NEXT sentence in parallel while current sentence plays!
      if (i + 1 < sentences.length) {
        nextBufferPromise = fetchTTSBuffer(sentences[i + 1]);
      }

      if (!audioBuffer || ttsQueueCancelled) continue;

      const source = audioCtx.createBufferSource();
      
      // Volume Ducking: Set gain to 0.8 to optimize for speaker echo cancellation
      const gainNode = audioCtx.createGain();
      gainNode.gain.value = 0.8;
      source.buffer = audioBuffer;
      source.connect(gainNode);
      gainNode.connect(audioCtx.destination);

      currentAudioSource = source;

      const chunkWords = sentences[i].split(/\s+/).filter(w => w.length > 0).length;
      const duration = audioBuffer.duration;
      const startTime = audioCtx.currentTime;
      const startWordIdx = globalWordIdx;

      let lastIdx = -1;
      const updateHighlight = () => {
        if (!currentAudioSource || ttsQueueCancelled) return;
        const elapsed = audioCtx.currentTime - startTime;
        const progress = Math.min(1, elapsed / duration);
        const currentIdx = startWordIdx + Math.floor(progress * chunkWords);
        activeTTSWordIdx = currentIdx;
        if (currentIdx !== lastIdx && currentIdx < wordSpans.length) {
          if (lastIdx >= 0 && wordSpans[lastIdx]) wordSpans[lastIdx].classList.remove('tts-highlight');
          if (wordSpans[currentIdx]) {
            wordSpans[currentIdx].classList.add('tts-highlight');
            wordSpans[currentIdx].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
          }
          lastIdx = currentIdx;
        }
        if (progress < 1) {
          ttsAnimFrame = requestAnimationFrame(updateHighlight);
        }
      };

      const sentencePromise = new Promise((resolve) => {
        source.onended = () => {
          if (lastIdx >= 0 && wordSpans[lastIdx]) wordSpans[lastIdx].classList.remove('tts-highlight');
          currentAudioSource = null;
          if (ttsAnimFrame) cancelAnimationFrame(ttsAnimFrame);
          globalWordIdx += chunkWords;
          resolve();
        };
      });

      if (chunkWords > 0) updateHighlight();
      source.start(0);

      await sentencePromise;
    }

    wordSpans.forEach(s => s.classList.remove('tts-highlight'));
    onDone?.();

  } catch (err) {
    console.error('Edge-TTS playback error:', err);
    wordSpans?.forEach(s => s.classList.remove('tts-highlight'));
    onDone?.();
  }
}

function stopVoiceSession() {
  clearTimeout(silenceTimer); silenceTimer = null;
  voiceActive = false;
  stopCurrentTTSAudio();
  try { voiceRecog?.stop(); } catch (_) {}
  closeMicStream();
  if (audioCtx && audioCtx.state !== 'closed') {
    try { audioCtx.close(); } catch (_) {}
    audioCtx = null;
  }
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
      if (data.chat_info && data.chat_info.is_developer_session) {
        // Do nothing with the model, preserve the user's current selection
      } else {
        // Do nothing with the model, preserve the user's current selection
      }
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
      const res  = await fetch(`/api/chat/history/${chatId}/delete`, { 
        method: 'POST', 
        headers: { 'X-CSRFToken': getCsrfToken() },
        credentials: 'include' 
      });
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

function hexToRgba(hex, alpha) {
  hex = hex.replace('#', '');
  if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function hexToRgb(hex) {
  hex = hex.replace('#', '');
  if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
  return {
    r: parseInt(hex.substring(0, 2), 16),
    g: parseInt(hex.substring(2, 4), 16),
    b: parseInt(hex.substring(4, 6), 16)
  };
}

function drawBall() {
  const canvas = $(typeof activeVoiceCanvasId !== "undefined" ? activeVoiceCanvasId : "voiceCanvas"); if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height, cx = W/2, cy = H/2;
  ctx.clearRect(0,0,W,H); ballPhase += 0.018;

  // Retrieve theme variables dynamically
  const styles = getComputedStyle(document.documentElement);
  const accent = styles.getPropertyValue('--accent').trim() || '#9CB080';
  const accent2 = styles.getPropertyValue('--accent2').trim() || '#607456';
  const bg = styles.getPropertyValue('--bg').trim() || '#0a0a0b';
  const isDark = document.documentElement.getAttribute('data-theme') !== 'light';

  let volume = 0;
  if (analyser && isListening && mediaStream) {
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
  if (isListening && analyser && mediaStream) {
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
  halo.addColorStop(0,hexToRgba(accent, glowA));
  halo.addColorStop(0.45,hexToRgba(accent2, glowA*0.40));
  halo.addColorStop(1,'rgba(0,0,0,0)');
  ctx.beginPath(); ctx.arc(cx,cy,outerR*1.40,0,Math.PI*2); ctx.fillStyle=halo; ctx.fill();
  ctx.beginPath(); ctx.arc(cx,cy,outerR,0,Math.PI*2);
  ctx.strokeStyle=hexToRgba(accent, 0.20+sv*0.28); ctx.lineWidth=5; ctx.stroke();
  ctx.beginPath(); ctx.arc(cx,cy,outerR,0,Math.PI*2);
  ctx.strokeStyle=hexToRgba(accent2, 0.55+sv*0.38); ctx.lineWidth=1.5; ctx.stroke();
  const df = ctx.createRadialGradient(cx-outerR*0.22,cy-outerR*0.22,0,cx,cy,outerR);
  if (isDark) {
    df.addColorStop(0, '#1d273a');
    df.addColorStop(0.58, '#111827');
    df.addColorStop(1, bg);
  } else {
    df.addColorStop(0, '#f4f6f1');
    df.addColorStop(0.58, '#e2e7dc');
    df.addColorStop(1, '#cdd5c5');
  }
  ctx.beginPath(); ctx.arc(cx,cy,outerR-1,0,Math.PI*2); ctx.fillStyle=df; ctx.fill();
  
  const cAccent2 = hexToRgb(accent2);
  const cAccent = hexToRgb(accent);
  for (let i = 0; i < BAR_COUNT; i++) {
    const angle = (i/BAR_COUNT)*Math.PI*2-Math.PI/2;
    const barH  = drawBall._bars[i]*MAX_BAR_H;
    const r1=outerR-1, r2=outerR-barH-1.5;
    const x1=cx+Math.cos(angle)*r1, y1=cy+Math.sin(angle)*r1;
    const x2=cx+Math.cos(angle)*r2, y2=cy+Math.sin(angle)*r2;
    const intensity = Math.min(1,drawBall._bars[i]*2.4);
    const r = Math.round(cAccent2.r + (cAccent.r - cAccent2.r) * intensity);
    const g = Math.round(cAccent2.g + (cAccent.g - cAccent2.g) * intensity);
    const b = Math.round(cAccent2.b + (cAccent.b - cAccent2.b) * intensity);
    const alpha = 0.30+intensity*0.70;
    ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2);
    ctx.strokeStyle=`rgba(${r},${g},${b},${alpha*0.28})`; ctx.lineWidth=4.5; ctx.lineCap='round'; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2);
    ctx.strokeStyle=`rgba(${r},${g},${b},${alpha})`; ctx.lineWidth=1.6; ctx.stroke();
    if (intensity > 0.5) {
      ctx.beginPath(); ctx.arc(x2,y2,1.8,0,Math.PI*2);
      const peakR = Math.round(r + (255 - r) * 0.5);
      const peakG = Math.round(g + (255 - g) * 0.5);
      const peakB = Math.round(b + (255 - b) * 0.5);
      ctx.fillStyle=`rgba(${peakR},${peakG},${peakB},${(intensity-0.5)*2*alpha})`; ctx.fill();
    }
  }
  const innerZoneR = outerR-MAX_BAR_H-10;
  const coreA = isListening ? 0.18+sv*0.35 : 0.08;
  const core = ctx.createRadialGradient(cx,cy,0,cx,cy,innerZoneR*0.90);
  core.addColorStop(0,hexToRgba(accent, coreA)); 
  core.addColorStop(0.5,hexToRgba(accent2, coreA*0.45)); 
  core.addColorStop(1,'rgba(0,0,0,0)');
  ctx.save(); ctx.beginPath(); ctx.arc(cx,cy,innerZoneR,0,Math.PI*2); ctx.clip();
  ctx.beginPath(); ctx.arc(cx,cy,innerZoneR*0.90,0,Math.PI*2); ctx.fillStyle=core; ctx.fill(); ctx.restore();
  const sX=cx-outerR*0.26, sY=cy-outerR*0.28;
  const spec = ctx.createRadialGradient(sX,sY,0,sX,sY,outerR*0.38);
  spec.addColorStop(0,'rgba(255,255,255,0.55)'); 
  spec.addColorStop(0.28,hexToRgba(accent, 0.18)); 
  spec.addColorStop(1,'rgba(255,255,255,0)');
  ctx.save(); ctx.beginPath(); ctx.arc(cx,cy,outerR-1,0,Math.PI*2); ctx.clip();
  ctx.beginPath(); ctx.arc(sX,sY,outerR*0.38,0,Math.PI*2); ctx.fillStyle=spec; ctx.fill(); ctx.restore();
  drawBall._waves = drawBall._waves || []; drawBall._lastSv = drawBall._lastSv || 0;
  if (isListening && sv-drawBall._lastSv > 0.15 && sv > 0.30) drawBall._waves.push({ r:outerR*1.04, life:1.0 });
  drawBall._lastSv = sv;
  for (let w = drawBall._waves.length-1; w >= 0; w--) {
    const wv = drawBall._waves[w]; wv.r += 2.5; wv.life -= 0.030;
    if (wv.life <= 0) { drawBall._waves.splice(w,1); continue; }
    ctx.beginPath(); ctx.arc(cx,cy,wv.r,0,Math.PI*2);
    ctx.strokeStyle=hexToRgba(accent, wv.life*0.25); ctx.lineWidth=wv.life*5; ctx.stroke();
    ctx.beginPath(); ctx.arc(cx,cy,wv.r,0,Math.PI*2);
    ctx.strokeStyle=hexToRgba(accent2, wv.life*0.55); ctx.lineWidth=wv.life*1.2; ctx.stroke();
  }
  animFrame = requestAnimationFrame(drawBall);
}

/* ════════ INIT ════════ */
if (window.speechSynthesis) window.speechSynthesis.getVoices();
setTimeout(() => { initBallCanvas(); _syncMuteBtn(); toggleSendBtn(); }, 100);
document.addEventListener('DOMContentLoaded', checkSession);
console.log('✅ Heros loaded.');

/* ════════ DEVELOPER MODE ════════ */
let isDeveloperMode = false;
let devConfig = { provider: 'openrouter', model: '', saveHistory: true };

const devModels = {
  openrouter: [
    'nvidia/nemotron-3-nano-30b-a3b:free',
    'google/gemma-4-26b-a4b-it:free',
    'meta-llama/llama-3.3-70b-instruct:free',
    'google/gemma-4-31b-it:free',
    'nvidia/nemotron-nano-9b-v2:free',
    'meta-llama/llama-3.2-3b-instruct:free',
    'meta-llama/llama-3.3-70b:free',
    'nvidia/nemotron-3-super-120b-a12b:free',
    'custom'
  ],
  groq: [
    'llama-3.1-8b-instant',
    'openai/gpt-oss-120b',
    'openai/gpt-oss-20b',
    'llama-3.3-70b-versatile',
    'qwen/qwen3.6-27b',
    'qwen/qwen3-32b',
    'custom'
  ],
  gemini: [
    'gemini-3.5-flash',
    'gemini-3.1-flash-lite',
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite',
    'custom'
  ]
};

function openDeveloperModal() {
  developerModal.style.display = 'flex';
  onDevProviderChange(); // init dropdown
}

function closeDeveloperModal() {
  developerModal.style.display = 'none';
  if (!isDeveloperMode) {
    const select = modelSelect;
    if (select) select.value = currentModel || 'Baymax';
  }
}

function onDevProviderChange() {
  const provider = devProviderSelect.value;
  const modelSelect = devModelSelect;
  modelSelect.innerHTML = '';
  devModels[provider].forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m === 'custom' ? 'Custom Input...' : m;
    modelSelect.appendChild(opt);
  });
  onDevModelChange();
}

function onDevModelChange() {
  const model = devModelSelect.value;
  const customInput = devCustomModelInput;
  if (model === 'custom') {
    customInput.style.display = 'block';
  } else {
    customInput.style.display = 'none';
  }
}

function startDeveloperSession() {
  const provider = $('devProviderSelect').value;
  const modelSelectVal = $('devModelSelect').value;
  const customModel = $('devCustomModelInput').value.trim();

  const finalModel = modelSelectVal === 'custom' ? customModel : modelSelectVal;
  if (!finalModel) {
    showNotification('Please enter a custom model name', 'error');
    return;
  }

  if (provider === 'groq' && !hasGroqKey) {
    showNotification('Groq API Key is required. Please set it in profile / settings / api key.', 'error');
    return;
  }
  if (provider === 'openrouter' && !hasExistingApiKeys) {
    showNotification('OpenRouter API Key is required. Please set it in profile / settings / api key.', 'error');
    return;
  }

  isDeveloperMode = true;
  devConfig = {
    provider: provider,
    model: finalModel
  };

  isFastMode = false;
  const fastBtn = $('fastModeBtn');
  if (fastBtn) { fastBtn.classList.remove('active'); fastBtn.style.display = 'none'; }
  const toggleBtn = $('devSidebarToggleBtn');
  if (toggleBtn) toggleBtn.style.display = '';
  
  const devSidebar = $('developerSidebar');
  if (devSidebar) devSidebar.style.display = 'none'; // Default hidden as requested

  const sideProv = $('sideDevProviderSelect');
  if (sideProv) {
    sideProv.value = provider;
    onSideDevProviderChange();
    const sideModel = $('sideDevModelSelect');
    if (modelSelectVal === 'custom') {
      sideModel.value = 'custom';
      onSideDevModelChange();
      $('sideDevCustomModelInput').value = customModel;
    } else {
      sideModel.value = finalModel;
      onSideDevModelChange();
    }
  }

  $('developerModal').style.display = 'none';
  
  newChat();
  addSystemNote(`Started Developer Session (${provider.toUpperCase()}: ${finalModel})`);
}

function onSideDevProviderChange() {
  const provider = $('sideDevProviderSelect').value;
  const modelSelect = $('sideDevModelSelect');
  if (!modelSelect) return;
  modelSelect.innerHTML = '';
  devModels[provider].forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m === 'custom' ? 'Custom Input...' : m;
    modelSelect.appendChild(opt);
  });
  onSideDevModelChange();
}

function onSideDevModelChange() {
  const model = $('sideDevModelSelect').value;
  const customInput = $('sideDevCustomModelInput');
  if (!customInput) return;
  if (model === 'custom') {
    customInput.style.display = 'block';
  } else {
    customInput.style.display = 'none';
  }
}

function applySidebarDevConfig() {
  const provider = $('sideDevProviderSelect').value;
  const modelSelectVal = $('sideDevModelSelect').value;
  const customModel = $('sideDevCustomModelInput').value.trim();
  const finalModel = modelSelectVal === 'custom' ? customModel : modelSelectVal;
  if (!finalModel) {
    showNotification('Please enter a custom model name', 'error');
    return;
  }
  
  devConfig = {
    provider: provider,
    model: finalModel
  };
  addSystemNote(`Updated Developer Config (${provider.toUpperCase()}: ${finalModel})`);
  showNotification('Developer configuration applied', 'success');
}

function toggleDevSidebar() {
  const devSidebar = $('developerSidebar');
  if (devSidebar) {
    devSidebar.style.display = devSidebar.style.display === 'none' ? 'block' : 'none';
  }
}

