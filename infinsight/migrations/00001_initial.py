"""
infinsight/migrations/0001_initial.py
Initial migration for Infinsight models.
"""

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("backend", "0001_initial"),  # adjust to your actual latest backend migration
    ]

    operations = [
        migrations.CreateModel(
            name="UploadedFile",
            fields=[
                ("file_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="infinsight_files", to="backend.user")),
                ("file", models.FileField(upload_to="infinsight/uploads/%Y/%m/%d/")),
                ("original_filename", models.CharField(max_length=255)),
                ("file_type", models.CharField(choices=[("csv", "CSV"), ("excel", "Excel"), ("pdf", "PDF")], max_length=10)),
                ("file_size", models.PositiveBigIntegerField(help_text="Size in bytes")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ProjectSession",
            fields=[
                ("session_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="infinsight_sessions", to="backend.user")),
                ("uploaded_file", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="session", to="infinsight.uploadedfile")),
                ("session_name", models.CharField(max_length=200)),
                ("pinecone_namespace", models.CharField(blank=True, max_length=300)),
                ("status", models.CharField(choices=[("processing", "Processing"), ("ready", "Ready"), ("error", "Error")], default="processing", max_length=20)),
                ("chunk_count", models.PositiveIntegerField(default=0, help_text="Number of chunks indexed")),
                ("error_message", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.CreateModel(
            name="ChatMessage",
            fields=[
                ("message_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="infinsight.projectsession")),
                ("user_message", models.TextField()),
                ("ai_response", models.TextField()),
                ("sources_used", models.JSONField(blank=True, default=list)),
                ("model_used", models.CharField(default="gemini-1.5-flash", max_length=100)),
                ("timestamp", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["timestamp"]},
        ),
    ]