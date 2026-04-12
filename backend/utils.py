# backend/utils.py

from cryptography.fernet import Fernet
from django.conf import settings


def encrypt_api_key(api_key):
    """Encrypt API key before storing in database"""
    f = Fernet(settings.ENCRYPTION_KEY)
    return f.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key):
    """Decrypt API key when needed"""
    f = Fernet(settings.ENCRYPTION_KEY)
    return f.decrypt(encrypted_key.encode()).decode()