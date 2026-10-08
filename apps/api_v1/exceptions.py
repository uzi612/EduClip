"""Global error formatting (BACKEND-06): every API failure uses one envelope.

Envelope: {"error": {"code", "message", "details", "request_id", "retryable"}}
Covers DRF validation/throttle/auth errors, Django 404/403, uncaught 500s,
and unmatched URLs (not_found_json, wired as handler404 in config/urls.py).
See docs/API_SPECIFICATION.md §12.
"""
import logging

from django.http import JsonResponse
from rest_framework.exceptions import APIException, Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def _request_id(request):
    if request is None:
        return "unknown"
    rid = getattr(request, "request_id", None)
    if rid:
        return rid
    try:
        return request.headers.get("X-Request-Id", "unknown") or "unknown"
    except Exception:
        return "unknown"


def _envelope(code, message, status_code, request, details=None, retryable=False):
    return Response(
        {"error": {"code": code, "message": message, "details": details or {},
                   "request_id": _request_id(request), "retryable": retryable}},
        status=status_code,
    )


def educlip_exception_handler(exc, context):
    """DRF EXCEPTION_HANDLER: normalize every in-view error to the envelope."""
    request = context.get("request") if isinstance(context, dict) else None
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API exception (request_id=%s)", _request_id(request))
        return _envelope("INTERNAL_ERROR", "An unexpected error occurred.", 500,
                         request, retryable=True)
    if isinstance(exc, Throttled):
        wait = getattr(exc, "wait", None)
        wait_sec = int(wait) if wait else None
        resp = _envelope("RATE_LIMITED", "Request was throttled.", 429, request,
                         {"retry_after_sec": wait_sec}, retryable=True)
        if wait_sec is not None:
            resp["Retry-After"] = str(wait_sec)
        return resp
    if isinstance(exc, ValidationError):
        return _envelope("VALIDATION_ERROR", "Request validation failed.", 400,
                         request, {"fields": response.data}, retryable=False)
    status_code = response.status_code
    if status_code == 404:
        return _envelope("NOT_FOUND", "Not found.", 404, request, retryable=False)
    if status_code == 403:
        return _envelope("FORBIDDEN", "Permission denied.", 403, request, retryable=False)
    if status_code == 401:
        return _envelope("UNAUTHENTICATED", "Authentication required.", 401,
                         request, retryable=False)
    if isinstance(exc, APIException):
        detail = response.data.get("detail", str(exc)) if isinstance(
            response.data, dict) else str(response.data)
        return _envelope("API_ERROR", str(detail), status_code, request,
                         retryable=status_code >= 500)
    return response


def not_found_json(request, exception=None):
    """handler404: unmatched URLs return the envelope (not Django's HTML page)."""
    rid = getattr(request, "request_id", "unknown") or "unknown"
    payload = {"error": {"code": "NOT_FOUND", "message": "Not found.",
                         "details": {}, "request_id": rid, "retryable": False}}
    response = JsonResponse(payload, status=404)
    response["X-Request-Id"] = rid
    return response


__all__ = ["educlip_exception_handler", "not_found_json"]
