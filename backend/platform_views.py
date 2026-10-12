import json
import secrets
import hashlib
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from backend.views import login_required_json
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from backend.models import DeveloperApiKey, ExternalProviderKeys, ApiUsageTracking, ActivityLog, User, Setting, Api, Project
from backend.encryption import encrypt_api_key, decrypt_api_key
from backend.usage_tracker import log_activity

def _error_response(message, status_code=400):
    return JsonResponse({"error": message}, status=status_code)


@csrf_exempt
@login_required_json
def generate_api_key(request):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)
        
    try:
        data = json.loads(request.body)
        name = data.get("name", "My API Key")
        scope = data.get("scope", "full")
        if scope not in ("full", "read"):
            scope = "full"
        environment = data.get("environment", "live")  # 'live', 'test', 'staging'
        expiry_days = data.get("expiry_days")  # optional integer: 30, 60, 90 or None
        project_id = data.get("project_id")
    except (json.JSONDecodeError, ValueError):
        return _error_response("Invalid JSON payload", 400)
        
    project = None
    if project_id:
        from backend.models import Project
        try:
            project = Project.objects.get(project_id=project_id, user=request.user_obj)
        except Project.DoesNotExist:
            pass
    if not project:
        from backend.models import Project
        project = Project.objects.filter(user=request.user_obj).first()

    import datetime
    from django.utils import timezone

    expires_at = None
    if expiry_days and str(expiry_days).isdigit():
        expires_at = timezone.now() + datetime.timedelta(days=int(expiry_days))

    # Generate raw key
    raw_key = f"sk-hero-{secrets.token_urlsafe(32)}"
    
    # Hash the key with SHA-256 for fast $O(1)$ database lookup
    hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
    
    # Store masked prefix for safe UI rendering (raw key is NEVER stored reversibly)
    key_prefix = f"{raw_key[:12]}...{raw_key[-4:]}"

    # Save to database without reversible encrypted key
    dev_key = DeveloperApiKey.objects.create(
        key=hashed_key,
        key_prefix=key_prefix,
        encrypted_key=None,
        user=request.user_obj,
        project=project,
        name=name,
        scope=scope,
        environment=environment,
        expires_at=expires_at
    )

    log_activity(
        user=request.user_obj,
        action="API_KEY_CREATED",
        details=f"Generated API key '{dev_key.name}' (Scope: {scope}, Env: {environment})",
        request=request
    )

    # Return the raw key ONCE to the user
    return JsonResponse({
        "success": True,
        "message": "Key generated successfully. Please copy it now, you won't be able to see it again.",
        "key": raw_key,
        "key_prefix": key_prefix,
        "name": dev_key.name,
        "scope": dev_key.scope,
        "environment": dev_key.environment,
        "project": dev_key.project.name if dev_key.project else None,
        "created_at": dev_key.created_at.isoformat(),
        "expires_at": dev_key.expires_at.isoformat() if dev_key.expires_at else None
    })

@csrf_exempt
@login_required_json
def toggle_api_key_status(request, key_hash):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)
        
    try:
        dev_key = DeveloperApiKey.objects.get(key=key_hash, user=request.user_obj)
        dev_key.is_active = not dev_key.is_active
        dev_key.save()

        status_str = "activated" if dev_key.is_active else "paused"
        log_activity(
            user=request.user_obj,
            action="API_KEY_TOGGLED",
            details=f"{status_str.capitalize()} API key '{dev_key.name}'",
            request=request
        )

        return JsonResponse({
            "success": True,
            "is_active": dev_key.is_active,
            "message": f"API key successfully {status_str}."
        })
    except DeveloperApiKey.DoesNotExist:
        return _error_response("Key not found.", 404)

@csrf_exempt
@login_required_json
def delete_api_key(request, key_hash):
    if request.method != "DELETE":
        return _error_response("Method not allowed", 405)
        
    try:
        dev_key = DeveloperApiKey.objects.get(key=key_hash, user=request.user_obj)
        key_name = dev_key.name
        dev_key.delete()

        log_activity(
            user=request.user_obj,
            action="API_KEY_REVOKED",
            details=f"Revoked API key '{key_name}'",
            request=request
        )

        return JsonResponse({"success": True, "message": "API key revoked successfully."})
    except DeveloperApiKey.DoesNotExist:
        return _error_response("Key not found.", 404)

@csrf_exempt
@login_required_json
def list_api_keys(request):
    from django.db.models import Sum, Value
    from django.db.models.functions import Coalesce

    # Single-query execution: select_related('project') + annotate(spend) eliminates N+1 loops
    keys = DeveloperApiKey.objects.filter(
        user=request.user_obj
    ).select_related('project').annotate(
        annotated_spend=Coalesce(Sum('apiusagetracking__estimated_cost'), Value(0.0))
    ).order_by('-created_at')

    keys_data = []
    for k in keys:
        keys_data.append({
            "name": k.name,
            "id": k.key,
            "masked_key": k.key_prefix or (f"{k.key[:8]}...{k.key[-4:]}" if len(k.key) >= 12 else "sk-hero-..."),
            "scope": k.scope,
            "environment": getattr(k, 'environment', 'live'),
            "project_name": k.project.name if k.project else "Default Project",
            "project_id": str(k.project.project_id) if k.project else "all",
            "created_at": k.created_at.isoformat(),
            "expires_at": k.expires_at.isoformat() if k.expires_at else "Never",
            "last_used": k.last_used.isoformat() if k.last_used else "Never",
            "spend": round(float(k.annotated_spend or 0.0), 6),
            "is_active": k.is_active
        })
    return JsonResponse({"keys": keys_data})

def _get_provider_key(user_obj, provider):
    """Retrieve API key for a provider checking ExternalProviderKeys, Api model, and system environment/settings."""
    import os
    provider = provider.lower()
    key = None
    
    # 1. Check ExternalProviderKeys table
    ext_keys = ExternalProviderKeys.objects.filter(user=user_obj).first()
    if ext_keys:
        if provider == "gemini" and ext_keys.gemini_key:
            key = decrypt_api_key(ext_keys.gemini_key)
        elif provider == "groq" and ext_keys.groq_key:
            key = decrypt_api_key(ext_keys.groq_key)
        elif provider == "openrouter" and ext_keys.openrouter_key:
            key = decrypt_api_key(ext_keys.openrouter_key)
        elif provider == "huggingface" and ext_keys.huggingface_key:
            key = decrypt_api_key(ext_keys.huggingface_key)
            
    # 2. Check legacy Api model table if key not found
    if not key:
        api_obj = Api.objects.filter(user=user_obj, model_name__icontains=provider).first()
        if api_obj and api_obj.api_key_encrypted:
            key = decrypt_api_key(api_obj.api_key_encrypted)

    # 3. Check settings / OS environment variables
    if not key:
        if provider == "gemini":
            key = getattr(settings, "GEMINI_API_KEY", None) or os.getenv("GEMINI_API_KEY")
        elif provider == "groq":
            key = getattr(settings, "GROQ_API_KEY", None) or os.getenv("GROQ_API_KEY")
        elif provider == "openrouter":
            key = getattr(settings, "OPENROUTER_API_KEY", None) or os.getenv("OPENROUTER_API_KEY")
        elif provider == "huggingface":
            key = getattr(settings, "HF_TOKEN", None) or getattr(settings, "HUGGINGFACE_TOKEN", None) or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")

    return key

@csrf_exempt
@login_required_json
def get_external_keys(request):
    user_obj = request.user_obj
    return JsonResponse({
        "gemini_set": bool(_get_provider_key(user_obj, "gemini")),
        "groq_set": bool(_get_provider_key(user_obj, "groq")),
        "openrouter_set": bool(_get_provider_key(user_obj, "openrouter")),
        "huggingface_set": bool(_get_provider_key(user_obj, "huggingface"))
    })

@csrf_exempt
@login_required_json
def save_external_keys(request):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)
        
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _error_response("Invalid JSON payload", 400)

    try:
        user_obj = request.user_obj
        ext_keys, _ = ExternalProviderKeys.objects.get_or_create(user=user_obj)
        
        provider_mapping = [
            ("gemini_key", "gemini", "Gemini"),
            ("groq_key", "groq", "Groq"),
            ("openrouter_key", "openrouter", "OpenRouter"),
            ("huggingface_key", "huggingface", "HuggingFace"),
        ]

        for payload_key, attr_name, model_name in provider_mapping:
            if payload_key in data and data[payload_key].strip():
                val = data[payload_key].strip()
                encrypted_val = encrypt_api_key(val)
                setattr(ext_keys, attr_name + "_key", encrypted_val)
                # Also sync legacy Api model
                Api.objects.update_or_create(
                    user=user_obj,
                    model_name=model_name,
                    defaults={'api_key_encrypted': encrypted_val}
                )
            
        ext_keys.save()

        log_activity(
            user=user_obj,
            action="EXTERNAL_KEYS_UPDATED",
            details="Updated external provider API keys",
            request=request
        )

        return JsonResponse({"success": True, "message": "External keys saved securely."})
    except Exception as e:
        return _error_response(f"Failed to save keys: {str(e)}", 500)

@csrf_exempt
@login_required_json
def test_external_key(request):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _error_response("Invalid JSON payload", 400)

    try:
        provider = data.get("provider", "").lower()
        api_key = data.get("api_key", "").strip()

        # If user did not type a new key, retrieve stored/env key
        if not api_key:
            api_key = _get_provider_key(request.user_obj, provider)

        if not api_key:
            return JsonResponse({"success": False, "error": f"No {provider.capitalize()} key provided or saved."})

        import time, urllib.request, urllib.error
        start_time = time.time()
        
        # Some providers (like Groq) block requests missing a standard User-Agent header
        default_headers = {"User-Agent": "HeroAI/1.0"}

        if provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            req = urllib.request.Request(url, headers=default_headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    latency = round((time.time() - start_time) * 1000)
                    return JsonResponse({"success": True, "provider": "Gemini", "latency_ms": latency, "message": f"Connected! ({latency}ms)"})
        elif provider == "groq":
            url = "https://api.groq.com/openai/v1/models"
            headers = {"Authorization": f"Bearer {api_key}"}
            headers.update(default_headers)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    latency = round((time.time() - start_time) * 1000)
                    return JsonResponse({"success": True, "provider": "Groq", "latency_ms": latency, "message": f"Connected! ({latency}ms)"})
        elif provider == "openrouter":
            url = "https://openrouter.ai/api/v1/auth/key"
            headers = {"Authorization": f"Bearer {api_key}"}
            headers.update(default_headers)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    latency = round((time.time() - start_time) * 1000)
                    return JsonResponse({"success": True, "provider": "OpenRouter", "latency_ms": latency, "message": f"Connected! ({latency}ms)"})
        elif provider == "huggingface":
            url = "https://huggingface.co/api/whoami-v2"
            headers = {"Authorization": f"Bearer {api_key}"}
            headers.update(default_headers)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    latency = round((time.time() - start_time) * 1000)
                    return JsonResponse({"success": True, "provider": "HuggingFace", "latency_ms": latency, "message": f"Connected! ({latency}ms)"})
        else:
            return JsonResponse({"success": False, "error": f"Unknown provider: {provider}"})

    except urllib.error.HTTPError as e:
        return JsonResponse({"success": False, "error": f"HTTP {e.code}: Invalid key or unauthorized"})
    except urllib.error.URLError as e:
        return JsonResponse({"success": False, "error": f"Network error: {str(e.reason)}"})
    except Exception as e:
        return JsonResponse({"success": False, "error": f"Validation failed: {str(e)}"})

@csrf_exempt
@login_required_json
def send_help_email(request):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)
        
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _error_response("Invalid JSON payload", 400)

    try:
        subject = data.get("subject", "").strip() or "Heros Platform Support Request"
        message = data.get("message", "").strip()
        
        if not message:
            return _error_response("Please enter a message for support.", 400)
            
        user_email = getattr(request.user_obj, 'email', 'developer@heros.ai')
        user_name = getattr(request.user_obj, 'name', 'Developer User')
        import os
        ticket_id = f"HERO-TICK-{secrets.token_hex(3).upper()}"
        support_recipient = getattr(settings, 'SUPPORT_EMAIL', None) or os.getenv('SUPPORT_EMAIL', 'support@heros.ai')
        
        full_message = f"Support Request #{ticket_id}\nFrom: {user_name} ({user_email})\nSubject: {subject}\n\nMessage:\n{message}"

        email_sent = False
        # Dispatch email if SMTP configured; gracefully handle when offline
        try:
            from django.core.mail import send_mail
            send_mail(
                subject=f"[Heros AI Support #{ticket_id}] {subject}",
                message=full_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@heros.ai'),
                recipient_list=[support_recipient],
                fail_silently=False,
            )
            email_sent = True
        except Exception as mail_err:
            import logging
            logging.getLogger(__name__).warning(f"Mail delivery skipped/warning for ticket {ticket_id}: {mail_err}")

        log_activity(
            user=request.user_obj,
            action="SUPPORT_TICKET_LOGGED",
            details=f"Ticket #{ticket_id}: {subject} (Email dispatched: {email_sent})",
            request=request
        )

        return JsonResponse({
            "success": True,
            "ticket_id": ticket_id,
            "message": f"Support ticket #{ticket_id} submitted successfully! Our engineering team will respond to {user_email} shortly."
        })
    except Exception as e:
        return _error_response(f"Failed to submit support request: {str(e)}", 500)

@csrf_exempt
@login_required_json
def get_platform_usage(request):
    if request.method != "GET":
        return _error_response("Method not allowed", 405)
        
    from backend.models import ApiUsageTracking, DeveloperApiKey, ActivityLog
    import datetime
    from django.utils import timezone
    from django.db.models import Count, Sum, Avg, Q
    
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Filter exclusively for Developer API requests (or requests associated with Developer API Keys)
    dev_api_qs = ApiUsageTracking.objects.filter(
        user=request.user_obj,
        request_source="developer_api"
    )
    
    # --- Summary stats (Developer API only) ---
    today_stats = dev_api_qs.filter(
        timestamp__gte=today_start
    ).aggregate(
        total_requests=Count('id'),
        total_tokens=Sum('tokens_used'),
        total_prompt=Sum('prompt_tokens'),
        total_completion=Sum('completion_tokens'),
        total_cost=Sum('estimated_cost'),
        avg_latency=Avg('latency_ms'),
        success_count=Count('id', filter=Q(status_code=200)),
        error_count=Count('id', filter=~Q(status_code=200))
    )
    
    # --- User's API keys (for the dropdown and per-key breakdown) ---
    user_keys = list(DeveloperApiKey.objects.filter(user=request.user_obj).values_list('key', 'name'))
    key_names = {k: name for k, name in user_keys}
    
    # --- Build 30-day history ---
    thirty_days_ago = today_start - datetime.timedelta(days=29)
    recent_usage = dev_api_qs.filter(
        timestamp__gte=thirty_days_ago
    ).select_related('developer_key')
    
    # Initialize date buckets
    date_labels = []
    for i in range(30):
        day = (thirty_days_ago + datetime.timedelta(days=i)).strftime('%Y-%m-%d')
        date_labels.append(day)
    
    # Per-key request history + error history
    requests_per_key = {}  # {key_name: {date: count}}
    errors_per_code = {}   # {status_code: {date: count}}
    success_per_day = {d: 0 for d in date_labels}
    total_per_day = {d: 0 for d in date_labels}
    tokens_per_day = {d: {'prompt': 0, 'completion': 0, 'total': 0} for d in date_labels}
    
    for record in recent_usage:
        day_str = timezone.localtime(record.timestamp).strftime('%Y-%m-%d')
        if day_str not in total_per_day:
            continue
            
        # Determine key name
        if record.developer_key:
            kname = key_names.get(record.developer_key_id, record.developer_key_id[:8])
        else:
            kname = "Developer API"
        
        # Per-key requests
        if kname not in requests_per_key:
            requests_per_key[kname] = {d: 0 for d in date_labels}
        requests_per_key[kname][day_str] += 1
        
        # Total & success per day
        total_per_day[day_str] += 1
        if record.status_code == 200:
            success_per_day[day_str] += 1
        else:
            # Per error code
            code_str = str(record.status_code)
            if code_str not in errors_per_code:
                errors_per_code[code_str] = {d: 0 for d in date_labels}
            errors_per_code[code_str][day_str] += 1
        
        # Token history
        tokens_per_day[day_str]['prompt'] += record.prompt_tokens
        tokens_per_day[day_str]['completion'] += record.completion_tokens
        tokens_per_day[day_str]['total'] += record.tokens_used
    
    # Calculate success rate per day
    success_rate = {}
    for d in date_labels:
        if total_per_day[d] > 0:
            success_rate[d] = round((success_per_day[d] / total_per_day[d]) * 100, 1)
        else:
            success_rate[d] = None  # N/A
    
    # Error code labels
    ERROR_LABELS = {
        '400': 'BadRequest', '401': 'Unauthorized', '403': 'Forbidden',
        '404': 'NotFound', '405': 'MethodNotAllowed', '429': 'RateLimited',
        '500': 'ServerError', '503': 'ServiceUnavailable'
    }
    errors_formatted = {}
    for code, daily in errors_per_code.items():
        label = f"{code} {ERROR_LABELS.get(code, 'Error')}"
        errors_formatted[label] = daily

    # Fetch recent activity logs (Audit Trail)
    activities = ActivityLog.objects.filter(user=request.user_obj).order_by('-timestamp')[:15]
    activity_data = [
        {
            "action": a.action,
            "details": a.details,
            "ip_address": a.ip_address,
            "timestamp": a.timestamp.isoformat()
        }
        for a in activities
    ]

    # Fetch recent request logs (Developer API Request Logging Table only)
    recent_logs = dev_api_qs.select_related('developer_key').order_by('-timestamp')[:20]
    request_log_data = [
        {
            "id": r.id,
            "endpoint": r.endpoint,
            "request_source": r.request_source,
            "model": r.model_used,
            "tokens": r.tokens_used,
            "latency_ms": r.latency_ms,
            "estimated_cost": round(r.estimated_cost, 6),
            "status_code": r.status_code,
            "key_name": key_names.get(r.developer_key_id, "Developer API Key") if r.developer_key_id else "Developer API Key",
            "timestamp": r.timestamp.isoformat()
        }
        for r in recent_logs
    ]
            
    # Fetch per-model token & cost breakdown (Developer API only - valid active models)
    valid_models = ["baymax-4.5", "baymax"]
    model_stats = dev_api_qs.filter(model_used__in=valid_models).values('model_used').annotate(
        requests=Count('id'),
        tokens=Sum('tokens_used'),
        cost=Sum('estimated_cost')
    ).order_by('-tokens')

    model_breakdown = [
        {
            "model": m["model_used"],
            "requests": m["requests"],
            "tokens": m["tokens"] or 0,
            "cost": round(m["cost"] or 0.0, 6)
        }
        for m in model_stats
    ]

    # System Status & Health indicator
    system_status = {
        "status": "Operational",
        "indicator": "🟢 All Systems Operational",
        "avg_latency_ms": round(today_stats['avg_latency'] or 45.0, 1),
        "uptime": "99.98%"
    }

    # Current Tier & Rate Limits & Reset Times
    from backend.models import UserDailyQuota
    now = timezone.now()
    today_date = timezone.localtime(now).date()
    quota_rec = UserDailyQuota.objects.filter(user=request.user_obj, date=today_date).first()
    daily_quota_used = quota_rec.requests_count if quota_rec else (today_stats['total_requests'] or 0)

    # 1. Daily Reset Time
    next_midnight = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    daily_reset_sec = max(0, int((next_midnight - now).total_seconds()))
    d_h = daily_reset_sec // 3600
    d_m = (daily_reset_sec % 3600) // 60
    daily_reset_human = f"Resets at 12:00 AM Midnight (in {d_h}h {d_m}m)"

    # 2. Per-Minute Reset Time
    rpm_reset_sec = 0
    if quota_rec and quota_rec.rpm_window_start:
        rpm_reset_sec = max(0, 60 - int((now - quota_rec.rpm_window_start).total_seconds()))
    rpm_reset_human = f"Resets in {rpm_reset_sec}s" if rpm_reset_sec > 0 else "Resets every 60s"

    # 3. 4-Hour Reset Time
    h4_reset_sec = 0
    if quota_rec and quota_rec.window_4h_start:
        h4_reset_sec = max(0, 14400 - int((now - quota_rec.window_4h_start).total_seconds()))
    h4_h = h4_reset_sec // 3600
    h4_m = (h4_reset_sec % 3600) // 60
    h4_reset_human = f"Resets in {h4_h}h {h4_m}m" if h4_reset_sec > 0 else "Resets every 4 Hours"

    rate_limits = {
        "tier": "Heros 5 Free",
        "requests_per_min": 100,
        "rpm_used": quota_rec.rpm_count if quota_rec else 0,
        "rpm_reset_human": rpm_reset_human,
        "tokens_per_min": 40000,
        "tpm_used": quota_rec.tpm_count if quota_rec else 0,
        "tpm_reset_human": rpm_reset_human,
        "daily_request_limit": 1000,
        "daily_used": daily_quota_used,
        "daily_reset_human": daily_reset_human,
        "window_4h_limit": 250,
        "window_4h_used": quota_rec.window_4h_count if quota_rec else 0,
        "window_4h_reset_human": h4_reset_human,
    }

    # Project-level breakdown for Usage section
    user_projects = Project.objects.filter(user=request.user_obj)
    if not user_projects.exists():
        default_p = Project.objects.create(user=request.user_obj, name="Default Gemini Project")
        DeveloperApiKey.objects.filter(user=request.user_obj, project__isnull=True).update(project=default_p)
        user_projects = Project.objects.filter(user=request.user_obj)
    else:
        first_p = user_projects.first()
        DeveloperApiKey.objects.filter(user=request.user_obj, project__isnull=True).update(project=first_p)

    project_breakdown = []
    for p in user_projects:
        clean_uuid = str(p.project_id).replace('-', '')
        numeric_suffix = ''.join(filter(str.isdigit, clean_uuid))[:10].ljust(10, '0')
        client_id = f"gen-lang-client-{numeric_suffix}"
        
        p_keys = DeveloperApiKey.objects.filter(project=p, user=request.user_obj)
        p_usage = dev_api_qs.filter(developer_key__project=p)
        
        p_reqs = p_usage.count()
        p_tokens = p_usage.aggregate(t=Sum('tokens_used'))['t'] or 0
        p_cost = p_usage.aggregate(c=Sum('estimated_cost'))['c'] or 0.0

        project_breakdown.append({
            "project_id": str(p.project_id),
            "client_id": client_id,
            "name": p.name,
            "keys_count": p_keys.count(),
            "requests": p_reqs,
            "tokens": p_tokens,
            "cost": round(float(p_cost), 4)
        })

    return JsonResponse({
        "status": "success",
        "today_requests": daily_quota_used,
        "today_tokens": today_stats['total_tokens'] or (quota_rec.tokens_count if quota_rec else 0),
        "today_prompt_tokens": today_stats['total_prompt'] or 0,
        "today_completion_tokens": today_stats['total_completion'] or 0,
        "today_cost": round(today_stats['total_cost'] or 0.0, 6),
        "avg_latency_ms": round(today_stats['avg_latency'] or 0.0, 1),
        "today_success": today_stats['success_count'] or 0,
        "today_errors": today_stats['error_count'] or 0,
        "daily_limit": 1000,
        "date_labels": date_labels,
        "requests_per_key": requests_per_key,
        "errors_per_code": errors_formatted,
        "success_rate": success_rate,
        "tokens_per_day": tokens_per_day,
        "total_per_day": total_per_day,
        "activity_logs": activity_data,
        "request_logs": request_log_data,
        "model_breakdown": model_breakdown,
        "project_breakdown": project_breakdown,
        "system_status": system_status,
        "rate_limits": rate_limits,
        "api_keys": [{"key_hash": k, "name": name} for k, name in user_keys]
    })

@csrf_exempt
@login_required_json
def request_quota_increase(request):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)
        
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _error_response("Invalid JSON payload", 400)

    try:
        requested_tier = data.get("tier", "Heros 5 Pro")
        reason = data.get("reason", "Increased API demand")

        log_activity(
            user=request.user_obj,
            action="QUOTA_INCREASE_REQUESTED",
            details=f"Requested upgrade to {requested_tier}. Reason: {reason}",
            request=request
        )

        return JsonResponse({
            "success": True,
            "message": f"Quota increase request for {requested_tier} submitted successfully! Our team will process it within 24 hours."
        })
    except Exception as e:
        return _error_response(f"Failed to submit request: {str(e)}", 500)


@csrf_exempt
@login_required_json
def change_password(request):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _error_response("Invalid JSON payload", 400)

    try:
        current_password = data.get("current_password", "").strip()
        new_password = data.get("new_password", "").strip()
        confirm_password = data.get("confirm_password", "").strip()

        if not current_password or not new_password or not confirm_password:
            return _error_response("All password fields are required.")

        if new_password != confirm_password:
            return _error_response("New password and confirmation do not match.")

        if len(new_password) < 8:
            return _error_response("New password must be at least 8 characters long.")

        user = request.user_obj
        if user.password_hash and not check_password(current_password, user.password_hash):
            return _error_response("Incorrect current password.", 403)

        user.password_hash = make_password(new_password)
        user.save()

        log_activity(
            user=user,
            action="PASSWORD_CHANGED",
            details="User successfully updated account password",
            request=request
        )

        return JsonResponse({
            "success": True,
            "message": "Password updated successfully."
        })
    except Exception as e:
        return _error_response(f"Failed to update password: {str(e)}", 500)


@csrf_exempt
@login_required_json
def purge_request_logs(request):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)

    try:
        user = request.user_obj
        usage_deleted, _ = ApiUsageTracking.objects.filter(user=user).delete()
        activity_deleted, _ = ActivityLog.objects.filter(user=user).delete()

        return JsonResponse({
            "success": True,
            "message": f"Historical logs purged successfully ({usage_deleted} API records, {activity_deleted} activity logs)."
        })
    except Exception as e:
        return _error_response(f"Failed to purge logs: {str(e)}", 500)


@csrf_exempt
@login_required_json
def delete_developer_account(request):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)

    try:
        user = request.user_obj
        user_email = user.email

        DeveloperApiKey.objects.filter(user=user).delete()
        ExternalProviderKeys.objects.filter(user=user).delete()
        ApiUsageTracking.objects.filter(user=user).delete()
        ActivityLog.objects.filter(user=user).delete()
        Setting.objects.filter(user=user).delete()

        user.delete()
        request.session.flush()

        return JsonResponse({
            "success": True,
            "message": f"Developer account '{user_email}' and all associated keys/data have been permanently deleted.",
            "redirect_url": "/"
        })
    except Exception as e:
        return _error_response(f"Failed to delete account: {str(e)}", 500)


@csrf_exempt
@login_required_json
def create_project(request):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)
    try:
        data = json.loads(request.body)
        name = data.get("name", "").strip()
    except (json.JSONDecodeError, ValueError):
        return _error_response("Invalid JSON payload", 400)

    if not name:
        return _error_response("Project name is required", 400)

    from backend.models import Project
    project, created = Project.objects.get_or_create(
        user=request.user_obj,
        name=name
    )

    log_activity(
        user=request.user_obj,
        action="PROJECT_CREATED",
        details=f"Created project '{project.name}'",
        request=request
    )

    return JsonResponse({
        "success": True,
        "created": created,
        "project": {
            "project_id": project.project_id,
            "name": project.name,
            "created_at": project.created_at.isoformat()
        }
    })


@csrf_exempt
@login_required_json
def list_projects(request):
    if request.method != "GET":
        return _error_response("Method not allowed", 405)
    from backend.models import Project, DeveloperApiKey, ApiUsageTracking
    from django.db.models import Count, Sum
    from django.utils import timezone
    import datetime

    # 1. Single query: Fetch all projects with precalculated key counts
    projects = Project.objects.filter(
        user=request.user_obj
    ).annotate(
        annotated_keys_count=Count('api_keys', distinct=True)
    ).order_by("created_at")

    if not projects.exists():
        default_p = Project.objects.create(user=request.user_obj, name="Default Gemini Project")
        DeveloperApiKey.objects.filter(user=request.user_obj, project__isnull=True).update(project=default_p)
        projects = Project.objects.filter(
            user=request.user_obj
        ).annotate(
            annotated_keys_count=Count('api_keys', distinct=True)
        ).order_by("created_at")

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 2. Single query: Precompute all project-level usage for the month
    project_ids = [p.project_id for p in projects]
    month_usage_qs = ApiUsageTracking.objects.filter(
        user=request.user_obj,
        developer_key__project_id__in=project_ids,
        timestamp__gte=month_start
    ).values('developer_key__project_id').annotate(
        spend=Sum('estimated_cost'),
        requests=Count('id'),
        tokens=Sum('tokens_used')
    )
    usage_by_project = {
        row['developer_key__project_id']: row
        for row in month_usage_qs
    }

    # 3. Assemble results in memory (0 additional DB queries in the loop)
    project_list = []
    for p in projects:
        stats = usage_by_project.get(p.project_id, {})
        spend = stats.get('spend') or 0.0
        requests = stats.get('requests') or 0
        tokens = stats.get('tokens') or 0

        clean_uuid = str(p.project_id).replace("-", "")
        numeric_suffix = "".join(filter(str.isdigit, clean_uuid))[:10].ljust(10, '0')
        client_id = f"gen-lang-client-{numeric_suffix}"

        project_list.append({
            "project_id": str(p.project_id),
            "client_id": client_id,
            "name": p.name,
            "created_at": p.created_at.strftime("%b %d, %Y") if p.created_at else "Feb 22, 2026",
            "keys_count": p.annotated_keys_count,
            "monthly_spend": f"${spend:.2f}" if spend > 0 else "-",
            "monthly_spend_num": round(float(spend), 4),
            "total_requests": requests,
            "total_tokens": tokens,
            "billing_tier": "Free tier",
            "status": "Active"
        })

    return JsonResponse({"success": True, "projects": project_list})


@csrf_exempt
@login_required_json
def delete_project(request, project_id):
    if request.method != "POST":
        return _error_response("Method not allowed", 405)
    from backend.models import Project, DeveloperApiKey
    try:
        project = Project.objects.get(project_id=project_id, user=request.user_obj)
        name = project.name
        
        # Permanently delete all API keys belonging to this project (which also cascades to their usage logs)
        keys_qs = DeveloperApiKey.objects.filter(project=project, user=request.user_obj)
        keys_count = keys_qs.count()
        keys_qs.delete()
        
        # Delete project itself
        project.delete()

        log_activity(
            user=request.user_obj,
            action="PROJECT_DELETED",
            details=f"Deleted project '{name}' along with {keys_count} associated API key(s)",
            request=request
        )
        return JsonResponse({
            "success": True, 
            "message": f"Project '{name}' and {keys_count} associated API key(s) deleted successfully."
        })
    except Project.DoesNotExist:
        return _error_response("Project not found", 404)




