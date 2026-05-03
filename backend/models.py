"""
backend/model.py
"""
from django.db import models
from .encryption import encrypt_text, decrypt_text
import uuid

class EncryptedTextField(models.TextField):
    """
    Transparently encrypts and decrypts text data in the database.
    Uses cryptography.fernet via helpers in encryption.py.
    """
    def from_db_value(self, value, expression, connection):
        return decrypt_text(value)

    def get_prep_value(self, value):
        return encrypt_text(value)

# Users table
class User(models.Model):
    user_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255)
    google_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    is_superuser = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

# API Keys table
class Api(models.Model):
    api_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='apis')
    model_name = models.CharField(max_length=100)  # Gemini, OpenRouter, Groq
    api_key_encrypted = models.TextField()
    is_mandatory = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'model_name')

    def __str__(self):
        return f"{self.model_name} - {self.user.name}"

# Chat Session table
class ChatSession(models.Model):
    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    title = models.CharField(max_length=200, default='New Chat')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.title} - {self.user.name}"

# Chat history table
class Chat(models.Model):
    history_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chats')
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages', null=True, blank=True)
    task_type = models.CharField(max_length=100)  # Voice Chat, Coding, File Analysis
    model_used = models.CharField(max_length=100)
    input_text = EncryptedTextField()
    output_text = EncryptedTextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.task_type} - {self.user.name}"

# User settings table
class Setting(models.Model):
    setting_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='settings')
    user_instruction = models.TextField(blank=True, null=True)
    user_about_me = models.TextField(blank=True, null=True)
    user_name = models.CharField(max_length=100, blank=True, null=True)
    user_role = models.CharField(max_length=150, blank=True, null=True)
    user_interests = models.TextField(blank=True, null=True)
    
    # Display & Behavior Settings
    enable_custom_instructions = models.BooleanField(default=True)
    
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Settings - {self.user.name}"