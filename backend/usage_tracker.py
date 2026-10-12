import logging
from backend.models import AnonymousUsage, ApiUsageTracking, ActivityLog

logger = logging.getLogger(__name__)

HALO_MAX_LIMIT = 5
BAYMAX_MAX_LIMIT = 5

def get_halo_usage(user_key: str) -> int:
    """
    Get the current message count for the given user identifier from the database.
    """
    usage, _ = AnonymousUsage.objects.get_or_create(user_key=user_key)
    return usage.message_count

def increment_halo_usage(user_key: str) -> int:
    """
    Increment the message count for the given user identifier in the database.
    """
    usage, _ = AnonymousUsage.objects.get_or_create(user_key=user_key)
    usage.message_count += 1
    usage.save(update_fields=['message_count', 'updated_at'])
    return usage.message_count

def get_baymax_usage(user_key: str) -> int:
    """
    Get the current message count for the given user identifier (for Baymax model).
    """
    return get_halo_usage(f"baymax_{user_key}")

def increment_baymax_usage(user_key: str) -> int:
    """
    Increment the message count for the given user identifier (for Baymax model).
    """
    return increment_halo_usage(f"baymax_{user_key}")

def get_client_ip(request) -> str:
    """
    Extract client IP address from Django HTTP request.
    """
    if not request:
        return ""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '')
    return ip

def estimate_token_count(text: str) -> int:
    """
    Quick heuristic token estimator (~4 chars per token).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)

def estimate_cost(model_used: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Calculate estimated cost in USD based on model pricing per 1K tokens.
    """
    model = (model_used or "").lower()
    
    # Pricing per 1k tokens (prompt_rate, completion_rate)
    rates = {
        'baymax-4.5': (0.0005, 0.0015),
        'halo': (0.0001, 0.0003),
        'infinsight': (0.0005, 0.0015),
        'gemini-1.5-flash': (0.000075, 0.0003),
        'gemini-1.5-pro': (0.00125, 0.005),
        'llama-3.3-70b': (0.00059, 0.00079),
    }
    
    p_rate, c_rate = rates.get(model, (0.0005, 0.0015))
    cost = ((prompt_tokens / 1000.0) * p_rate) + ((completion_tokens / 1000.0) * c_rate)
    return round(cost, 6)

def log_api_request(
    user=None,
    developer_key=None,
    endpoint="/api/v1/chat/completions",
    request_source="developer_api",
    model_used="baymax-4.5",
    prompt_tokens=0,
    completion_tokens=0,
    latency_ms=0,
    status_code=200,
    error_message=None,
    request=None,
    ip_address=None
):
    """
    Unified, fail-safe database request logging.
    """
    try:
        if request and not ip_address:
            ip_address = get_client_ip(request)
            
        total_tokens = prompt_tokens + completion_tokens
        cost = estimate_cost(model_used, prompt_tokens, completion_tokens)
        
        record = ApiUsageTracking.objects.create(
            user=user,
            developer_key=developer_key,
            endpoint=endpoint,
            request_source=request_source,
            model_used=model_used,
            tokens_used=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=int(latency_ms),
            estimated_cost=cost,
            status_code=status_code,
            error_message=error_message,
            ip_address=ip_address
        )
        return record
    except Exception as e:
        logger.error(f"Failed to log API request usage: {e}", exc_info=True)
        return None

def log_activity(user=None, action="UNKNOWN_ACTION", details=None, request=None, ip_address=None):
    """
    Unified activity and audit logging.
    """
    try:
        if request and not ip_address:
            ip_address = get_client_ip(request)
            
        log_entry = ActivityLog.objects.create(
            user=user,
            action=action,
            details=details,
            ip_address=ip_address
        )
        return log_entry
    except Exception as e:
        logger.error(f"Failed to log activity: {e}", exc_info=True)
        return None


def check_and_increment_rate_limits(user, prompt_tokens=0, completion_tokens=0):
    """
    Atomically checks and updates rate limits and daily quota in database.
    Does NOT depend on ApiUsageTracking telemetry rows, so purging request logs NEVER resets rate limits or daily quotas!

    Limits enforced:
    - Daily Quota: 1,000 requests / day (resets at 12:00 AM midnight)
    - RPM (Requests Per Minute): 100 requests / min
    - TPM (Tokens Per Minute): 40,000 tokens / min
    - 4-Hour Window: 250 requests / 4 hours (Claude-style rolling window)

    Returns:
        (allowed: bool, error_message: str | None, headers: dict)
    """
    if not user:
        return True, None, {}

    from backend.models import UserDailyQuota
    from django.utils import timezone
    from datetime import timedelta
    from django.db import transaction

    now = timezone.now()
    today_date = timezone.localtime(now).date()

    try:
        with transaction.atomic():
            # Atomically lock the row for the user's daily quota to prevent race conditions
            quota, _ = UserDailyQuota.objects.select_for_update().get_or_create(
                user=user,
                date=today_date,
                defaults={
                    'rpm_window_start': now,
                    'window_4h_start': now,
                }
            )

            # 1. Check Daily Quota (1,000 req / day)
            DAILY_QUOTA_LIMIT = 1000
            if quota.requests_count >= DAILY_QUOTA_LIMIT:
                next_midnight = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                reset_str = next_midnight.strftime('%I:%M %p')
                return False, f"Daily quota limit reached ({DAILY_QUOTA_LIMIT:,} requests/day). Limit resets at 12:00 AM midnight ({reset_str}).", {
                    'X-RateLimit-Limit-Daily': str(DAILY_QUOTA_LIMIT),
                    'X-RateLimit-Remaining-Daily': '0',
                    'Retry-After': str(int((next_midnight - now).total_seconds()))
                }

            # 2. Check Per-Minute Rate Limits (RPM: 100 req/min, TPM: 40,000 tokens/min)
            RPM_LIMIT = 100
            TPM_LIMIT = 40000

            if not quota.rpm_window_start or (now - quota.rpm_window_start).total_seconds() >= 60:
                quota.rpm_window_start = now
                quota.rpm_count = 0
                quota.tpm_count = 0

            if quota.rpm_count + 1 > RPM_LIMIT:
                retry_seconds = max(1, 60 - int((now - quota.rpm_window_start).total_seconds()))
                return False, f"Per-minute request limit exceeded ({RPM_LIMIT} req/min). Please slow down and retry in {retry_seconds}s.", {
                    'X-RateLimit-Limit-RPM': str(RPM_LIMIT),
                    'X-RateLimit-Remaining-RPM': '0',
                    'Retry-After': str(retry_seconds)
                }

            estimated_total_tokens = prompt_tokens + completion_tokens
            if quota.tpm_count + estimated_total_tokens > TPM_LIMIT:
                retry_seconds = max(1, 60 - int((now - quota.rpm_window_start).total_seconds()))
                return False, f"Per-minute token limit exceeded ({TPM_LIMIT:,} tokens/min). Please retry in {retry_seconds}s.", {
                    'X-RateLimit-Limit-TPM': str(TPM_LIMIT),
                    'X-RateLimit-Remaining-TPM': '0',
                    'Retry-After': str(retry_seconds)
                }

            # 3. Check 4-Hour Window Rate Limit (250 req / 4h)
            FOUR_HOUR_LIMIT = 250
            if not quota.window_4h_start or (now - quota.window_4h_start).total_seconds() >= 14400:
                quota.window_4h_start = now
                quota.window_4h_count = 0

            if quota.window_4h_count + 1 > FOUR_HOUR_LIMIT:
                retry_seconds = max(1, 14400 - int((now - quota.window_4h_start).total_seconds()))
                hours_left = round(retry_seconds / 3600, 1)
                return False, f"4-hour tumbling rate limit reached ({FOUR_HOUR_LIMIT} requests / 4 hours). Please try again in ~{hours_left} hours.", {
                    'X-RateLimit-Limit-4H': str(FOUR_HOUR_LIMIT),
                    'X-RateLimit-Remaining-4H': '0',
                    'Retry-After': str(retry_seconds)
                }

            # Atomically increment counters
            quota.requests_count += 1
            quota.tokens_count += estimated_total_tokens
            quota.rpm_count += 1
            quota.tpm_count += estimated_total_tokens
            quota.window_4h_count += 1
            quota.save()

            headers = {
                'X-RateLimit-Limit-Daily': str(DAILY_QUOTA_LIMIT),
                'X-RateLimit-Remaining-Daily': str(max(0, DAILY_QUOTA_LIMIT - quota.requests_count)),
                'X-RateLimit-Limit-RPM': str(RPM_LIMIT),
                'X-RateLimit-Remaining-RPM': str(max(0, RPM_LIMIT - quota.rpm_count)),
                'X-RateLimit-Limit-TPM': str(TPM_LIMIT),
                'X-RateLimit-Remaining-TPM': str(max(0, TPM_LIMIT - quota.tpm_count)),
            }

            return True, None, headers
    except Exception as e:
        logger.error(f"Error checking rate limits: {e}", exc_info=True)
        # Fail-closed behavior to prevent abuse/bypassing of limits during DB load
        return False, "Rate limit service temporarily unavailable. Please try again later.", {}

