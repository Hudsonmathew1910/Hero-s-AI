"""
infinsight/models.py
--------------------
Database models for the Infinsight AI Personal Data Analyst feature.
Three core models: ProjectSession, UploadedFile, ChatMessage.
"""

import uuid
from django.db import models
from backend.models import User  # Reference existing User model


class UploadedFile(models.Model):
    """Tracks every file a user uploads."""

    FILE_TYPE_CHOICES = [
        ("csv", "CSV"),
        ("excel", "Excel"),
        ("pdf", "PDF"),
    ]

    file_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="infinsight_files")
    file = models.FileField(upload_to="infinsight/uploads/%Y/%m/%d/")
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    file_size = models.PositiveBigIntegerField(help_text="Size in bytes")
    metadata = models.JSONField(default=dict, blank=True)
    # e.g. {"rows": 1200, "columns": ["name","age"], "pages": 5}
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.original_filename} ({self.user.name})"


class ProjectSession(models.Model):
    """
    One session = one uploaded file.
    All chats within this session are scoped to that file's data.
    """

    STATUS_CHOICES = [
        ("processing", "Processing"),
        ("ready", "Ready"),
        ("error", "Error"),
    ]

    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="infinsight_sessions")
    uploaded_file = models.OneToOneField(
        UploadedFile, on_delete=models.CASCADE, related_name="session"
    )
    session_name = models.CharField(max_length=200)
    pinecone_namespace = models.CharField(max_length=300, blank=True)
    # namespace format: "infinsight_{user_id}_{session_id}"
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="processing")
    chunk_count = models.PositiveIntegerField(default=0, help_text="Number of chunks indexed")
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.session_name} — {self.user.name}"

    def save(self, *args, **kwargs):
        if not self.pinecone_namespace:
            self.pinecone_namespace = (
                f"infinsight_{str(self.user.user_id).replace('-', '')}_{str(self.session_id).replace('-', '')}"
            )
        super().save(*args, **kwargs)


class ChatMessage(models.Model):
    """Stores every turn (user message + AI response) in a session."""

    message_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ProjectSession, on_delete=models.CASCADE, related_name="messages"
    )
    user_message = models.TextField()
    ai_response = models.TextField()
    sources_used = models.JSONField(default=list, blank=True)
    # e.g. [{"chunk": "...", "score": 0.91}]
    model_used = models.CharField(max_length=100, default="gemini-1.5-flash")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        return f"[{self.session.session_name}] {self.user_message[:60]}"