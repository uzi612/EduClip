"""BACKEND-06 verification: error envelopes, middleware, LLM backoff.

Run: python apps/api_v1/tests/test_error_handling.py (needs repo root on PYTHONPATH)
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from django.conf import settings  # noqa: E402

if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]

from unittest.mock import MagicMock, patch  # noqa: E402

from rest_framework.exceptions import Throttled, ValidationError  # noqa: E402
from rest_framework.test import APIClient, APIRequestFactory  # noqa: E402

from apps.api_v1.exceptions import educlip_exception_handler  # noqa: E402
from apps.api_v1.throttles import ProcessVideoThrottle  # noqa: E402
from services import llm_client  # noqa: E402
from services.llm_client import LLMError  # noqa: E402


def _client():
    return APIClient(HTTP_HOST="testserver")


def _ctx(path="/api/v1/process-video"):
    factory = APIRequestFactory()
    req, _ = factory.get(path), None
    from rest_framework.request import Request

    drf_req = Request(req)
    drf_req.request_id = "req_test123"
    return {"request": drf_req}


def test_unknown_path_returns_not_found_envelope():
    # handler404 only serves JSON with DEBUG=False (as in prod); dev shows HTML.
    from django.test.utils import override_settings

    with override_settings(DEBUG=False):
        r = _client().get("/api/v1/does-not-exist/")
    assert r.status_code == 404, r.status_code
    body = r.json()
    assert body["error"]["code"] == "NOT_FOUND" and body["error"]["retryable"] is False
    assert r["X-Request-Id"], "request id must be echoed"


def test_throttle_returns_rate_limited_envelope():
    import mongomock
    import mongoengine as me
    from django.core.cache import caches

    me.disconnect_all()
    me.connect("educlip-test", mongo_client_class=mongomock.MongoClient)
    try:
        from apps.videos.models import Video

        Video.objects.delete()
        caches["default"].clear()
        meta = {"title": "T", "channel": "C",
                "thumbnail": "https://i.ytimg.com/vi/x/hqdefault.jpg", "duration_sec": 600}
        ids = ["dQw4w9WgXcQ", "9bZkp7q19f0", "jNQXAC9IVRw"]
        with patch.object(ProcessVideoThrottle, "THROTTLE_RATES",
                          {"process_video": "2/min"}), patch(
            "services.youtube.get_video_metadata", return_value=dict(meta)), patch(
                "apps.videos.tasks.process_video_task") as task:
            task.delay.return_value = MagicMock(id="t")
            codes = []
            last = None
            for i in ids:
                last = _client().post(
                    "/api/v1/process-video",
                    {"youtube_url": f"https://youtu.be/{i}"}, format="json")
                codes.append(last.status_code)
        assert codes == [202, 202, 429], codes
        body = last.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert body["error"]["retryable"] is True
        assert body["error"]["details"]["retry_after_sec"] is not None
        assert last["Retry-After"], "Retry-After header required"
    finally:
        me.disconnect_all()


def test_handler_validation_error():
    resp = educlip_exception_handler(ValidationError({"f": ["bad"]}), _ctx())
    assert resp.status_code == 400
    body = resp.data["error"]
    assert body["code"] == "VALIDATION_ERROR" and body["request_id"] == "req_test123"


def test_handler_throttled():
    resp = educlip_exception_handler(Throttled(wait=30), _ctx())
    assert resp.status_code == 429
    assert resp.data["error"]["code"] == "RATE_LIMITED"
    assert resp.data["error"]["details"]["retry_after_sec"] == 30
    assert resp["Retry-After"] == "30"


def test_handler_uncaught_is_500_with_request_id():
    resp = educlip_exception_handler(RuntimeError("kaboom"), _ctx())
    assert resp.status_code == 500
    body = resp.data["error"]
    assert body["code"] == "INTERNAL_ERROR" and body["request_id"] == "req_test123"
    assert body["retryable"] is True


def test_request_logging_emits_line():
    import logging

    records = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger("educlip.requests")
    handler = _H()
    old_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        _client().get("/api/v1/health/", HTTP_HOST="localhost")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    assert any("GET /api/v1/health/" in m and "id=" in m for m in records), records


def test_llm_backoff_is_exponential_with_jitter():
    llm_client.clear_cache()
    segs = [{"start": 0.0, "duration": 5.0, "text": "atp"}]
    sleeps = []
    with patch.object(llm_client, "_call_openai",
                      side_effect=LLMError("timeout", retryable=True)), patch(
        "random.uniform", return_value=0.0), patch(
        "services.llm_client.time.sleep", side_effect=lambda s: sleeps.append(s)):
        try:
            llm_client.analyze_video(segs, "T", provider="openai", use_cache=False)
        except LLMError:
            pass
        else:
            raise AssertionError("expected LLMError after retries exhausted")
    assert sleeps == [1.0, 2.0, 4.0], sleeps


if __name__ == "__main__":
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    print("ALL BACKEND-06 CHECKS PASSED")
