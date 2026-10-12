from django.contrib import admin
from .models import UploadedFile, ProjectSession, ChatMessage

@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "file_type", "user", "file_size", "created_at")
    list_filter = ("file_type", "created_at")
    search_fields = ("original_filename", "user__email")

@admin.register(ProjectSession)
class ProjectSessionAdmin(admin.ModelAdmin):
    list_display = ("session_name", "status", "user", "chunk_count", "updated_at")
    list_filter = ("status", "created_at")
    search_fields = ("session_name", "user__email")

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "model_used", "timestamp")
    list_filter = ("model_used", "timestamp")
    search_fields = ("session__session_name", "user_message")
