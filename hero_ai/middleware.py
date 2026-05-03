import logging
import time
from django.http import JsonResponse

logger = logging.getLogger('django.request')

class RequestSizeLimitMiddleware:
    """
    Blocks requests that exceed a certain size to prevent DoS.
    Defaults to 20MB.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.max_bytes = 20 * 1024 * 1024  # 20MB

    def __call__(self, request):
        content_length = request.META.get('CONTENT_LENGTH')
        if content_length and int(content_length) > self.max_bytes:
            return JsonResponse({'error': 'Payload too large'}, status=413)
        return self.get_response(request)

class GlobalExceptionHandlerMiddleware:
    """
    Catches unhandled exceptions, logs them, and returns a safe 500 error.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except Exception as e:
            logger.error("Unhandled Exception: %s", str(e), exc_info=True, extra={
                'status_code': 500,
                'request': request
            })
            return JsonResponse({'status': 'fail', 'message': 'Internal Server Error'}, status=500)

class RequestMetricsMiddleware:
    """
    Logs request durations and status codes.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        duration = time.time() - start_time
        
        # Log response metrics
        if not request.path.startswith('/static/'):
            logger.info("Response metrics | path=%s | method=%s | status=%s | duration=%.3fs",
                        request.path, request.method, response.status_code, duration)
        
        return response
