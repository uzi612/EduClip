"""Health endpoint (SETUP-01): GET /api/v1/health/."""
import time

from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response


def _check_redis():
    try:
        import redis

        r = redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2)
        start = time.perf_counter()
        r.ping()
        return True, int((time.perf_counter() - start) * 1000)
    except Exception:
        return False, None


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
