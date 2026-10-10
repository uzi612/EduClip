"""API v1 views: health (SETUP-01) + video processing (BACKEND-03)."""
import logging
import time

from django.conf import settings
from mongoengine.errors import ValidationError as MongoValidationError
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from apps.api_v1.exceptions import request_id_of
from apps.api_v1.serializers import ProcessVideoSerializer
from apps.api_v1.throttles import ProcessVideoThrottle

logger = logging.getLogger(__name__)


def _check_redis():
    try:
        import redis

        r = redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2)
        start = time.perf_counter()
        r.ping()
        return True, int((time.perf_counter() - start) * 1000)
    except Exception:
        return False, None


@api_view(["POST"])
@throttle_classes([ProcessVideoThrottle])
def process_video(request):
    """Submit a YouTube URL for async processing (BACKEND-03).

    202 new/processing job, 200 already-ready dedupe, 400 invalid URL,
    422 unavailable video, 429 throttled, 503 DB unconfigured.
    Heavy work always runs in Celery — this view only validates,
    dedupes, persists the queued record, and dispatches the task.
    See docs/API_SPECIFICATION.md §3.
    """
    from apps.videos.db import ensure_mongoengine
    from apps.videos.tasks import process_video_task
    from apps.videos.video_service import get_or_create_video
    from services.youtube import TranscriptUnavailableError, get_video_metadata

    try:
        ensure_mongoengine()
    except RuntimeError as exc:
        rid = request_id_of(request)
        return Response({"error": {"code": "SERVICE_UNAVAILABLE", "message": str(exc),
                                    "details": {}, "request_id": rid,
                                    "retryable": True}}, status=503)

    serializer = ProcessVideoSerializer(data=request.data)
    if not serializer.is_valid():
        errors = serializer.errors
        code = "INVALID_URL" if set(errors) == {"youtube_url"} else "VALIDATION_ERROR"
        rid = request_id_of(request)
        return Response({"error": {"code": code, "message": "; ".join(
            f"{f}: {', '.join(map(str, m))}" for f, m in errors.items()),
            "details": {"fields": errors}, "request_id": rid,
            "retryable": False}}, status=400)

    # Pre-flight: fail fast when no worker could ever pick this up. Without
    # it a dead broker accepts the POST and strands the video at 5% forever.
    # Skipped entirely when tasks run eagerly (synchronous inline execution
    # needs no broker) or when no broker URL is configured (nothing to ping —
    # dispatch itself still fails loudly via the delay guard below).
    broker_url = getattr(settings, "CELERY_BROKER_URL", "") or ""
    if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False) and broker_url:
        broker_ok, _ = _check_redis()
        if not broker_ok:
            rid = request_id_of(request)
            logger.warning("worker pre-flight failed: request_id=%s", rid)
            return Response({"error": {
                "code": "WORKER_UNAVAILABLE",
                "message": "Video workers are unavailable (message broker unreachable). "
                           "Start Redis and a Celery worker, then retry.",
                "details": {}, "request_id": rid, "retryable": True}}, status=503)

    youtube_id = serializer.youtube_id
    idempotency_key = request.headers.get("Idempotency-Key", "")
    try:
        metadata = get_video_metadata(youtube_id)
    except TranscriptUnavailableError as exc:
        rid = request_id_of(request)
        return Response({"error": {"code": "VIDEO_UNAVAILABLE", "message": str(exc),
                                    "details": {}, "request_id": rid,
                                    "retryable": exc.retryable}}, status=422)
    try:
        video, created = get_or_create_video(
            youtube_id, metadata, idempotency_key=idempotency_key)
    except MongoValidationError as exc:
        rid = request_id_of(request)
        return Response({"error": {"code": "VIDEO_UNAVAILABLE",
                                    "message": f"Video metadata incomplete: {exc}",
                                    "details": {}, "request_id": rid,
                                    "retryable": False}}, status=422)

    video_id = str(video.id)
    poll_url = f"/api/v1/video/{video_id}/"
    if not created and video.status == "ready":
        return Response({"video_id": video_id, "youtube_id": youtube_id,
                         "status": "ready", "poll_url": poll_url}, status=200)
    if not created:
        return Response({"video_id": video_id, "youtube_id": youtube_id,
                         "status": video.status, "progress": video.progress,
                         "poll_url": poll_url}, status=202)
    try:
        task = process_video_task.delay(video_id)
    except Exception as exc:
        # Broker down (no Redis/worker): without this the video sits at 5%
        # forever with no error. Fail loudly instead of hanging the UI.
        rid = request_id_of(request)
        logger.exception("task dispatch failed: video_id=%s request_id=%s err=%s",
                         video_id, rid, exc)
        video.update(set__status="failed",
                     set__error=f"Worker unavailable, retry later: {exc}"[:500])
        return Response({"error": {"code": "WORKER_UNAVAILABLE",
                                    "message": "Video workers are unavailable, retry later.",
                                    "details": {}, "request_id": rid,
                                    "retryable": True}}, status=503)
    video.update(set__task_id=task.id)
    logger.info("task dispatched: video_id=%s task_id=%s youtube_id=%s request_id=%s",
                video_id, task.id, youtube_id, request_id_of(request))
    return Response({"video_id": video_id, "youtube_id": youtube_id, "task_id": task.id,
                     "status": "processing", "progress": 0.05, "poll_url": poll_url,
                     "estimated_seconds": 45}, status=202)


@api_view(["GET"])
def health(request):
    from services.mongo import ping_mongo

    mongo_ok, mongo_ms = ping_mongo()
    redis_ok, redis_ms = _check_redis()
    degraded = not (mongo_ok and redis_ok)
    status_code = 200 if not degraded else 503
    return Response(
        {
            "status": "ok" if not degraded else "degraded",
            "version": settings.EDUCLIP_VERSION,
            "checks": {
                "mongodb": f"{'ok' if mongo_ok else 'down'}"
                + (f" ({mongo_ms}ms)" if mongo_ms is not None else ""),
                "redis": f"{'ok' if redis_ok else 'down'}"
                + (f" ({redis_ms}ms)" if redis_ms is not None else ""),
            },
        },
        status=status_code,
    )
