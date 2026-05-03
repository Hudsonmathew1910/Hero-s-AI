"""
infinsight/views.py
--------------------
All API endpoints for Infinsight.
No AI logic here — delegates everything to the service layer.
"""

import json
import logging
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

from django.http import JsonResponse
from django.shortcuts import render
from django.conf import settings
from django_ratelimit.decorators import ratelimit

from backend.models import User, Api
from backend.encryption import decrypt_api_key
from .models import UploadedFile, ProjectSession, ChatMessage
from .Rag import ingest_file, query_session, cleanup_session, get_session_title

logger = logging.getLogger("infinsight.views")

# Thread pool for async ingestion (non-blocking uploads)
_ingest_executor = ThreadPoolExecutor(max_workers=3)

# ─────────────────────────────────────────────────────────────────────────────
# Allowed file types and max size
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls", "pdf"}
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

EXT_TO_TYPE = {
    "csv": "csv",
    "xlsx": "excel",
    "xls": "excel",
    "pdf": "pdf",
}


# ─────────────────────────────────────────────────────────────────────────────
# Decorators
# ─────────────────────────────────────────────────────────────────────────────

def login_required_json(f):
    @wraps(f)
    def wrapper(request, *args, **kwargs):
        uid = request.session.get("user_id")
        if not uid:
            return JsonResponse({"status": "fail", "message": "Authentication required"}, status=401)
        try:
            request.user_obj = User.objects.get(user_id=uid)
        except User.DoesNotExist:
            request.session.flush()
            return JsonResponse({"status": "fail", "message": "Session invalid"}, status=401)
        return f(request, *args, **kwargs)
    return wrapper


def _get_gemini_key(user) -> str:
    """Fetch and decrypt the user's Gemini API key."""
    try:
        api = Api.objects.get(user=user, model_name="Gemini")
        return decrypt_api_key(api.api_key_encrypted)
    except Api.DoesNotExist:
        raise ValueError("No Gemini API key found. Please add your Gemini key in API Keys settings.")


def _validate_file(uploaded_file):
    """Validate extension and file size. Returns (ext, file_type) or raises."""
    name = uploaded_file.name
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '.{ext}'. Allowed: CSV, Excel, PDF.")
    if uploaded_file.size > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File too large ({uploaded_file.size // (1024*1024)}MB). Max is {MAX_FILE_SIZE_MB}MB.")
    return ext, EXT_TO_TYPE[ext]


# ─────────────────────────────────────────────────────────────────────────────
# Main page
# ─────────────────────────────────────────────────────────────────────────────

def infinsight_page(request):
    """Render the Infinsight HTML page."""
    username = None
    user_id = request.session.get("user_id")
    if user_id:
        try:
            user = User.objects.get(user_id=user_id)
            username = user.name
        except Exception:
            pass
    return render(request, "infinsight.html", {"username": username})


# ─────────────────────────────────────────────────────────────────────────────
# File Upload + Session creation
# ─────────────────────────────────────────────────────────────────────────────
@ratelimit(key='ip', rate='5/m', block=True)
@login_required_json
def upload_file(request):
    """
    POST /infinsight/upload/
    Accepts: multipart/form-data with 'file' field.
    Creates UploadedFile + ProjectSession, triggers async ingestion.
    """
    t0 = time.time()
    logger.info("Upload Request Received")
    if request.method != "POST":
        return JsonResponse({"status": "fail", "message": "Method not allowed"}, status=405)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"status": "fail", "message": "No file provided"}, status=400)

    try:
        ext, file_type = _validate_file(uploaded)
        gemini_key = _get_gemini_key(request.user_obj)

        # Persist file record
        file_record = UploadedFile.objects.create(
            user=request.user_obj,
            file=uploaded,
            original_filename=uploaded.name,
            file_type=file_type,
            file_size=uploaded.size,
        )

        # Generate a nice title
        title = get_session_title(uploaded.name, file_type, gemini_key)

        # Create session (status=processing)
        session = ProjectSession.objects.create(
            user=request.user_obj,
            uploaded_file=file_record,
            session_name=title,
        )

        # Kick off async ingestion
        _ingest_executor.submit(
            _async_ingest,
            session.session_id,
            file_record.file.path,
            file_type,
            gemini_key,
        )

        logger.debug("Upload logic completed in %.2fs", time.time() - t0)
        return JsonResponse({
            "status": "success",
            "message": "File uploaded. Processing started.",
            "session": {
                "session_id": str(session.session_id),
                "session_name": session.session_name,
                "file_name": uploaded.name,
                "file_type": file_type,
                "status": session.status,
                "created_at": session.created_at.isoformat(),
            },
        })

    except ValueError as e:
        return JsonResponse({"status": "fail", "message": str(e)}, status=400)
    except Exception as e:
        logger.error("Upload error: %s\n%s", e, traceback.format_exc())
        return JsonResponse({"status": "fail", "message": "Upload failed. Please try again."}, status=500)


def _async_ingest(session_id, file_path: str, file_type: str, gemini_key: str):
    """Run inside thread pool — reads file from disk and ingests."""
    try:
        from django.db import close_old_connections
        close_old_connections()

        session = ProjectSession.objects.get(session_id=session_id)
        with open(file_path, "rb") as f:
            result = ingest_file(session, f, file_type, gemini_key)
        logger.info("Async ingestion done for %s: %s", session_id, result)
    except Exception as e:
        logger.error("Async ingest crashed for %s: %s\n%s", session_id, e, traceback.format_exc())
        try:
            from django.db import close_old_connections
            close_old_connections()
            session = ProjectSession.objects.get(session_id=session_id)
            session.status = "error"
            session.error_message = str(e)[:500]
            session.save(update_fields=["status", "error_message"])
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Chat
# ─────────────────────────────────────────────────────────────────────────────
@ratelimit(key='ip', rate='20/m', block=True)
@login_required_json
def chat(request):
    """
    POST /infinsight/chat/
    Body: {"session_id": "...", "message": "..."}
    """
    t0 = time.time()
    logger.info("Chat Message Received")
    if request.method != "POST":
        return JsonResponse({"status": "fail", "message": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"status": "fail", "message": "Invalid JSON"}, status=400)

    session_id = data.get("session_id", "").strip()
    user_message = data.get("message", "").strip()

    if not session_id:
        return JsonResponse({"status": "fail", "message": "session_id required"}, status=400)
    if not user_message:
        return JsonResponse({"status": "fail", "message": "message required"}, status=400)

    try:
        session = ProjectSession.objects.get(session_id=session_id, user=request.user_obj)
    except ProjectSession.DoesNotExist:
        return JsonResponse({"status": "fail", "message": "Session not found"}, status=404)

    try:
        gemini_key = _get_gemini_key(request.user_obj)
    except ValueError as e:
        return JsonResponse({"status": "fail", "message": str(e)}, status=400)

    # Build chat history (last 6 messages)
    recent = list(session.messages.order_by("-timestamp")[:6])
    recent.reverse()
    history = []
    for msg in recent:
        history.append({"role": "user", "content": msg.user_message})
        history.append({"role": "assistant", "content": msg.ai_response})

    try:
        result = query_session(session, user_message, gemini_key, history)

        # Persist the exchange
        if result.get("error") != "session_not_ready":
            ChatMessage.objects.create(
                session=session,
                user_message=user_message,
                ai_response=result["reply"],
                sources_used=result.get("sources", []),
                model_used=result.get("model", "unknown"),
            )
            # Update session timestamp
            from django.utils import timezone
            session.updated_at = timezone.now()
            session.save(update_fields=["updated_at"])

        logger.debug("Total Response Time: %.2fs", time.time() - t0)
        return JsonResponse({
            "status": "success",
            "reply": result["reply"],
            "model": result.get("model", ""),
            "sources": result.get("sources", []),
        })

    except Exception as e:
        logger.error("Chat error session %s: %s\n%s", session_id, e, traceback.format_exc())
        return JsonResponse({"status": "fail", "message": "Analysis failed. Please try again."}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Session Management
# ─────────────────────────────────────────────────────────────────────────────
@login_required_json
def list_sessions(request):
    """GET /infinsight/sessions/ — list all sessions for the user."""
    sessions = ProjectSession.objects.filter(user=request.user_obj).select_related("uploaded_file")
    data = []
    for s in sessions:
        data.append({
            "session_id": str(s.session_id),
            "session_name": s.session_name,
            "file_name": s.uploaded_file.original_filename,
            "file_type": s.uploaded_file.file_type,
            "status": s.status,
            "chunk_count": s.chunk_count,
            "message_count": s.messages.count(),
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
        })
    return JsonResponse({"status": "success", "sessions": data})
@login_required_json
def session_detail(request, session_id):
    """
    GET  /infinsight/session/<id>/  → chat history
    DELETE /infinsight/session/<id>/delete/ → handled separately
    """
    try:
        session = ProjectSession.objects.get(session_id=session_id, user=request.user_obj)
    except ProjectSession.DoesNotExist:
        return JsonResponse({"status": "fail", "message": "Session not found"}, status=404)

    messages = session.messages.order_by("timestamp")
    history = []
    for m in messages:
        history.append({
            "message_id": str(m.message_id),
            "user_message": m.user_message,
            "ai_response": m.ai_response,
            "model_used": m.model_used,
            "timestamp": m.timestamp.isoformat(),
        })

    return JsonResponse({
        "status": "success",
        "session": {
            "session_id": str(session.session_id),
            "session_name": session.session_name,
            "file_name": session.uploaded_file.original_filename,
            "file_type": session.uploaded_file.file_type,
            "status": session.status,
            "chunk_count": session.chunk_count,
            "metadata": session.uploaded_file.metadata,
            "created_at": session.created_at.isoformat(),
        },
        "messages": history,
    })
@login_required_json
def delete_session(request, session_id):
    """POST /infinsight/session/<id>/delete/"""
    if request.method not in ["DELETE", "POST"]:
        return JsonResponse({"status": "fail", "message": "Method not allowed"}, status=405)
    try:
        session = ProjectSession.objects.get(session_id=session_id, user=request.user_obj)
        cleanup_session(session)  # Delete Pinecone vectors
        # Delete file from disk
        try:
            if session.uploaded_file.file:
                import os
                file_path = session.uploaded_file.file.path
                if os.path.exists(file_path):
                    os.remove(file_path)
        except Exception:
            pass
        session.uploaded_file.delete()  # Cascades to session + messages
        return JsonResponse({"status": "success", "message": "Session deleted"})
    except ProjectSession.DoesNotExist:
        return JsonResponse({"status": "fail", "message": "Session not found"}, status=404)
    except Exception as e:
        logger.error("Delete session error: %s", e)
        return JsonResponse({"status": "fail", "message": str(e)}, status=500)
@login_required_json
def session_status(request, session_id):
    """GET /infinsight/session/<id>/status/ — poll processing status."""
    try:
        session = ProjectSession.objects.get(session_id=session_id, user=request.user_obj)
        return JsonResponse({
            "status": "success",
            "session_status": session.status,
            "chunk_count": session.chunk_count,
            "error": session.error_message,
        })
    except ProjectSession.DoesNotExist:
        return JsonResponse({"status": "fail", "message": "Session not found"}, status=404)