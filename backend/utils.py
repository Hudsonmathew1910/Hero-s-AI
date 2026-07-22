# backend/utils.py

from cryptography.fernet import Fernet
from django.conf import settings
from django.http import JsonResponse
import traceback
import logging

def encrypt_api_key(api_key):
    """Encrypt API key before storing in database"""
    f = Fernet(settings.ENCRYPTION_KEY)
    return f.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key):
    """Decrypt API key when needed"""
    f = Fernet(settings.ENCRYPTION_KEY)
    return f.decrypt(encrypted_key.encode()).decode()

def safe_error_response(request, logger, context, exception, status=500):
    """
    Standardized error handler for API views.
    1. Logs the full traceback.
    2. Returns generic message to users.
    3. Returns full traceback to superusers.
    """
    tb = traceback.format_exc()
    user_id = getattr(request, 'session', {}).get('user_id', 'anonymous')
    
    logger.error(
        "Exception in %s | User: %s | Error: %s\n%s",
        context, user_id, str(exception), tb
    )

    is_superuser = False
    if hasattr(request, 'user_obj'):
        is_superuser = getattr(request.user_obj, 'is_superuser', False)
    elif user_id != 'anonymous':
        try:
            # Lazy import to avoid circular dependencies
            from .models import User
            is_superuser = User.objects.get(user_id=user_id).is_superuser
        except Exception:
            pass

    if is_superuser:
        message = f"**[Superuser Debug]** {context} error:\n\n```\n{tb.strip()}\n```"
    else:
        message = "Something went wrong. Please try again later."

    return JsonResponse({"status": "fail", "message": message}, status=status)


def is_greeting_or_smalltalk(text: str) -> bool:
    """
    Returns True if the query is a simple greeting or short small talk
    to prevent fetching search results for simple conversational words.
    """
    if not text:
        return True
    clean = text.strip().lower().rstrip('?!.')
    greetings = {
        'hey', 'hello', 'hi', 'yo', 'sup', 'hola', 'hey buddy', 'hey bro', 'hey there',
        'hi there', 'hello there', 'good morning', 'good afternoon', 'good evening',
        'hows it going', 'how are you', 'whats up', 'what up', 'greetings', 'test',
        'hey baymax', 'hey halo', 'hey hero', 'hi baymax', 'hi halo', 'hello baymax',
        'hello halo', 'ok', 'okay', 'hey heros', 'hey buddy heros', 'heros', 'susila'
    }
    return clean in greetings