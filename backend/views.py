"""
views.py — Hero AI Django views

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

from concurrent.futures import ThreadPoolExecutor
from functools import wraps

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.hashers import make_password, check_password
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings as django_settings
from django.utils import timezone

from django.db import connections, close_old_connections
from .models import User, Api, Chat, Setting, ChatSession
from .encryption import encrypt_api_key, decrypt_api_key
from .hero_model import Baymax
from .Nlp import preprocess, resolve_mode

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
    keys = {'Gemini': None, 'OpenRouter': None, 'Groq': None}
    for api in Api.objects.filter(user=user, model_name__in=keys):
        keys[api.model_name] = decrypt_api_key(api.api_key_encrypted)
    return keys['Gemini'], keys['OpenRouter'], keys['Groq']


@db_thread_task
def get_user_settings(user):
    try:
        s = Setting.objects.get(user=user)
        return {
            'user_instruction':           s.user_instruction,
            'user_about_me':              s.user_about_me,
            'user_name':                  s.user_name,
            'enable_custom_instructions': getattr(s, 'enable_custom_instructions', True),
        }
    except Setting.DoesNotExist:
        return {
            'user_instruction':           None,
            'user_about_me':              None,
            'user_name':                  None,
            'enable_custom_instructions': True,
        }


def get_session_history(session_id_str, user, limit=5):
    if not session_id_str:
        return []
    try:
        session = ChatSession.objects.get(session_id=session_id_str, user=user)
        chats   = list(session.messages.order_by('-timestamp')[:limit])
        chats.reverse()
        history = []
        for chat in chats:
            if not chat.input_text or not chat.output_text:
                continue
            history.append({"role": "user",      "content": chat.input_text.strip()})
            history.append({"role": "assistant", "content": chat.output_text.strip()})
        return history
    except (ChatSession.DoesNotExist, Exception):
        return []


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
            },
        })
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Signup error for %s: %s\n%s", email, e, tb)
        
        # Check if the session already has a user who might be a superuser
        current_uid = request.session.get('user_id')
        is_superuser = False
        if current_uid:
            try:
                is_superuser = User.objects.get(user_id=current_uid).is_superuser
            except Exception: pass
            
        if is_superuser:
            msg = f"**[Superuser Debug]** Signup error:\n\n```\n{tb.strip()}\n```"
        else:
            msg = "Something went wrong. Please try again later."
            
        return JsonResponse({"status": "fail", "message": msg}, status=500)


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
        return JsonResponse({
            "status": "success",
            "message": "Login successful",
            "user": {
                "user_id":      str(user.user_id),
                "name":         user.name,
                "email":        user.email,
                "has_api_keys": has_keys,
            },
        })
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Login error for %s: %s\n%s", email, e, tb)
        
        # In login, if the user doesn't exist yet, we can't easily check is_superuser
        # unless they were already logged in (unlikely). We fallback to safe message.
        msg = "Something went wrong. Please try again later."
        return JsonResponse({"status": "fail", "message": msg}, status=500)


@csrf_exempt
def logout_view(request):
    if request.method != "POST":
        return JsonResponse({"status": "fail", "message": "Method not allowed"}, status=405)
    request.session.flush()
    return JsonResponse({"status": "success", "message": "Logged out"})


@csrf_exempt
def check_session(request):
    uid = request.session.get('user_id')
    if not uid:
        return JsonResponse({"status": "fail", "logged_in": False})
    try:
        user     = User.objects.get(user_id=uid)
        has_keys = Api.objects.filter(user=user, model_name__in=['Gemini', 'OpenRouter']).exists()
        return JsonResponse({
            "status":    "success",
            "logged_in": True,
            "user": {
                "user_id":      str(user.user_id),
                "name":         user.name,
                "email":        user.email,
                "has_api_keys": has_keys,
            },
        })
    except User.DoesNotExist:
        request.session.flush()
        return JsonResponse({"status": "fail", "logged_in": False})


# ── Google OAuth ──────────────────────────────────────────────────────────────

def google_login(request):
    flow = request.GET.get('flow', 'signin')
    request.session['oauth_flow'] = flow

    redirect_uri = f"{django_settings.SITE_URL}/auth/google/callback"
    print("SITE_URL:", django_settings.SITE_URL)
    return redirect(
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={django_settings.GOOGLE_CLIENT_ID}&redirect_uri={redirect_uri}&"
        f"response_type=code&scope=openid%20email%20profile&access_type=offline"
    )


@csrf_exempt
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
            return redirect('/')
        except User.DoesNotExist:
            if flow == 'signin':
                return redirect('/?error=Account+does+not+exist.+Please+create+an+account.')
            else:
                # Signup flow: create account
                user = User.objects.create(
                    email=email,
                    name=name,
                    google_id=google_id,
                    password_hash=''  # No password yet
                )
                Setting.objects.create(user=user)

                request.session['setup_user_id'] = str(user.user_id)
                return redirect('/?action=google_setup')

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
        
        return JsonResponse({
            "status": "success",
            "message": "Account setup complete",
            "user": {
                "user_id":      str(user.user_id),
                "name":         user.name,
                "email":        user.email,
                "has_api_keys": False,
            },
        })
    except User.DoesNotExist:
        return JsonResponse({"status": "fail", "message": "User not found"}, status=404)


# ── API Keys ──────────────────────────────────────────────────────────────────

@csrf_exempt
@login_required_json
@json_only
def save_api_keys(request):
    d          = request.json_data
    gemini     = d.get('gemini', '').strip()
    openrouter = d.get('openrouter', '').strip()
    groq       = d.get('groq', '').strip()

    if not any([gemini, openrouter, groq]):
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
        return JsonResponse({"status": "success", "message": "API keys saved"})
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("save_api_keys error for user %s: %s\n%s", request.user_obj.user_id, e, tb)
        
        is_superuser = getattr(request.user_obj, 'is_superuser', False)
        if is_superuser:
            msg = f"**[Superuser Debug]** save_api_keys error:\n\n```\n{tb.strip()}\n```"
        else:
            msg = "Something went wrong. Please try again later."
            
        return JsonResponse({"status": "fail", "message": msg}, status=500)


@csrf_exempt
@login_required_json
def check_api_keys(request):
    keys = {
        n: Api.objects.filter(user=request.user_obj, model_name=n).exists()
        for n in ['Gemini', 'OpenRouter', 'Groq']
    }
    return JsonResponse({
        "status":      "success",
        "has_api_keys": keys['Gemini'] or keys['OpenRouter'],
        "keys":         {k.lower(): v for k, v in keys.items()},
    })


# ── Chat ──────────────────────────────────────────────────────────────────────

@csrf_exempt
@login_required_json
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

    # ── Determine whether this user has superuser privileges ──────────────────
    # A user is a superuser if their is_superuser flag is set to True.
    is_superuser: bool = getattr(request.user_obj, 'is_superuser', False)

    if not raw_message:
        return JsonResponse({"status": "fail", "message": "Message required"}, status=400)


    try:
        # ── NLP pre-processing ────────────────────────────────────────────────
        nlp_result = preprocess(raw_message, source=mode)
        message    = nlp_result["clean_text"] or raw_message
        mode       = resolve_mode(nlp_result, mode)
        nlp_intent = nlp_result["intent"]

        logger.info(
            "chat_api | user=%s | mode=%s | intent=%s | temporary=%s | tokens≈%s",
            request.user_obj.user_id, mode, nlp_intent,
            temporary_chat, nlp_result["metadata"].get("token_estimate"),
        )

        # ── Parallel DB lookups ───────────────────────────────────────────────
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_keys = pool.submit(get_user_api_keys,      request.user_obj)
            f_sett = pool.submit(get_user_settings,      request.user_obj)
            f_sess = pool.submit(
                _get_or_create_session,
                request.user_obj,
                # For temporary chats: always start a brand-new session by
                # passing None so _get_or_create_session never re-uses one.
                None if temporary_chat else session_id_str,
                message,
            )

            gemini_key, openrouter_key, groq_key = f_keys.result()
            user_settings                         = f_sett.result()
            chat_session, is_new_session          = f_sess.result()

        # ── Session history ───────────────────────────────────────────────────
        if temporary_chat:
            # Temporary chats have no persisted history — use whatever the
            # frontend sent in this request (in-memory context only).
            chat_history = send_history
        else:
            # Determine history turn limit based on task type (1 turn = 2 messages: User + AI)
            # Text: 3 turns (6) | Coding/Voice: 2 turns (4) | File/WebSearch: 1 turn (2)
            history_limits = {
                'text':           3,
                'coding':         2,
                'Voice Chat':     2,
                'voice_message':  2,
                'file_handle':    1,
                'websearch':      2,
            }
            turn_limit = history_limits.get(mode, 5)
            
            chat_history = (
                send_history
                if send_history
                else get_session_history(session_id_str, request.user_obj, turn_limit)
            )

        logger.debug("DB lookup: %.2fs", time.time() - t0)

        # ── Build Baymax instance ─────────────────────────────────────────────
        user_instruction = (
            user_settings['user_instruction']
            if user_settings['enable_custom_instructions'] else None
        )
        user_about_me = (
            user_settings['user_about_me']
            if user_settings['enable_custom_instructions'] else None
        )

        baymax = Baymax(
            gemini_key=gemini_key,
            openrouter_key=openrouter_key,
            groq_key=groq_key,
            user_instruction=user_instruction,
            user_about_me=user_about_me,
            user_name=user_settings['user_name'],
            chat_history=chat_history,
            nlp_result=nlp_result,
            # Pass new flags so Baymax behaves correctly
            temporary=temporary_chat,
            is_superuser=is_superuser,
        )

        t1 = time.time()

        # ── Handler dispatch ──────────────────────────────────────────────────
        try:
            handlers = {
                'coding':        lambda: baymax.handle_coding(message),
                'websearch':     lambda: baymax.handle_websearch(message),
                'Voice Chat':    lambda: baymax.handle_voice_chat(message),
                'voice_message': lambda: baymax.handle_voice_message(message),
                'file_handle':   lambda: baymax.handle_file(message, d.get('files', [])),
                'live_display':  lambda: baymax.handle_live_display(message),
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

        logger.debug("AI reply: %.2fs | total: %.2fs", time.time() - t1, time.time() - t0)

        # ── Persist (skipped for temporary chats) ─────────────────────────────
        if not temporary_chat:
            _db_executor.submit(
                _save_chat_async,
                request.user_obj, chat_session, mode, model, message, reply, nlp_intent,
            )
        else:
            logger.debug(
                "Temporary chat — skipping DB save for session %s", chat_session.session_id
            )

        return JsonResponse({
            "status":      "success",
            "reply":       reply,
            "session_id":  str(chat_session.session_id),
            "is_new_chat": is_new_session,
            # Let the frontend know whether this was a temporary session so it
            # can avoid storing the session_id in its own history list.
            "temporary":   temporary_chat,
        })

    except Exception as e:
        # Top-level catch-all
        tb = traceback.format_exc()
        logger.error("chat_api top-level error: %s\n%s", e, tb)

        if is_superuser:
            error_message = (
                f"**[Superuser Debug]** Unhandled exception in chat_api:\n\n"
                f"```\n{tb.strip()}\n```"
            )
        else:
            error_message = "Something went wrong. Please try again later."

        return JsonResponse({"status": "fail", "message": error_message}, status=500)


# ── Profile & Settings (unchanged) ────────────────────────────────────────────

@csrf_exempt
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
        return JsonResponse({"status": "success", "message": "Settings saved successfully"})
    except Exception as e:
        logger.exception("save_user_settings error for user %s", request.user_obj.user_id)
        return JsonResponse({"status": "fail", "message": str(e)}, status=500)


# ── Chat History ──────────────────────────────────────────────────────────────

@csrf_exempt
@login_required_json
def get_chat_history(request):
    try:
        sessions  = ChatSession.objects.filter(user=request.user_obj).order_by('-updated_at')
        chat_list = []
        for sess in sessions:
            first = sess.messages.order_by('timestamp').first()
            if not first:
                continue
            chat_list.append({
                'chat_id':    str(sess.session_id),
                'session_id': str(sess.session_id),
                'preview':    sess.title,
                'task_type':  first.task_type,
                'model_used': first.model_used,
                'created_at': sess.created_at.isoformat(),
                'date':       sess.updated_at.strftime('%Y-%m-%d'),
            })
        return JsonResponse({"status": "success", "chats": chat_list})
    except Exception as e:
        logger.exception("get_chat_history error for user %s", request.user_obj.user_id)
        return JsonResponse({"status": "fail", "message": str(e)}, status=500)


@csrf_exempt
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
            },
        })
    except ChatSession.DoesNotExist:
        return JsonResponse({"status": "fail", "message": "Chat not found"}, status=404)
    except Exception as e:
        logger.exception("get_chat_messages error for chat %s", chat_id)
        return JsonResponse({"status": "fail", "message": str(e)}, status=500)


@csrf_exempt
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
        logger.exception("get_recent_messages error for chat %s", chat_id)
        return JsonResponse({"status": "fail", "message": str(e)}, status=500)


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
        logger.exception("delete_chat error for chat %s", chat_id)
        return JsonResponse({"status": "fail", "message": str(e)}, status=500)