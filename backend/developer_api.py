from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import hashlib
import json
import time
from backend.models import DeveloperApiKey, Api, Setting
from backend.encryption import decrypt_api_key
from backend.hero_model import Baymax
from infinsight.Llm import generate_analyst_response
from backend.usage_tracker import log_api_request, log_activity, estimate_token_count


def _error_response(message, status_code=400, user=None, dev_key=None, request=None, model="baymax-4.5", latency_ms=0, endpoint="/api/v1/chat/completions", error_type=None, error_code=None):
    log_api_request(
        user=user,
        developer_key=dev_key,
        endpoint=endpoint,
        request_source="developer_api",
        model_used=model,
        status_code=status_code,
        error_message=message,
        latency_ms=latency_ms,
        request=request
    )
    if status_code == 429 and user:
        log_activity(
            user=user,
            action="RATE_LIMIT_EXCEEDED",
            details="Rate limit exceeded.",
            request=request
        )
    if not error_type:
        if status_code == 401:
            error_type = "invalid_request_error"
        elif status_code == 403:
            error_type = "permission_error"
        elif status_code == 429:
            error_type = "rate_limit_error"
        elif status_code >= 500:
            error_type = "api_error"
        else:
            error_type = "invalid_request_error"

    error_dict = {
        "message": message,
        "type": error_type,
        "param": None,
        "code": error_code
    }
    return JsonResponse({"error": error_dict}, status=status_code)


def authenticate_developer_key(request, required_scope="full", endpoint="/api/v1/chat/completions"):
    """
    Authenticate developer API key and validate expiration and scope.
    Scopes:
    - 'full': Has access to chat completions, model catalog, and usage metrics.
    - 'read': Restricted to read-only queries (usage and models). Cannot make chat completion calls.
    
    Returns:
        (dev_key, user, error_response)
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        err = _error_response(
            "Missing or invalid Authorization header. Format: Bearer <your_developer_api_key>",
            status_code=401,
            request=request,
            endpoint=endpoint
        )
        return None, None, err

    api_key = auth_header.split(" ")[1].strip()
    hashed_key = hashlib.sha256(api_key.encode()).hexdigest()

    try:
        dev_key = DeveloperApiKey.objects.get(key=hashed_key)
    except DeveloperApiKey.DoesNotExist:
        err = _error_response("Invalid API key provided.", status_code=401, request=request, endpoint=endpoint, error_code="invalid_api_key")
        return None, None, err

    # Check key active status (Paused/Disabled key check)
    if not dev_key.is_active:
        err = _error_response(
            "API key is deactivated/paused. Please reactivate this key in the platform console to continue.",
            status_code=401,
            user=dev_key.user,
            dev_key=dev_key,
            request=request,
            endpoint=endpoint,
            error_code="key_disabled"
        )
        return None, None, err

    # Check key expiration
    if dev_key.expires_at and timezone.now() > dev_key.expires_at:
        err = _error_response("API key has expired.", status_code=401, user=dev_key.user, dev_key=dev_key, request=request, endpoint=endpoint, error_code="key_expired")
        return None, None, err

    # Enforce scope permissions
    if required_scope == "full" and dev_key.scope != "full":
        err = _error_response(
            "Permission denied: API key has read-only permissions and cannot perform inference requests. A key with 'full' scope is required.",
            status_code=403,
            user=dev_key.user,
            dev_key=dev_key,
            request=request,
            endpoint=endpoint,
            error_code="insufficient_scope"
        )
        return None, None, err

    # Update last used timestamp
    dev_key.last_used = timezone.now()
    dev_key.save(update_fields=['last_used'])

    return dev_key, dev_key.user, None


@csrf_exempt
def developer_chat_completions(request):
    t0 = time.time()
    if request.method != "POST":
        return _error_response("Method not allowed", 405, request=request)
    
    # 1. Authenticate API Key with 'full' scope requirement
    dev_key, user, auth_err = authenticate_developer_key(request, required_scope="full", endpoint="/api/v1/chat/completions")
    if auth_err:
        return auth_err
    
    # 2. Parse Request Body Early for logging context
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _error_response("Invalid JSON", 400, user=user, dev_key=dev_key, request=request)
        
    model_input = data.get("model", "baymax-4.5")
    model_raw = str(model_input).strip().rstrip(":").lower()

    NOT_AVAILABLE_MODELS = ["halo", "zeno", "zuno", "infinsight"]
    ALLOWED_MODELS = ["baymax-4.5", "baymax"]

    if model_raw in NOT_AVAILABLE_MODELS:
        return _error_response(f"Model '{model_raw}' is currently not available.", 400, user=user, dev_key=dev_key, request=request, model=model_raw)

    if model_raw not in ALLOWED_MODELS:
        return _error_response(f"Invalid model: '{model_input}'. Allowed active model is 'baymax-4.5'.", 400, user=user, dev_key=dev_key, request=request, model=model_raw)

    model = "baymax-4.5"
    messages = data.get("messages", [])
    req_type = data.get("type", "text").lower()
    allow_search = bool(data.get("search", False))
    stream = bool(data.get("stream", False))
    
    # 3. Persistent Rate & Quota Enforcement (1,000 req/day, 100 req/min, 40k tpm, 250 req/4h)
    from backend.usage_tracker import check_and_increment_rate_limits, estimate_token_count
    
    prompt_tokens_est = estimate_token_count(json.dumps(messages))
    allowed, rate_error, rate_headers = check_and_increment_rate_limits(user, prompt_tokens=prompt_tokens_est)
    if not allowed:
        err_resp = _error_response(rate_error, 429, user=user, dev_key=dev_key, request=request, model=model)
        for h_k, h_v in rate_headers.items():
            err_resp[h_k] = h_v
        return err_resp

    if not messages:
        return _error_response("Messages array is required", 400, user=user, dev_key=dev_key, request=request, model=model)
        
    # Get user's own keys from Heros profile
    gemini_key, openrouter_key, groq_key = None, None, None
    for api in Api.objects.filter(user=user):
        if api.model_name == 'Gemini':
            gemini_key = decrypt_api_key(api.api_key_encrypted)
        elif api.model_name == 'OpenRouter':
            openrouter_key = decrypt_api_key(api.api_key_encrypted)
        elif api.model_name == 'Groq':
            groq_key = decrypt_api_key(api.api_key_encrypted)

    # Format history and extract system message
    chat_history = []
    current_message = ""
    dev_system_msg = ""
    
    for idx, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            dev_system_msg += content + "\n"
        elif idx == len(messages) - 1 and role == "user":
            current_message = content
        else:
            chat_history.append({"role": role, "content": content})

    reply = ""
    audio_b64 = None

    if model in ["baymax-4.5", "baymax"]:
        # Initialize Baymax specifically for developer API
        baymax = Baymax(
            gemini_key=gemini_key,
            openrouter_key=openrouter_key,
            groq_key=groq_key,
            chat_history=chat_history,
            temporary=True,
            is_fast=False,
            is_superuser=user.is_superuser
        )
        
        try:
            from backend.Nlp import preprocess
            if allow_search:
                nlp_result = preprocess(current_message, source='text')
                baymax.nlp_result = nlp_result
                
            reply = baymax.handle_developer_api(
                text=current_message,
                req_type=req_type,
                allow_search=allow_search,
                dev_system_msg=dev_system_msg.strip()
            )
            
            if req_type == "voice" and reply:
                try:
                    from gtts import gTTS
                    import io
                    import base64
                    tts = gTTS(text=reply, lang='en', slow=False)
                    fp = io.BytesIO()
                    tts.write_to_fp(fp)
                    fp.seek(0)
                    audio_b64 = base64.b64encode(fp.read()).decode('utf-8')
                except Exception as e:
                    print(f"TTS Error: {e}")
        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            return _error_response(f"Baymax error: {str(e)}", 500, user=user, dev_key=dev_key, request=request, model=model, latency_ms=latency_ms)
            
    elif model == "infinsight":
        if not gemini_key:
            latency_ms = int((time.time() - t0) * 1000)
            return _error_response("Infinsight requires a Gemini API key configured in your Heros profile.", 403, user=user, dev_key=dev_key, request=request, model=model, latency_ms=latency_ms)
        try:
            reply, used_model = generate_analyst_response(
                user_message=current_message,
                context_chunks=[],
                gemini_api_key=gemini_key,
                chat_history=chat_history
            )
        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            return _error_response(f"Infinsight error: {str(e)}", 500, user=user, dev_key=dev_key, request=request, model=model, latency_ms=latency_ms)
    else:
        latency_ms = int((time.time() - t0) * 1000)
        return _error_response(f"Unsupported model: {model}. Supported models are 'baymax-4.5' and 'infinsight'", 400, user=user, dev_key=dev_key, request=request, model=model, latency_ms=latency_ms)
        
    # Calculate token estimation & execution latency
    latency_ms = int((time.time() - t0) * 1000)
    prompt_str = dev_system_msg + current_message + "".join([m.get("content", "") for m in chat_history])
    prompt_tokens = estimate_token_count(prompt_str)
    completion_tokens = estimate_token_count(reply)
    total_tokens = prompt_tokens + completion_tokens
    
    # 4. Save detailed request log to database
    log_api_request(
        user=user,
        developer_key=dev_key,
        endpoint="/api/v1/chat/completions",
        request_source="developer_api",
        model_used=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        status_code=200,
        request=request
    )

    if stream:
        cmpl_id = f"chatcmpl-{int(time.time() * 1000)}"
        created_ts = int(time.time())

        def stream_generator():
            # Initial chunk providing assistant role
            initial_chunk = {
                "id": cmpl_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None
                    }
                ]
            }
            yield f"data: {json.dumps(initial_chunk)}\n\n"

            # Stream words/token pieces
            words = reply.split(" ")
            chunk_buffer = []
            for idx, word in enumerate(words):
                chunk_buffer.append(word)
                if len(chunk_buffer) >= 2 or idx == len(words) - 1:
                    content_piece = " ".join(chunk_buffer)
                    if idx < len(words) - 1:
                        content_piece += " "
                    chunk_buffer = []

                    data_chunk = {
                        "id": cmpl_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": content_piece},
                                "finish_reason": None
                            }
                        ]
                    }
                    yield f"data: {json.dumps(data_chunk)}\n\n"

            # Final finish_reason chunk
            final_chunk = {
                "id": cmpl_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }
                ]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        streaming_resp = StreamingHttpResponse(
            stream_generator(),
            content_type="text/event-stream"
        )
        streaming_resp["Cache-Control"] = "no-cache"
        streaming_resp["X-Accel-Buffering"] = "no"
        if 'rate_headers' in locals() and rate_headers:
            for hk, hv in rate_headers.items():
                streaming_resp[hk] = hv
        return streaming_resp

    message_data = {
        "role": "assistant",
        "content": reply
    }
    if audio_b64:
        message_data["audio"] = {
            "format": "mp3",
            "data": audio_b64
        }

    response_data = {
        "id": "chatcmpl-" + str(int(time.time())),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message_data,
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens
        }
    }
    response = JsonResponse(response_data)
    if 'rate_headers' in locals() and rate_headers:
        for hk, hv in rate_headers.items():
            response[hk] = hv
    return response


@csrf_exempt
def developer_usage(request):
    """
    Query developer usage and quota statistics using an API key.
    Accessible by both 'read' and 'full' scope API keys.
    Endpoint: GET /api/v1/usage
    """
    t0 = time.time()
    if request.method != "GET":
        return _error_response("Method not allowed", 405, request=request, endpoint="/api/v1/usage")
        
    dev_key, user, auth_err = authenticate_developer_key(request, required_scope="read", endpoint="/api/v1/usage")
    if auth_err:
        return auth_err

    from backend.models import ApiUsageTracking, UserDailyQuota
    from django.db.models import Count, Sum, Avg

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Fetch user's overall developer API usage today
    today_stats = ApiUsageTracking.objects.filter(
        user=user,
        request_source="developer_api",
        timestamp__gte=today_start
    ).aggregate(
        total_requests=Count('id'),
        total_tokens=Sum('tokens_used'),
        total_prompt=Sum('prompt_tokens'),
        total_completion=Sum('completion_tokens'),
        total_cost=Sum('estimated_cost'),
        avg_latency=Avg('latency_ms')
    )

    # Key-specific usage stats today
    key_stats = ApiUsageTracking.objects.filter(
        developer_key=dev_key,
        timestamp__gte=today_start
    ).aggregate(
        key_requests=Count('id'),
        key_tokens=Sum('tokens_used')
    )

    quota_record = UserDailyQuota.objects.filter(user=user, date=today_start.date()).first()
    requests_today = quota_record.requests_count if quota_record else (today_stats["total_requests"] or 0)
    daily_limit = 1000

    latency_ms = int((time.time() - t0) * 1000)

    # Log successful usage read request
    log_api_request(
        user=user,
        developer_key=dev_key,
        endpoint="/api/v1/usage",
        request_source="developer_api",
        model_used="none",
        status_code=200,
        latency_ms=latency_ms,
        request=request
    )

    return JsonResponse({
        "status": "success",
        "key": {
            "name": dev_key.name,
            "scope": dev_key.scope,
            "environment": dev_key.environment,
            "is_active": dev_key.is_active,
            "created_at": dev_key.created_at.isoformat() if dev_key.created_at else None,
            "expires_at": dev_key.expires_at.isoformat() if dev_key.expires_at else None,
            "last_used": dev_key.last_used.isoformat() if dev_key.last_used else None
        },
        "quota": {
            "daily_limit": daily_limit,
            "requests_today": requests_today,
            "remaining_requests": max(0, daily_limit - requests_today)
        },
        "today_usage": {
            "total_requests": today_stats["total_requests"] or 0,
            "total_tokens": today_stats["total_tokens"] or 0,
            "prompt_tokens": today_stats["total_prompt"] or 0,
            "completion_tokens": today_stats["total_completion"] or 0,
            "estimated_cost_usd": round(float(today_stats["total_cost"] or 0.0), 6),
            "key_requests_today": key_stats["key_requests"] or 0,
            "key_tokens_today": key_stats["key_tokens"] or 0
        }
    })


@csrf_exempt
def developer_models(request):
    """
    List available models. Accessible by both 'read' and 'full' scope API keys.
    Endpoint: GET /api/v1/models
    """
    t0 = time.time()
    if request.method != "GET":
        return _error_response("Method not allowed", 405, request=request, endpoint="/api/v1/models")

    dev_key, user, auth_err = authenticate_developer_key(request, required_scope="read", endpoint="/api/v1/models")
    if auth_err:
        return auth_err

    latency_ms = int((time.time() - t0) * 1000)
    log_api_request(
        user=user,
        developer_key=dev_key,
        endpoint="/api/v1/models",
        request_source="developer_api",
        model_used="none",
        status_code=200,
        latency_ms=latency_ms,
        request=request
    )

    return JsonResponse({
        "object": "list",
        "data": [
            {
                "id": "baymax-4.5",
                "object": "model",
                "created": 1710000000,
                "owned_by": "heros-ai",
                "permission": [],
                "root": "baymax-4.5",
                "parent": None
            }
        ]
    })
