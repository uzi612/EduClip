"""Env wiring + broker pre-flight integration (audit fix verification).

Run: python apps/api_v1/tests/test_env_preflight.py (needs repo root on PYTHONPATH)
Proves: keys/eager flag are read from the environment, eager/memory/empty
configurations skip the Redis ping without 503s, and a dead broker fails
fast with no orphan row. MongoEngine uses in-memory mongomock.
"""
import os
import time
from unittest.mock import MagicMock, patch

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from django.conf import settings  # noqa: E402
from django.test.utils import override_settings  # noqa: E402

if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]

import mongomock  # noqa: E402
import mongoengine as me  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.videos.models import Video  # noqa: E402

VID = "dQw4w9WgXcQ"
META = {"title": "T", "channel": "C",
        "thumbnail": "https://i.ytimg.com/vi/x/hqdefault.jpg", "duration_sec": 600}


def setup_module():
    me.disconnect_all()
    me.connect("educlip-test", mongo_client_class=mongomock.MongoClient)


def teardown_module():
    me.disconnect_all()


def _post(**kwargs):
    return APIClient(HTTP_HOST="testserver").post(
        "/api/v1/process-video", {"youtube_url": f"https://youtu.be/{VID}"},
        format="json", **kwargs)


def _queued_broker_mocks():
    return (patch("services.youtube.get_video_metadata", return_value=dict(META)),
            patch("apps.videos.tasks.process_video_task"))


def test_env_keys_are_wired_to_settings():
    assert isinstance(settings.GEMINI_API_KEY, str)
    assert isinstance(settings.OPENAI_API_KEY, str)
    assert isinstance(settings.CELERY_TASK_ALWAYS_EAGER, bool)


def test_gemini_key_reaches_client():
    import json
    import sys
    import types

    from services import llm_client

    captured = {}
    module = types.ModuleType("google.generativeai")
    module.configure = lambda api_key=None: captured.setdefault("api_key", api_key)

    class _Model:
        def __init__(self, *a, **k):
            pass

        def generate_content(self, prompt, **kwargs):
            canned = {"summary": "S",
                      "chapters": [{"title": "A", "start_sec": 0, "end_sec": 600,
                                    "summary": ""}],
                      "keywords": [], "flashcards": []}
            return types.SimpleNamespace(text=json.dumps(canned))

    module.GenerativeModel = _Model
    real = dict(sys.modules)
    sys.modules["google.generativeai"] = module
    sys.modules.setdefault("google", types.ModuleType("google"))
    try:
        with override_settings(GEMINI_API_KEY="wired-key-123"):
            llm_client.clear_cache()
            out = llm_client.analyze_video(
                [{"start": 0.0, "duration": 5.0, "text": "alpha beta"}],
                "T", use_cache=False)
    finally:
        sys.modules.clear()
        sys.modules.update(real)
    assert captured.get("api_key") == "wired-key-123", captured
    assert out["_meta"]["provider"] == "gemini"


def test_eager_bypasses_dead_broker():
    Video.objects.delete()
    meta_patch, task_patch = _queued_broker_mocks()
    with override_settings(CELERY_TASK_ALWAYS_EAGER=True), patch(
        "apps.api_v1.views._check_redis", return_value=(False, None)), \
            meta_patch, task_patch as task:
        task.delay.return_value = MagicMock(id="task-eager")
        r = _post()
    assert r.status_code == 202, r.content
    assert Video.objects(youtube_id=VID).first() is not None


def test_empty_and_memory_broker_skip_ping():
    for url in ("", "memory://"):
        Video.objects.delete()
        meta_patch, task_patch = _queued_broker_mocks()
        with override_settings(CELERY_BROKER_URL=url), patch(
            "apps.api_v1.views._check_redis",
            side_effect=AssertionError("must not ping")), \
                meta_patch, task_patch as task:
            task.delay.return_value = MagicMock(id="task-x")
            r = _post()
        assert r.status_code == 202, (url, r.content)


def test_dead_broker_fails_fast_without_orphan():
    Video.objects.delete()
    with patch("apps.api_v1.views._check_redis", return_value=(False, None)), \
            override_settings(CELERY_TASK_ALWAYS_EAGER=False,
                              CELERY_BROKER_URL="redis://localhost:6379/0"):
        started = time.perf_counter()
        r = _post()
        elapsed = time.perf_counter() - started
    assert r.status_code == 503, r.content
    assert r.json()["error"]["code"] == "WORKER_UNAVAILABLE"
    assert elapsed < 10, elapsed
    assert Video.objects(youtube_id=VID).first() is None


def test_debug_rates_relaxed_for_local_review():
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    if settings.DEBUG:
        assert rates == {"anon": "100/min", "process_video": "100/min"}, rates
    else:
        assert rates == {"anon": "60/min", "process_video": "10/hour"}, rates


if __name__ == "__main__":
    setup_module()
    try:
        for name, fn in sorted([(k, v) for k, v in globals().items()
                                if k.startswith("test_")]):
            fn()
            print(f"PASS {name}")
    finally:
        teardown_module()
    print("ALL ENV-PREFLIGHT CHECKS PASSED")
