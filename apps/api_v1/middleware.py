"""Request middleware (BACKEND-06): correlation IDs + access logging.

RequestIdMiddleware mints (or echoes) X-Request-Id so every log line, error
envelope, and Sentry event for one call shares an id. RequestLoggingMiddleware
logs one structured line per request: method, path, status, duration, id.
"""
import logging
import time
import uuid

request_logger = logging.getLogger("educlip.requests")


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.headers.get("X-Request-Id", "") or uuid.uuid4().hex[:12]
        response = self.get_response(request)
        response["X-Request-Id"] = request.request_id
        return response


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        response = self.get_response(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        request_logger.info(
            "%s %s -> %s (%sms) id=%s", request.method, request.get_full_path(),
            response.status_code, duration_ms,
            getattr(request, "request_id", "-"),
        )
        return response


__all__ = ["RequestIdMiddleware", "RequestLoggingMiddleware", "request_logger"]
