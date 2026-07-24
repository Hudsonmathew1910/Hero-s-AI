from django_ratelimit.decorators import ratelimit
"""
views.py — Heros Django views
backend/view.py

Changes from original:
  • Structured logging via Python's `logging` module (replaces bare print calls)
  • Temporary-chat support:
      - Frontend sends `temporary_chat: true` in the JSON body
      - A fresh session is created but chat turns are NEVER saved to the DB
      - Session ID is still returned so the client can keep the conversation
        alive for the current browser tab, but nothing persists server-side
  • Superuser-aware error handling in chat_api:
      - request.user_obj.is_superuser == True  → full traceback in response
      - False                                  → generic safe message
  • All existing endpoints and signatures are preserved
"""

import logging
import json
import re
import time
import requests
import traceback
from django.views.decorators.csrf import csrf_exempt

from concurrent.futures import ThreadPoolExecutor
from functools import wraps

from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.hashers import make_password, check_password
from django.conf import settings as django_settings
from django.utils import timezone

from django.db import connections, close_old_connections
from django.core.cache import cache
from .models import User, Api, Chat, Setting, ChatSession
from .encryption import encrypt_api_key, decrypt_api_key
from .hero_model import Baymax
from .Nlp import preprocess, resolve_mode
from .utils import safe_error_response

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------
logger = logging.getLogger("hero_ai.views")

# Reusable thread pool for async DB writes
_db_executor = ThreadPoolExecutor(max_workers=4)


# =============================================================================
# HELPERS (unchanged unless noted)
# =============================================================================

def db_thread_task(f):
    """
    Decorator to ensure database connections are properly managed in
    manually-created threads (like ThreadPoolExecutor).
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        close_old_connections()
        try:
            return f(*args, **kwargs)
        finally:
            close_old_connections()
    return wrapper


@db_thread_task
def get_user_api_keys(user):
    cache_key = f"api_keys_{user.user_id}"
    keys = cache.get(cache_key)
    if keys is not None:
        return keys['Gemini'], keys['OpenRouter'], keys['Groq']

    keys = {'Gemini': None, 'OpenRouter': None, 'Groq': None}
    for api in Api.objects.filter(user=user, model_name__in=keys):
        keys[api.model_name] = decrypt_api_key(api.api_key_encrypted)
        
    cache.set(cache_key, keys, timeout=3600 * 24)
    return keys['Gemini'], keys['OpenRouter'], keys['Groq']


@db_thread_task
def get_user_settings(user):
    cache_key = f"settings_{user.user_id}"
    sett = cache.get(cache_key)
    if sett is not None:
        return sett

    try:
        s = Setting.objects.get(user=user)
        sett = {
            'user_instruction':           s.user_instruction,
            'user_about_me':              s.user_about_me,
            'user_name':                  s.user_name,
            'enable_custom_instructions': getattr(s, 'enable_custom_instructions', True),
        }
    except Setting.DoesNotExist:
        sett = {
            'user_instruction':           None,
            'user_about_me':              None,
            'user_name':                  None,
            'enable_custom_instructions': True,
        }
    
    cache.set(cache_key, sett, timeout=3600 * 24)
    return sett


def get_session_history(session_id_str, user, limit=5):
    if not session_id_str:
        return []
    
    cache_key = f"history_{session_id_str}"
    cached_buffer = cache.get(cache_key)
    
    if cached_buffer is None:
        try:
            session = ChatSession.objects.get(session_id=session_id_str, user=user)
            # Load max base chunk for the buffer (5 turns = 10 messages)
            chats = list(session.messages.order_by('-timestamp')[:5])
            chats.reverse()
            cached_buffer = []
            for chat in chats:
                if not chat.input_text or not chat.output_text:
                    continue
                cached_buffer.append({"role": "user",      "content": chat.input_text.strip()})
                cached_buffer.append({"role": "assistant", "content": chat.output_text.strip()})
            
            cache.set(cache_key, cached_buffer, timeout=3600 * 2)
        except (ChatSession.DoesNotExist, Exception):
            cached_buffer = []

    # Slicing logic: limit is in turns, buffer holds messages (2 per turn)
    if limit:
        return cached_buffer[-(limit*2):] if len(cached_buffer) >= (limit*2) else cached_buffer
    return cached_buffer


@db_thread_task
def _get_or_create_session(user, session_id_str, message):
    """
    Return (session, is_new).
    For temporary chats the caller passes session_id_str=None so a fresh
    session is always created; the title is prefixed with '[Temp]' as a hint.
    """
    if session_id_str:
        try:
            return ChatSession.objects.get(session_id=session_id_str, user=user), False
        except ChatSession.DoesNotExist:
            pass
    title = message[:50] + ('...' if len(message) > 50 else '')
    return ChatSession.objects.create(user=user, title=title), True


@db_thread_task
def _save_chat_async(user, session, mode, model, message, reply, intent=None):
    """
    Persist a chat turn to the database.

    This function must NOT be called for temporary-chat turns — the caller
    (chat_api) is responsible for skipping the submit() call when
    `temporary_chat` is True.
    """
    try:
        task_type = intent if (mode == "text" and intent) else mode
        Chat.objects.create(
            user=user, session=session, task_type=task_type,
            model_used=model, input_text=message, output_text=reply,
        )
        session.updated_at = timezone.now()
        session.save(update_fields=['updated_at'])
    except Exception as e:
        logger.error("[BG SAVE ERROR] %s", e, exc_info=True)


# =============================================================================
# VALIDATION (unchanged)
# =============================================================================

def is_valid_email(email):
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))


def validate_password(password):
    if len(password) < 6:                      return "Password must be at least 6 characters"
    if not any(c.isupper() for c in password): return "Password must contain uppercase letter"
    if not any(c.isdigit() for c in password): return "Password must contain a number"
    return None


# =============================================================================
# DECORATORS (unchanged)
# =============================================================================

def login_required_json(f):
    @wraps(f)
    def wrapper(request, *args, **kwargs):
        uid = request.session.get('user_id')
        if not uid:
            session_key_raw = request.headers.get('X-Session-Id')
            if session_key_raw:
                from django.contrib.sessions.backends.db import SessionStore
                for sk in session_key_raw.split(','):
                    sk = sk.strip()
                    if not sk: continue
                    s = SessionStore(session_key=sk)
                    uid = s.get('user_id')
                    if uid:
                        request.session = s
                        break
        if not uid:
            return JsonResponse({"status": "fail", "message": "Authentication required"}, status=401)
        try:
            if not hasattr(request, '_cached_user'):
                request._cached_user = User.objects.get(user_id=uid)
            request.user_obj = request._cached_user
        except User.DoesNotExist:
            request.session.flush()
            return JsonResponse({"status": "fail", "message": "Session invalid"}, status=401)
        return f(request, *args, **kwargs)
    return wrapper

def optional_login_json(f):
    @wraps(f)
    def wrapper(request, *args, **kwargs):
        uid = request.session.get('user_id')
        if not uid:
            session_key_raw = request.headers.get('X-Session-Id', '')
            print(f"[DEBUG] {request.path} | X-Session-Id: {session_key_raw} | Cookie: {request.COOKIES.get('sessionid')}")
            if session_key_raw:
                from django.contrib.sessions.backends.db import SessionStore
                for sk in session_key_raw.split(','):
                    sk = sk.strip()
                    if not sk: continue
                    s = SessionStore(session_key=sk)
                    uid = s.get('user_id')
                    if uid:
                        request.session = s
                        break
        
        request.user_obj = None
        if uid:
            try:
                if not hasattr(request, '_cached_user'):
                    request._cached_user = User.objects.get(user_id=uid)
                request.user_obj = request._cached_user
            except User.DoesNotExist:
                pass
        return f(request, *args, **kwargs)
    return wrapper

def privacy_view(request):
    """
    Simple privacy policy view for the extension submission.
    """
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Privacy Policy - Heros</title>
        <link rel="icon" type="image/png" href="/static/images/Hero_ai.png">
    </head>
    <body style="font-family: sans-serif; max-width: 800px; margin: 40px auto; line-height: 1.6;">
        <h1>Privacy Policy</h1>
        <p><strong>Effective Date:</strong> July 2026</p>
        
        <h2>Zeno Extension</h2>
        <p>The Zeno browser extension acts as a mini AI assistant powered by Heros. To provide its core functionality, the extension requires access to certain data:</p>
        <ul>
            <li><strong>Website Content:</strong> When you use the "Ask Zeno Plus" right-click context menu, the text you have highlighted on the page is temporarily collected and sent to our servers to generate an AI response.</li>
            <li><strong>Personal Communications:</strong> Chat messages you type into the Zeno popup are transmitted to our servers to communicate with the AI.</li>
        </ul>
        <p>We do not collect any browsing history, location data, or keystrokes outside of the explicit text you submit to the AI.</p>
        
        <h2>Data Usage & Protection</h2>
        <p>Your data is strictly used to process and return AI responses. We do not sell your personal data or chat queries to third-party data brokers, nor do we use it for unrelated advertising purposes.</p>
        
        <p>If you have any questions, please contact us at support@hero-ai.com.</p>
    </body>
    </html>
    '''
    return HttpResponse(html)


def json_only(f):
    @wraps(f)
    def wrapper(request, *args, **kwargs):
        if request.method != "POST":
            return JsonResponse({"status": "fail", "message": "Method not allowed"}, status=405)
        try:
            request.json_data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"status": "fail", "message": "Invalid JSON"}, status=400)
        return f(request, *args, **kwargs)
    return wrapper


# =============================================================================
# VIEWS
# =============================================================================

def home(request):
    username = None
    user_id = request.session.get('user_id')
    if user_id:
        try:
            user = User.objects.get(user_id=user_id)
            settings = Setting.objects.get(user=user)
            if settings.user_name:
                username = settings.user_name
        except Exception:
            pass

    if not username:
        username = request.session.get('user_name')

    return render(request, 'home.html', {'username': username})


def landing(request):
    """Public landing / marketing page."""
    is_authenticated = bool(request.session.get('user_id'))
    return render(request, 'landing.html', {'is_authenticated': is_authenticated})


# ── Auth ──────────────────────────────────────────────────────────────────────
@csrf_exempt
@json_only
def signup_view(request):
    d = request.json_data
    name     = d.get('name', '').strip()
    email    = d.get('email', '').strip().lower()
    password = d.get('password', '')

    if not all([name, email, password]):
        return JsonResponse({"status": "fail", "message": "All fields required"}, status=400)
    if not is_valid_email(email):
        return JsonResponse({"status": "fail", "message": "Invalid email format"}, status=400)
    err = validate_password(password)
    if err:
        return JsonResponse({"status": "fail", "message": err}, status=400)
    if User.objects.filter(email=email).exists():
        return JsonResponse({"status": "fail", "message": "Email already registered"}, status=409)

    try:
        user = User.objects.create(
            name=name, email=email, password_hash=make_password(password)
        )
        Setting.objects.create(user=user)
        request.session.update({
            'user_id': str(user.user_id),
            'user_email': user.email,
            'user_name': user.name,
        })
        request.session.set_expiry(1209600)
        return JsonResponse({
            "status": "success",
            "message": "Account created",
            "user": {
                "user_id":      str(user.user_id),
                "name":         user.name,
                "email":        user.email,
                "has_api_keys": False,
                "has_groq_key": False,
            },
        })
    except Exception as e:
        return safe_error_response(request, logger, "Signup", e)
@csrf_exempt
@json_only
def login_view(request):
    d        = request.json_data
    email    = d.get('email', '').strip().lower()
    password = d.get('password', '')

    if not all([email, password]):
        return JsonResponse({"status": "fail", "message": "Email and password required"}, status=400)
    if not is_valid_email(email):
        return JsonResponse({"status": "fail", "message": "Invalid email format"}, status=400)

    try:
        try:
            user = User.objects.get(email=email)
            if not check_password(password, user.password_hash):
                return JsonResponse({"status": "fail", "message": "Invalid credentials"}, status=401)
        except User.DoesNotExist:
            return JsonResponse({"status": "fail", "message": "Invalid credentials"}, status=401)

        request.session.update({
            'user_id':    str(user.user_id),
            'user_email': user.email,
            'user_name':  user.name,
        })
        request.session.set_expiry(1209600)
        has_keys = Api.objects.filter(user=user, model_name__in=['Gemini', 'OpenRouter']).exists()
        has_groq = Api.objects.filter(user=user, model_name='Groq').exists()
        return JsonResponse({
            "status": "success",
            "message": "Login successful",
            "user": {
                "user_id":      str(user.user_id),
                "name":         user.name,
                "email":        user.email,
                "has_api_keys": has_keys,
                "has_groq_key": has_groq,
            },
        })
    except Exception as e:
        return safe_error_response(request, logger, "Login", e)
@csrf_exempt
def logout_view(request):
    if request.method != "POST":
        return JsonResponse({"status": "fail", "message": "Method not allowed"}, status=405)
    request.session.flush()
    return JsonResponse({"status": "success", "message": "Logged out"})
@csrf_exempt
@optional_login_json
def check_session(request):
    uid = request.session.get('user_id')
    if not getattr(request, 'user_obj', None):
        return JsonResponse({"status": "fail", "logged_in": False, "authenticated": False})
    
    try:
        user = request.user_obj
        has_keys = Api.objects.filter(user=user, model_name__in=['Gemini', 'OpenRouter']).exists()
        has_groq = Api.objects.filter(user=user, model_name='Groq').exists()
        return JsonResponse({
            "status":    "success",
            "logged_in": True,
            "authenticated": True,
            "user": {
                "user_id":      str(user.user_id),
                "name":         user.name,
                "email":        user.email,
                "has_api_keys": has_keys,
                "has_groq_key": has_groq,
            },
        })
    except Exception as e:
        return JsonResponse({"status": "fail", "logged_in": False, "authenticated": False})
# ── Google OAuth ──────────────────────────────────────────────────────────────

def google_login(request):
    flow = request.GET.get('flow', 'signin')
    next_url = request.GET.get('next', '/')
    request.session['oauth_flow'] = flow
    request.session['oauth_next'] = next_url

    redirect_uri = f"{django_settings.SITE_URL}/auth/google/callback"
    logger.info("Initiating Google Login: flow=%s, next=%s", flow, next_url)
    return redirect(
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={django_settings.GOOGLE_CLIENT_ID}&redirect_uri={redirect_uri}&"
        f"response_type=code&scope=openid%20email%20profile&access_type=offline"
    )
def google_callback(request):
    code = request.GET.get('code')
    if not code:
        return render(request, 'home.html', {'error': 'Google login failed'})
    try:
        redirect_uri = f"{django_settings.SITE_URL}/auth/google/callback"
        token = requests.post('https://oauth2.googleapis.com/token', data={
            'code':          code,
            'client_id':     django_settings.GOOGLE_CLIENT_ID,
            'client_secret': django_settings.GOOGLE_CLIENT_SECRET,
            'redirect_uri':  redirect_uri,
            'grant_type':    'authorization_code',
        }).json()

        access_token = token.get('access_token')
        if not access_token:
            return render(request, 'home.html', {'error': 'Failed to authenticate'})

        info = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'},
        ).json()
        email     = info.get('email')
        name      = info.get('name', email.split('@')[0])
        google_id = info.get('id')

        flow = request.session.get('oauth_flow', 'signin')
        next_url = request.session.get('oauth_next', '/')

        try:
            user = User.objects.get(email=email)
            # Email exists
            if not user.google_id:
                user.google_id = google_id
                user.save()
            
            # Whether signin or signup, if user exists, just log them in directly
            request.session.update({
                'user_id':    str(user.user_id),
                'user_email': user.email,
                'user_name':  user.name,
            })
            request.session.set_expiry(1209600)
            
            # Clean up session
            if 'oauth_next' in request.session: del request.session['oauth_next']
            
            return redirect(next_url)
        except User.DoesNotExist:
            # Always fall back to account creation if user doesn't exist,
            # so both 'signin' and 'signup' flows lead to a seamless experience.
            user = User.objects.create(
                email=email,
                name=name,
                google_id=google_id,
                password_hash=''  # No password yet
            )
            Setting.objects.create(user=user)

            request.session['setup_user_id'] = str(user.user_id)
            
            # Preserve next_url for the final step
            return redirect(f'/?action=google_setup&next={next_url}' if next_url != '/' else '/?action=google_setup')

    except Exception as e:
        logger.exception("Google OAuth callback error")
        return redirect('/?error=Login+failed')
@csrf_exempt
@json_only
def complete_google_signup(request):
    setup_user_id = request.session.get('setup_user_id')
    if not setup_user_id:
        return JsonResponse({"status": "fail", "message": "Invalid session"}, status=400)
        
    d = request.json_data
    username = d.get('username', '').strip()
    password = d.get('password', '')
    
    if not username or not password:
        return JsonResponse({"status": "fail", "message": "Username and password required"}, status=400)
    
    err = validate_password(password)
    if err:
        return JsonResponse({"status": "fail", "message": err}, status=400)
        
    try:
        user = User.objects.get(user_id=setup_user_id)
        user.name = username
        user.password_hash = make_password(password)
        user.save()
        
        # Mark setup as complete and log in
        del request.session['setup_user_id']
        request.session.update({
            'user_id':    str(user.user_id),
            'user_email': user.email,
            'user_name':  user.name,
        })
        request.session.set_expiry(1209600)
        
        # Get next URL from session if available
        next_url = request.session.get('oauth_next', '/')
        if 'oauth_next' in request.session: del request.session['oauth_next']
        
        return JsonResponse({
            "status": "success",
            "message": "Account setup complete",
            "redirect_url": next_url,
            "user": {
                "user_id":      str(user.user_id),
                "name":         user.name,
                "email":        user.email,
                "has_api_keys": False,
                "has_groq_key": False,
            },
        })
    except User.DoesNotExist:
        return JsonResponse({"status": "fail", "message": "User not found"}, status=404)
    except Exception as e:
        return safe_error_response(request, logger, "complete_google_signup", e)


# ── API Keys ──────────────────────────────────────────────────────────────────
@csrf_exempt
@login_required_json
@json_only
def save_api_keys(request):
    d          = request.json_data
    gemini     = d.get('gemini', '').strip()
    openrouter = d.get('openrouter', '').strip()
    groq       = d.get('groq', '').strip()
    huggingface = d.get('huggingface', '').strip()

    if not any([gemini, openrouter, groq, huggingface]):
        return JsonResponse({"status": "fail", "message": "Please enter at least one API key"}, status=400)
    try:
        for name, val in [('Gemini', gemini), ('OpenRouter', openrouter)]:
            if val:
                Api.objects.update_or_create(
                    user=request.user_obj, model_name=name,
                    defaults={'api_key_encrypted': encrypt_api_key(val), 'is_mandatory': True},
                )
        if groq:
            Api.objects.update_or_create(
                user=request.user_obj, model_name='Groq',
                defaults={'api_key_encrypted': encrypt_api_key(groq), 'is_mandatory': False},
            )
        elif 'groq' in d:
            Api.objects.filter(user=request.user_obj, model_name='Groq').delete()
            
        if huggingface:
            Api.objects.update_or_create(
                user=request.user_obj, model_name='HuggingFace',
                defaults={'api_key_encrypted': encrypt_api_key(huggingface), 'is_mandatory': False},
            )
        elif 'huggingface' in d:
            Api.objects.filter(user=request.user_obj, model_name='HuggingFace').delete()
            
        cache.delete(f"api_keys_{request.user_obj.user_id}")
        
        return JsonResponse({"status": "success", "message": "API keys saved"})
    except Exception as e:
        return safe_error_response(request, logger, "save_api_keys", e)
@login_required_json
def check_api_keys(request):
    keys = {
        n: Api.objects.filter(user=request.user_obj, model_name=n).exists()
        for n in ['Gemini', 'OpenRouter', 'Groq', 'HuggingFace']
    }
    return JsonResponse({
        "status":      "success",
        "has_api_keys": keys['Gemini'] or keys['OpenRouter'],
        "has_groq_key": keys['Groq'],
        "has_hf_key":   keys['HuggingFace'],
        "keys":         {k.lower(): v for k, v in keys.items()},
    })


# ── Chat ──────────────────────────────────────────────────────────────────────
@csrf_exempt
@optional_login_json
@json_only
def chat_api(request):
    """
    Main chat endpoint.

    Additions vs original:
      • Reads `temporary_chat` (bool) from the request body.
        - True  → history is NOT loaded from DB, reply is NOT saved to DB.
        - False → normal behaviour (load history, save reply).
      • Passes `is_superuser` to Baymax so error verbosity matches user role.
      • Uses logger instead of print() for all diagnostic output.
      • Wraps the entire handler body in a structured try/except that returns
        full details to superusers and a safe message to everyone else.
    """
    t0 = time.time()
    d  = request.json_data

    raw_message    = d.get('message', '').strip()
    model          = d.get('model', 'Baymax')
    mode           = d.get('mode', 'text')
    session_id_str = d.get('session_id')
    send_history   = d.get('send_history', [])

    # ── NEW: read temporary-chat flag from the request ────────────────────────
    temporary_chat: bool = bool(d.get('temporary_chat', False))
    is_fast: bool = bool(d.get('is_fast', False))
    
    is_developer = bool(d.get('is_developer', False))
    dev_provider = d.get('dev_provider', '')
    dev_model_name = d.get('dev_model_name', '')

    # ── Determine whether this user has superuser privileges ──────────────────
    # A user is a superuser if their is_superuser flag is set to True.
    is_superuser: bool = getattr(request.user_obj, 'is_superuser', False) if getattr(request, 'user_obj', None) else False
    
    if not getattr(request, 'user_obj', None):
        temporary_chat = True
        
        if mode == 'zeno_plus':
            return JsonResponse({
                "status": "success",
                "reply": "⚠️ **Login Required**\n\nPlease log in to your Heros account and configure your Groq API key to use Zeno Plus.",
                "session_id": session_id_str,
                "is_new_chat": False,
                "temporary": True
            })
            
        if model not in ['Halo', 'Baymax']:
            model = 'Halo'

    if mode.startswith('zeno_'):
        model = 'Baymax'

    files = d.get('files', [])
    if not raw_message and not files:
        return JsonResponse({"status": "fail", "message": "Message required"}, status=400)
        
    if not raw_message and files:
        raw_message = "Read and wait for user Query about the file"


    try:
        # ── Developer Bypass ──────────────────────────────────────────────────
        if is_developer:
            from .hero_model import Developer
            dev_client = Developer(request.user_obj, dev_provider, dev_model_name)
            
            clean_history = []
            if isinstance(send_history, list):
                for msg in send_history:
                    if isinstance(msg, dict) and "role" in msg and "content" in msg:
                        clean_history.append({"role": msg["role"], "content": msg["content"]})
            
            # Limit history to match Baymax's standard text behavior (10 messages = 5 turns)
            clean_history = clean_history[-10:]
            
            system_prompt = dev_client.build_system_prompt(mode)
            messages_payload = [{"role": "system", "content": system_prompt}] + clean_history
            messages_payload.append({"role": "user", "content": raw_message})
            
            t0 = time.time()
            result = dev_client.generate(messages_payload)
            time_taken = round(time.time() - t0, 2)
            
            reply = result.get('reply') or ""
            status_code = result.get('status_code', 500)
            error_msg = result.get('error')
            
            is_new_session = False
            if not temporary_chat and reply and not error_msg:
                chat_session, is_new_session = _get_or_create_session(request.user_obj, session_id_str, raw_message)
                
                active_buffer = cache.get(f"history_{chat_session.session_id}")
                if active_buffer is None:
                    active_buffer = list(send_history)
                
                active_buffer.append({"role": "user", "content": raw_message.strip()})
                active_buffer.append({"role": "assistant", "content": reply.strip()})
                active_buffer = active_buffer[-10:]
                cache.set(f"history_{chat_session.session_id}", active_buffer, timeout=3600 * 2)
                
                # Force mode to developer for the database record
                _save_chat_async(request.user_obj, chat_session, 'developer', dev_model_name, raw_message, reply)
                
            return JsonResponse({
                "status": "success",
                "reply": reply,
                "status_code": status_code,
                "error": error_msg,
                "dev_model": dev_model_name,
                "time_taken": time_taken,
                "session_id": str(chat_session.session_id) if not temporary_chat and 'chat_session' in locals() else session_id_str,
                "is_new_chat": is_new_session,
                "temporary": temporary_chat,
            })

        # ── NLP pre-processing ────────────────────────────────────────────────
        if mode in ['coding', 'websearch', 'Voice Chat', 'voice_message', 'zeno_shadow', 'search_code', 'search_file', 'code_file', 'search_code_file', 'voice_search', 'voice_search_file', 'voice_code', 'voice_code_file', 'voice_search_code', 'voice_search_code_file']:
            nlp_result = {"clean_text": raw_message, "intent": "direct", "metadata": {}}
        else:
            nlp_result = preprocess(raw_message, source=mode)
            
        message    = nlp_result["clean_text"] or raw_message
        mode       = resolve_mode(nlp_result, mode)
        nlp_intent = nlp_result["intent"]

        if nlp_intent == "play_song":
            try:
                from ytmusicapi import YTMusic
                
                # Extract the query
                query = re.sub(r'^(?:hey\s+zuno\s+|zuno\s+)?(?:play|listen\s+to|search\s+artist)\s+', '', raw_message, flags=re.IGNORECASE).strip()
                if not query:
                    query = raw_message

                ytmusic = YTMusic()
                results = ytmusic.search(query, filter="songs")
                
                if results and len(results) > 0:
                    video_id = results[0].get("videoId")
                    if video_id:
                        return JsonResponse({
                            "status": "play_extension",
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "intent": "play_song",
                            "message": f"Playing '{results[0].get('title', query)}' on YouTube."
                        })
                
                return JsonResponse({
                    "status": "play_extension",
                    "url": f"https://www.youtube.com/results?search_query={query}+official+audio",
                    "intent": "play_song",
                    "message": f"Playing '{query}' on YouTube."
                })
            except Exception as e:
                logger.error(f"Music intent failure in chat_api: {e}")
                # If ytmusicapi fails, fallback to standard LLM response
                pass

        logger.info(
            "chat_api | user=%s | mode=%s | intent=%s | temporary=%s | tokens≈%s",
            request.user_obj.user_id if request.user_obj else "Anonymous", mode, nlp_intent,
            temporary_chat, nlp_result["metadata"].get("token_estimate"),
        )

        # ── Parallel DB lookups ───────────────────────────────────────────────
        if getattr(request, 'user_obj', None):
            with ThreadPoolExecutor(max_workers=4) as pool:
                f_keys = pool.submit(get_user_api_keys,      request.user_obj)
                f_sett = pool.submit(get_user_settings,      request.user_obj)
                f_sess = pool.submit(
                    _get_or_create_session,
                    request.user_obj,
                    None if temporary_chat else session_id_str,
                    message,
                )

                gemini_key, openrouter_key, groq_key = f_keys.result()
                user_settings                        = f_sett.result()
                chat_session, is_new_session         = f_sess.result()
        else:
            gemini_key, openrouter_key, groq_key = None, None, None
            user_settings = {}
            chat_session, is_new_session = None, True

        if mode == 'zeno_plus' and not groq_key:
            return JsonResponse({
                "status": "success",
                "reply": "⚠️ **Groq API Key Required**\n\nPlease configure your Groq API Key in account settings to use Zeno Plus.",
                "session_id": session_id_str,
                "is_new_chat": False,
                "temporary": True
            })

        # ── Session history ───────────────────────────────────────────────────
        if temporary_chat:
            # Temporary chats have no persisted history — use whatever the
            # frontend sent in this request (in-memory context only).
            chat_history = send_history
        else:
            # Determine base history turn limit (1 turn = 2 messages: User + AI)
            # Base limits doubled (x2): Text = 6 turns (12 msgs), Coding/Voice = 4 turns (8 msgs)
            history_limits = {
                'text':                   6,
                'coding':                 4,
                'Voice Chat':             4,
                'voice_message':          4,
                'file_handle':            2,
                'websearch':              4,
                'zeno_eco':               4,
                'zeno_plus':              8,
                'zeno_voice':             4,
                'zeno_shadow':            0,
                'voice_search':           4,
                'voice_search_file':      2,
                'voice_code':             4,
                'voice_code_file':        2,
                'voice_search_code':      4,
                'voice_search_code_file': 2,
            }
            base_turn_limit = history_limits.get(mode, 4)

            # Check for remember_history setting or file reference NLP detection
            remember_hist = d.get('remember_history', False)
            if not remember_hist and request.user_obj:
                try:
                    user_setting = Setting.objects.get(user=request.user_obj)
                    remember_hist = user_setting.remember_history
                except Exception:
                    pass

            file_keywords = r'\b(file|document|pdf|attachment|uploaded|textfile|image|csv|codefile|datafile|file_handle|attached)\b'
            has_file_ref = bool(re.search(file_keywords, raw_message, re.IGNORECASE))
            if not has_file_ref and send_history:
                for msg in send_history:
                    c = str(msg.get('content', ''))
                    m = str(msg.get('mode', ''))
                    if msg.get('files') or 'file' in m.lower() or re.search(file_keywords, c, re.IGNORECASE):
                        has_file_ref = True
                        break

            if remember_hist or has_file_ref:
                # x3 history length multiplier if remember_history enabled or referencing a file
                turn_limit = int(base_turn_limit * 3)
            else:
                # Default x2 base turn limit
                turn_limit = base_turn_limit

            if send_history and isinstance(send_history, list):
                max_msgs = turn_limit * 2
                chat_history = send_history[-max_msgs:] if len(send_history) > max_msgs else send_history
            else:
                chat_history = get_session_history(session_id_str, request.user_obj, turn_limit)

        db_lookup_time = time.time() - t0
        logger.debug("DB lookup: %.2fs", db_lookup_time)

        try:
            if model == 'Halo':
                from .usage_tracker import get_halo_usage, increment_halo_usage, HALO_MAX_LIMIT
                
                has_hf_key = False
                hf_key = None
                if request.user_obj:
                    try:
                        api_obj = Api.objects.get(user=request.user_obj, model_name='HuggingFace')
                        hf_key = decrypt_api_key(api_obj.api_key_encrypted)
                        has_hf_key = True
                    except Api.DoesNotExist:
                        pass
                
                if request.user_obj:
                    user_key = f"user_{request.user_obj.user_id}"
                else:
                    if not request.session.session_key:
                        request.session.create()
                    user_key = f"anon_{request.session.session_key}" if request.session.session_key else "anon_default"
                
                # Block coding and file handling tasks for Halo if user has no Hugging Face API key
                coding_and_file_modes = {
                    'coding', 'file_handle', 'search_code', 'search_file', 
                    'code_file', 'search_code_file', 'voice_file'
                }
                if mode in coding_and_file_modes and not has_hf_key:
                    return JsonResponse({
                        "status": "success",
                        "reply": "⚠️ **Access Restricted**\n\nTo use coding or file handling features in Halo, please log in and add your Hugging Face API key in settings.",
                        "session_id": session_id_str,
                        "is_new_chat": False,
                        "temporary": True
                    })
                
                if not has_hf_key:
                    current_usage = get_halo_usage(user_key)
                    if current_usage >= HALO_MAX_LIMIT:
                        return JsonResponse({
                            "status": "success",
                            "reply": "⚠️ **Limit Reached**\n\nYou have reached the maximum message limit for Halo. To continue using Halo, please log in and add your Hugging Face API key in settings. You can also log in and configure a Gemini API key to get access to Baymax, our flagship reasoning model.",
                            "session_id": session_id_str,
                            "is_new_chat": False,
                            "temporary": True
                        })
                    increment_halo_usage(user_key)

                from .halo import Halo
                baymax = Halo(
                    chat_history=chat_history,
                    temporary=temporary_chat,
                    is_superuser=is_superuser,
                    is_fast=is_fast,
                    db_lookup_time=db_lookup_time,
                    hf_key=hf_key,
                )
            else:
                has_user_keys = bool(gemini_key or openrouter_key or groq_key)
                if not has_user_keys:
                    from .usage_tracker import get_baymax_usage, increment_baymax_usage, BAYMAX_MAX_LIMIT
                    if request.user_obj:
                        user_key = f"user_{request.user_obj.user_id}"
                    else:
                        if not request.session.session_key:
                            request.session.create()
                        user_key = f"anon_{request.session.session_key}" if request.session.session_key else "anon_default"
                    
                    current_usage = get_baymax_usage(user_key)
                    if current_usage >= BAYMAX_MAX_LIMIT:
                        if mode.startswith('zeno_'):
                            limit_msg = "⚠️ **Limit Reached**\n\nYou have reached the maximum message limit for Zeno. To continue, please log in and configure your own API keys (Gemini and Groq) in account."
                        else:
                            limit_msg = "⚠️ **Limit Reached**\n\nYou have reached the maximum message limit for Baymax. To continue, please log in and configure your own API keys (Gemini, OpenRouter, or Groq) in settings."
                        return JsonResponse({
                            "status": "success",
                            "reply": limit_msg,
                            "session_id": session_id_str,
                            "is_new_chat": False,
                            "temporary": True
                        })
                    increment_baymax_usage(user_key)

                baymax = Baymax(
                    gemini_key=gemini_key,
                    openrouter_key=openrouter_key,
                    groq_key=groq_key,
                    user_instruction=user_settings.get('user_instruction'),
                    user_about_me=user_settings.get('user_about_me'),
                    user_name=user_settings.get('user_name'),
                    chat_history=chat_history,
                    nlp_result=nlp_result,
                    # Pass new flags so Baymax behaves correctly
                    temporary=temporary_chat,
                    is_superuser=is_superuser,
                    is_fast=is_fast,
                    db_lookup_time=db_lookup_time,
                )
        except ImportError as e:
            missing = str(e).replace("No module named ", "").strip("'")
            return JsonResponse({
                "status": "success",
                "reply": f"Missing library: **{missing}** is not installed on the server.\n\nTo fix this, run:\n```\npip install {missing}\n```",
                "session_id": session_id_str,
                "is_new_chat": False,
                "temporary": True
            })
        except Exception as e:
            return JsonResponse({
                "status": "success",
                "reply": f"Server Configuration Error: {str(e)}\n\nPlease ensure your server has all required environment variables.",
                "session_id": session_id_str,
                "is_new_chat": False,
                "temporary": True
            })

        t1 = time.time()

        # ── Handler dispatch ──────────────────────────────────────────────────
        try:
            from backend.multiple_task import MultipleTask
            mt = MultipleTask(baymax)
            handlers = {
                'coding':        lambda: baymax.handle_coding(message),
                'websearch':     lambda: baymax.handle_websearch(message),
                'Voice Chat':    lambda: baymax.handle_voice_chat(message),
                'voice_message': lambda: baymax.handle_voice_message(message),
                'file_handle':   lambda: baymax.handle_file(message, d.get('files', [])),
                'live_display':  lambda: baymax.handle_live_display(message),
                'zeno_eco':      lambda: baymax.handle_zeno_eco(message),
                'zeno_plus':     lambda: baymax.handle_zeno_plus(message),
                'zeno_voice':    lambda: baymax.handle_zeno_voice(message),
                'zeno_shadow':   lambda: baymax.handle_zeno_shadow(message),
                'search_code':   lambda: mt.handle_search_code(message),
                'search_file':   lambda: mt.handle_search_file(message, d.get('files', [])),
                'code_file':     lambda: mt.handle_code_file(message, d.get('files', [])),
                'search_code_file': lambda: mt.handle_search_code_file(message, d.get('files', [])),
                'voice_file':    lambda: mt.handle_voice_file(message, d.get('files', [])),
                'voice_search':  lambda: mt.handle_voice_search(message),
                'voice_search_file': lambda: mt.handle_voice_search_file(message, d.get('files', [])),
                'voice_code':    lambda: baymax.handle_coding(message),
                'voice_code_file': lambda: mt.handle_code_file(message, d.get('files', [])),
                'voice_search_code': lambda: mt.handle_search_code(message),
                'voice_search_code_file': lambda: mt.handle_search_code_file(message, d.get('files', [])),
            }
            reply = handlers.get(mode, lambda: baymax.handle_text(message))()
        except ImportError as e:
            missing = str(e).replace("No module named ", "").strip("'")
            reply = (
                f"Missing library: **{missing}** is not installed on the server.\n\n"
                f"To fix this, run:\n```\npip install {missing}\n```"
            )
        except Exception as e:
            # Per-handler errors: full detail for superusers, safe message otherwise
            tb = traceback.format_exc()
            logger.error("Handler error [mode=%s]: %s\n%s", mode, e, tb)
            if is_superuser:
                reply = (
                    f"**[Superuser Debug]** Handler `{mode}` raised an exception:\n\n"
                    f"```\n{tb.strip()}\n```"
                )
            else:
                reply = "Something went wrong. Please try again later."

        if not reply:
            reply = "Something went wrong. Please try again later."
            
        logger.debug("AI reply: %.2fs | total: %.2fs", time.time() - t1, time.time() - t0)
        
        # ── Update Active Memory Buffer ───────────────────────────────────────
        if not temporary_chat:
            active_buffer = cache.get(f"history_{chat_session.session_id}")
            if active_buffer is None:
                active_buffer = list(chat_history)
            
            active_buffer.append({"role": "user", "content": message.strip()})
            active_buffer.append({"role": "assistant", "content": reply.strip()})
            
            # Enforce max buffer size to 5 turns (10 messages)
            active_buffer = active_buffer[-10:]
            cache.set(f"history_{chat_session.session_id}", active_buffer, timeout=3600 * 2)

        # ── Persist (skipped for temporary chats) ─────────────────────────────
        if not temporary_chat:
            _db_executor.submit(
                _save_chat_async,
                request.user_obj, chat_session, mode, model, message, reply, nlp_intent,
            )
        else:
            logger.debug(
                "Temporary chat — skipping DB save for session %s", getattr(chat_session, 'session_id', session_id_str)
            )

        return JsonResponse({
            "status":      "success",
            "reply":       reply,
            "session_id":  str(chat_session.session_id) if chat_session else session_id_str,
            "is_new_chat": is_new_session,
            # Let the frontend know whether this was a temporary session so it
            # can avoid storing the session_id in its own history list.
            "temporary":   temporary_chat,
        })

    except Exception as e:
        return safe_error_response(request, logger, "chat_api", e)


# ── Profile & Settings (unchanged) ────────────────────────────────────────────
@login_required_json
def get_user_profile(request):
    try:
        s = Setting.objects.get(user=request.user_obj)
        settings_data = {
            "user_instruction":           s.user_instruction,
            "user_about_me":              s.user_about_me,
            "user_name":                  s.user_name,
            "user_role":                  getattr(s, 'user_role', ''),
            "user_interests":             getattr(s, 'user_interests', ''),
            "enable_custom_instructions": getattr(s, 'enable_custom_instructions', True),
        }
    except Setting.DoesNotExist:
        settings_data = {
            "user_instruction":           None,
            "user_about_me":              None,
            "user_name":                  None,
            "user_role":                  '',
            "user_interests":             '',
            "enable_custom_instructions": True,
        }

    return JsonResponse({
        "status": "success",
        "user": {
            "user_id":    str(request.user_obj.user_id),
            "name":       request.user_obj.name,
            "email":      request.user_obj.email,
            "created_at": request.user_obj.created_at.isoformat(),
            "chat_count": Chat.objects.filter(user=request.user_obj).count(),
        },
        "settings": settings_data,
    })
@csrf_exempt
@login_required_json
@json_only
def save_user_settings(request):
    d = request.json_data
    try:
        s, _ = Setting.objects.get_or_create(user=request.user_obj)
        s.user_instruction            = d.get('user_instruction', '').strip()  or None
        s.user_about_me               = d.get('user_about_me', '').strip()     or None
        s.user_name                   = d.get('user_name', '').strip()         or None
        s.user_role                   = d.get('user_role', '').strip()         or None
        s.user_interests              = d.get('user_interests', '').strip()    or None
        s.enable_custom_instructions  = d.get('enable_custom_instructions', True)
        s.save()
        
        cache.delete(f"settings_{request.user_obj.user_id}")
        
        return JsonResponse({"status": "success", "message": "Settings saved successfully"})
    except Exception as e:
        return safe_error_response(request, logger, "save_user_settings", e)


# ── Chat History ──────────────────────────────────────────────────────────────
from django.db.models import OuterRef, Subquery

@login_required_json
def get_chat_history(request):
    try:
        first_task_type = Chat.objects.filter(
            session=OuterRef('pk')
        ).order_by('timestamp').values('task_type')[:1]
        
        first_model = Chat.objects.filter(
            session=OuterRef('pk')
        ).order_by('timestamp').values('model_used')[:1]

        sessions = ChatSession.objects.filter(user=request.user_obj).annotate(
            first_task_type=Subquery(first_task_type),
            first_model=Subquery(first_model)
        ).order_by('-updated_at')
        
        chat_list = []
        for sess in sessions:
            if not sess.first_task_type:
                continue
            chat_list.append({
                'chat_id':    str(sess.session_id),
                'session_id': str(sess.session_id),
                'preview':    sess.title,
                'task_type':  sess.first_task_type,
                'model_used': sess.first_model,
                'created_at': sess.created_at.isoformat(),
                'date':       sess.updated_at.strftime('%Y-%m-%d'),
            })
        return JsonResponse({"status": "success", "chats": chat_list})
    except Exception as e:
        return safe_error_response(request, logger, "get_chat_history", e)
@login_required_json
def get_chat_messages(request, chat_id):
    try:
        sess  = ChatSession.objects.get(session_id=chat_id, user=request.user_obj)
        qs    = sess.messages.order_by('timestamp')
        limit = request.GET.get('limit')
        if limit:
            try:
                limit = int(limit)
                qs    = qs[max(0, qs.count() - limit):]
            except ValueError:
                pass

        msgs, last = [], None
        for chat in qs:
            msgs.append({'role': 'user',      'content': chat.input_text,  'timestamp': chat.timestamp.isoformat()})
            msgs.append({'role': 'assistant', 'content': chat.output_text, 'timestamp': chat.timestamp.isoformat()})
            last = chat

        if not msgs:
            return JsonResponse({"status": "success", "messages": []})

        return JsonResponse({
            "status":    "success",
            "messages":  msgs,
            "chat_info": {
                'chat_id':    str(sess.session_id),
                'session_id': str(sess.session_id),
                'task_type':  last.task_type,
                'model_used': last.model_used,
                'created_at': sess.created_at.isoformat(),
                'is_developer_session': getattr(last, 'task_type', '') == 'developer',
            },
        })
    except ChatSession.DoesNotExist:
        return JsonResponse({"status": "fail", "message": "Chat not found"}, status=404)
    except Exception as e:
        return safe_error_response(request, logger, "get_chat_messages", e)
@login_required_json
def get_recent_messages(request, chat_id):
    try:
        sess  = ChatSession.objects.get(session_id=chat_id, user=request.user_obj)
        total = sess.messages.count()
        qs    = sess.messages.order_by('timestamp')[max(0, total - 5):]
        msgs, last = [], None
        for chat in qs:
            msgs.append({'role': 'user',      'content': chat.input_text,  'timestamp': chat.timestamp.isoformat()})
            msgs.append({'role': 'assistant', 'content': chat.output_text, 'timestamp': chat.timestamp.isoformat()})
            last = chat
        return JsonResponse({
            "status":           "success",
            "messages":         msgs,
            "total_in_session": total,
            "returned":         len(msgs) // 2,
            "chat_info": {
                'chat_id':    str(sess.session_id),
                'session_id': str(sess.session_id),
                'task_type':  last.task_type  if last else None,
                'model_used': last.model_used if last else None,
            },
        })
    except ChatSession.DoesNotExist:
        return JsonResponse({"status": "fail", "message": "Chat not found"}, status=404)
    except Exception as e:
        return safe_error_response(request, logger, "get_recent_messages", e)
@csrf_exempt
@login_required_json
def delete_chat(request, chat_id):
    if request.method not in ["DELETE", "POST"]:
        return JsonResponse({"status": "fail", "message": "Method not allowed"}, status=405)
    try:
        ChatSession.objects.get(session_id=chat_id, user=request.user_obj).delete()
        return JsonResponse({"status": "success", "message": "Chat deleted successfully"})
    except ChatSession.DoesNotExist:
        return JsonResponse({"status": "fail", "message": "Chat not found"}, status=404)
    except Exception as e:
        return safe_error_response(request, logger, "delete_chat", e)

# =============================================================================
# Edge TTS API View
# =============================================================================
async def _generate_tts_audio(text, voice="en-US-AriaNeural"):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    audio_data = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
    return bytes(audio_data)

@csrf_exempt
def tts_api(request):
    if request.method not in ["GET", "POST"]:
        return JsonResponse({"status": "fail", "message": "Method not allowed"}, status=405)
    
    if request.method == "POST":
        try:
            data = json.loads(request.body.decode('utf-8'))
            text = data.get("text", "")
            voice = data.get("voice", "en-US-AriaNeural")
        except Exception:
            text = request.POST.get("text", "")
            voice = request.POST.get("voice", "en-US-AriaNeural")
    else:
        text = request.GET.get("text", "")
        voice = request.GET.get("voice", "en-US-AriaNeural")
        
    text = (text or "").strip()
    if not text:
        return JsonResponse({"status": "fail", "message": "No text provided"}, status=400)
    
    text = text[:1500]
    
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            audio_bytes = loop.run_until_complete(_generate_tts_audio(text, voice))
        finally:
            loop.close()
            
        return HttpResponse(audio_bytes, content_type="audio/mpeg")
    except Exception as e:
        logger.error(f"TTS generation error: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@csrf_exempt
@optional_login_json
def transcribe_audio(request):
    logger.info("Transcribe audio endpoint hit. Method: %s, Content-Type: %s", request.method, request.content_type)
    
    if request.method != 'POST':
        return JsonResponse({'status': 'fail', 'message': 'Only POST method is allowed'}, status=405)
        
    try:
        if request.content_type == 'application/json':
            import json
            import base64
            from django.core.files.uploadedfile import SimpleUploadedFile
            
            data = json.loads(request.body.decode('utf-8'))
            audio_base64 = data.get('audio')
            if not audio_base64:
                logger.warning("No audio key found in JSON body")
                return JsonResponse({'status': 'fail', 'message': 'No audio data provided'}, status=400)
                
            audio_bytes = base64.b64decode(audio_base64)
            audio_file = SimpleUploadedFile("voice.webm", audio_bytes, content_type="audio/webm")
        else:
            if 'audio' not in request.FILES:
                logger.warning("No audio key found in request.FILES")
                return JsonResponse({'status': 'fail', 'message': 'No audio file provided'}, status=400)
            audio_file = request.FILES['audio']
            
        audio_file.seek(0)
    except Exception as e:
        logger.error(f"Transcribe request parsing failed: {e}")
        return JsonResponse({'status': 'fail', 'message': f"Request parsing failed: {str(e)}"}, status=400)
    
    gemini_key = None
    groq_key = None
    
    # Try fetching keys from the authenticated user (via session cookies or X-Session-Id header)
    user = getattr(request, 'user_obj', None) or (request.user if request.user.is_authenticated else None)
    if user:
        try:
            api_obj = Api.objects.get(user=user, model_name='Groq')
            groq_key = decrypt_api_key(api_obj.api_key_encrypted)
        except Api.DoesNotExist:
            pass
        try:
            api_obj = Api.objects.get(user=user, model_name='Gemini')
            gemini_key = decrypt_api_key(api_obj.api_key_encrypted)
        except Api.DoesNotExist:
            pass

    # If anonymous or missing keys, fall back to setting defaults
    from django.conf import settings
    if not groq_key:
        groq_key = getattr(settings, "GROQ_API_KEY", None)
    if not gemini_key:
        gemini_key = getattr(settings, "GEMINI_API_KEY", None)
        
    if groq_key:
        try:
            import requests
            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            headers = {
                "Authorization": f"Bearer {groq_key}"
            }
            files = {
                "file": (audio_file.name, audio_file.read(), audio_file.content_type or "audio/webm")
            }
            data = {
                "model": "whisper-large-v3"
            }
            r = requests.post(url, headers=headers, files=files, data=data)
            if r.status_code == 200:
                res_data = r.json()
                logger.info("Groq transcription success: %s", res_data.get('text', ''))
                return JsonResponse({'status': 'success', 'text': res_data.get('text', '')})
            else:
                logger.warning("Groq transcription failed with status %s: %s", r.status_code, r.text)
                return JsonResponse({'status': 'fail', 'message': f"Groq transcription failed: {r.text}"}, status=r.status_code)
        except Exception as e:
            logger.error("Error calling Groq Whisper: %s", e, exc_info=True)
            return JsonResponse({'status': 'fail', 'message': f"Error calling Groq Whisper: {str(e)}"}, status=500)
            
    elif gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_file:
                for chunk in audio_file.chunks():
                    temp_file.write(chunk)
                temp_path = temp_file.name
                
            try:
                with open(temp_path, "rb") as f:
                    audio_bytes = f.read()
                    
                response = model.generate_content([
                    {
                        "mime_type": "audio/webm",
                        "data": audio_bytes
                    },
                    "Provide a highly accurate transcription of this audio. Output only the transcription, nothing else."
                ])
                logger.info("Gemini transcription success: %s", response.text.strip())
                return JsonResponse({'status': 'success', 'text': response.text.strip()})
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        except Exception as e:
            logger.error("Error calling Gemini audio: %s", e, exc_info=True)
            return JsonResponse({'status': 'fail', 'message': f"Error calling Gemini audio: {str(e)}"}, status=500)
            
    else:
        logger.warning("No API key configured for speech-to-text transcription")
        return JsonResponse({'status': 'fail', 'message': 'No API key configured for speech-to-text transcription'}, status=400)


# =============================================================================
# Custom 404 Error Handler
# =============================================================================
def custom_404(request, exception=None):
    return render(request, "404.html", status=404)
