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
    company_name = models.CharField(max_length=150, blank=True, null=True)
    user_interests = models.TextField(blank=True, null=True)
    
    # Display & Behavior Settings
    enable_custom_instructions = models.BooleanField(default=True)
    remember_history = models.BooleanField(default=False)
    auto_read_aloud = models.BooleanField(default=False)
    
    # Notification Preferences
    notify_daily_usage = models.BooleanField(default=False)
    notify_quota_alerts = models.BooleanField(default=False)
    notify_product_updates = models.BooleanField(default=True)
    
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Settings - {self.user.name}"

# Anonymous/Free Usage Tracking table
class AnonymousUsage(models.Model):
    user_key = models.CharField(max_length=255, unique=True, primary_key=True)
    message_count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user_key}: {self.message_count}"

class Project(models.Model):
    project_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects')
    name = models.CharField(max_length=150, default="Default Project")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.user.name}"

class DeveloperApiKey(models.Model):
    # 'key' will store the hashed version for fast lookups.
    key = models.CharField(max_length=64, unique=True, primary_key=True)
    # The actual encrypted raw key (deprecated, retained for backwards-compatibility)
    encrypted_key = models.CharField(max_length=512, blank=True, null=True)
    # Masked prefix for safe UI display (e.g., sk-hero-abcd••••••••1234)
    key_prefix = models.CharField(max_length=64, blank=True, default='')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='developer_keys')
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name='api_keys')
    name = models.CharField(max_length=150, default="My API Key")
    scope = models.CharField(max_length=50, default="full")  # 'full', 'read'
    environment = models.CharField(max_length=20, default="live")  # 'live', 'test', 'staging'
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.scope}) - {self.user.name}"

class ExternalProviderKeys(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='external_keys')
    gemini_key = models.CharField(max_length=512, blank=True, null=True)
    groq_key = models.CharField(max_length=512, blank=True, null=True)
    openrouter_key = models.CharField(max_length=512, blank=True, null=True)
    huggingface_key = models.CharField(max_length=512, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"External Keys - {self.user.name}"

class ApiUsageTracking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_usage', null=True, blank=True)
    developer_key = models.ForeignKey(DeveloperApiKey, on_delete=models.CASCADE, null=True, blank=True)
    endpoint = models.CharField(max_length=100, default="/api/v1/chat/completions")
    request_source = models.CharField(max_length=50, default="developer_api")  # e.g., 'developer_api', 'platform_ui', 'web_chat'
    model_used = models.CharField(max_length=100, default="baymax-4.5")
    tokens_used = models.IntegerField(default=0)
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    latency_ms = models.IntegerField(default=0)  # Request execution time in milliseconds
    estimated_cost = models.FloatField(default=0.0)
    status_code = models.IntegerField(default=200)
    error_message = models.TextField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'request_source', 'timestamp'], name='idx_usage_user_src_time'),
            models.Index(fields=['developer_key', 'timestamp'], name='idx_usage_key_time'),
            models.Index(fields=['user', 'timestamp'], name='idx_usage_user_time'),
        ]

    def __str__(self):
        user_str = self.user.name if self.user else "Anonymous"
        return f"{user_str} - {self.model_used} - {self.tokens_used} tokens ({self.latency_ms}ms) at {self.timestamp}"

class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activity_logs', null=True, blank=True)
    action = models.CharField(max_length=100)  # e.g., 'API_KEY_CREATED', 'API_KEY_REVOKED', 'LOGIN_SUCCESS', 'RATE_LIMIT_EXCEEDED'
    details = models.TextField(blank=True, null=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp'], name='idx_actlog_user_time'),
        ]

    def __str__(self):
        user_str = self.user.name if self.user else "System"
        return f"[{self.action}] {user_str} at {self.timestamp}"


class BroadcastMessage(models.Model):
    AUDIENCE_CHOICES = (
        ('product_updates', 'Product Updates Subscribers'),
        ('daily_usage', 'Daily Usage Summary Subscribers'),
        ('quota_alerts', 'Quota Threshold Alerts Subscribers'),
        ('all', 'All Registered Users'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_broadcasts')
    subject = models.CharField(max_length=255)
    audience = models.CharField(max_length=50, choices=AUDIENCE_CHOICES, default='product_updates')
    message_body = models.TextField()
    recipients_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.subject}] to {self.audience} ({self.recipients_count} recipients)"


class UserDailyQuota(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_quotas', null=True, blank=True)
    date = models.DateField(db_index=True)
    requests_count = models.IntegerField(default=0)
    tokens_count = models.IntegerField(default=0)

    # Per-minute rate limit tracking (RPM / TPM)
    rpm_window_start = models.DateTimeField(null=True, blank=True)
    rpm_count = models.IntegerField(default=0)
    tpm_count = models.IntegerField(default=0)

    # 4-Hour window rate limit tracking (Claude style)
    window_4h_start = models.DateTimeField(null=True, blank=True)
    window_4h_count = models.IntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'date')

    def __str__(self):
        user_str = self.user.name if self.user else "Anonymous"
        return f"{user_str} - {self.date}: {self.requests_count} reqs, {self.tokens_count} tokens"