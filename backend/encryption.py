from cryptography.fernet import Fernet
from django.conf import settings

def encrypt_text(text):
    """Generic text encryption using project-wide ENCRYPTION_KEY"""
    if not text:
        return text
    f = Fernet(settings.ENCRYPTION_KEY)
    return f.encrypt(text.encode()).decode()

def decrypt_text(encrypted_text):
    """Generic text decryption with fallback for plain text"""
    if not encrypted_text:
        return encrypted_text
    try:
        f = Fernet(settings.ENCRYPTION_KEY)
        return f.decrypt(encrypted_text.encode()).decode()
    except Exception:
        # Fallback for old plain-text data or invalid tokens
        return encrypted_text

def encrypt_api_key(api_key):
    """Encrypt API key before storing in database"""
    return encrypt_text(api_key)

def decrypt_api_key(encrypted_key):
    """Decrypt API key when needed"""
    return decrypt_text(encrypted_key)