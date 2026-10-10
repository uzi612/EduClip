"""Stuck-at-5% regression tests: transcript timeouts, broker-down 503,
failure logging. Run: python apps/videos/tests/test_transcript_timeout.py
(needs repo root on PYTHONPATH). No network.
"""
import os
import time
from unittest.mock import MagicMock, patch

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from django.conf import settings  # noqa: E402

if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]

import mongomock  # noqa: E402
import mongoengine as me  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

import services.youtube as youtube_svc  # noqa: E402
from services.youtube import TranscriptUnavailableError  # noqa: E402

VID = "dQw4w9WgXcQ"


def setup_module():
    me.disconnect_all()
    me.connect("educlip-test", mongo_client_class=mongomock.MongoClient)


def teardown_module():
    me.disconnect_all()


def _slow_api(*args, **kwargs):
    time.sleep(5)
    raise AssertionError("slow fetch should have timed out first")


def test_fetch_transcript_times_out():
    with patch(
        "youtube_transcript_api.YouTubeTranscriptApi", side_effect=_slow_api):
        started = time.perf_counter()
        try:
            youtube_svc.fetch_transcript(VID, timeout_sec=1)
        except TranscriptUnavailableError as exc:
            elapsed = time.perf_counter() - started
            assert "timed out" in str(exc) and exc.retryable is True
            assert elapsed < 12, f"timeout did not bound the call ({elapsed:.1f}s)"
            return
    raise AssertionError("expected TranscriptUnavailableError on hung fetch")


def test_fetch_logs_start_and_done():
    import logging

    records = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    snip = MagicMock()
    snip.start, snip.duration, snip.text = 0.0, 2.0, "hi"
    api = MagicMock()
    api.list.return_value.find_transcript.return_value.fetch.return_value = [snip]
    logger = logging.getLogger("services.youtube")
    handler = _H()
    old_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=api):
            youtube_svc.fetch_transcript(VID)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    assert any("transcript fetch start" in m and VID in m for m in records), records
    assert any("transcript fetch done" in m and "segments=1" in m for m in records), records


def test_broker_down_returns_503_not_hang():
    from apps.videos.models import Video

    Video.objects.delete()
    meta = {"title": "T", "channel": "C",
            "thumbnail": "https://i.ytimg.com/vi/x/hqdefault.jpg", "duration_sec": 600}
    with patch("apps.api_v1.views._check_redis", return_value=(True, 1)), patch(
        "services.youtube.get_video_metadata", return_value=dict(meta)), patch(
        "apps.videos.tasks.process_video_task") as task:
        task.delay.side_effect = Exception("connection refused: redis")
        r = APIClient(HTTP_HOST="testserver").post(
            "/api/v1/process-video", {"youtube_url": f"https://youtu.be/{VID}"},
            format="json")
    assert r.status_code == 503, r.content
    body = r.json()
    assert body["error"]["code"] == "WORKER_UNAVAILABLE"
    assert body["error"]["retryable"] is True
    assert Video.objects(youtube_id=VID).first().status == "failed"


def test_dead_broker_fails_fast_with_no_orphan_row():
    # The 5%-forever hang: pre-flight must reject before any DB record exists.
    import time

    from apps.videos.models import Video

    Video.objects.delete()
    with patch("apps.api_v1.views._check_redis", return_value=(False, None)):
        started = time.perf_counter()
        r = APIClient(HTTP_HOST="testserver").post(
            "/api/v1/process-video", {"youtube_url": f"https://youtu.be/{VID}"},
            format="json")
        elapsed = time.perf_counter() - started
    assert r.status_code == 503, r.content
    assert r.json()["error"]["code"] == "WORKER_UNAVAILABLE"
    assert elapsed < 10, f"pre-flight must be fast ({elapsed:.1f}s)"
    assert Video.objects(youtube_id=VID).first() is None


def test_gemini_uses_request_timeout():
    import json
    import sys
    import types

    from django.test.utils import override_settings

    from services import llm_client

    captured = {}
    module = types.ModuleType("google.generativeai")
    module.configure = lambda api_key=None: None

    class _Model:
        def __init__(self, *a, **k):
            pass

        def generate_content(self, prompt, **kwargs):
            captured.update(kwargs)
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
        with override_settings(GEMINI_API_KEY="k"):
            llm_client._call_gemini("t", "T")
    finally:
        sys.modules.clear()
        sys.modules.update(real)
    assert captured.get("request_options", {}).get("timeout") == llm_client.GEMINI_TIMEOUT_SEC


def test_disabled_captions_fail_with_trace_and_clean_422():
    import logging

    from apps.videos.models import Video
    from apps.videos.tasks import process_video_task
    from apps.videos.video_service import get_or_create_video
    from youtube_transcript_api._errors import TranscriptsDisabled

    for doc in (Video,):
        doc.objects.delete()
    meta = {"title": "T", "channel": "C",
            "thumbnail": "https://i.ytimg.com/vi/x/hqdefault.jpg", "duration_sec": 600}
    records = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record)

    api = MagicMock()
    api.list.side_effect = TranscriptsDisabled(VID)
    logger = logging.getLogger("services.youtube")
    handler = _H()
    old_level = logger.level
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=api), patch(
            "apps.videos.transcribe.fallback_transcribe.whisper_transcribe",
            side_effect=TranscriptUnavailableError("no audio tool", retryable=False)):
            # Unit: exact mapped error, no hang.
            try:
                youtube_svc.fetch_transcript(VID)
            except TranscriptUnavailableError as exc:
                assert "disabled" in str(exc).lower() and exc.retryable is False
            else:
                raise AssertionError("expected TranscriptsDisabled mapping")
            # Chain: worker records failure, API answers 422 JSON (never hangs).
            video, _ = get_or_create_video(VID, meta)
            try:
                process_video_task.run(str(video.id))
            except Exception:
                pass
            video.reload()
            # The stored error names the terminal tier; the disabled-captions
            # root cause is in the traceback logs asserted below.
            assert video.status == "failed" and video.error, video.status
            r = APIClient(HTTP_HOST="testserver").get(
                f"/api/v1/video/{video.id}/", HTTP_HOST="testserver")
            assert r.status_code == 422
            assert r.json()["error"]["code"] == "PROCESSING_FAILED"
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    assert any(getattr(r, "exc_info", None) for r in records), \
        "failure must log the stack trace"


if __name__ == "__main__":
    setup_module()
    try:
        for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
            fn()
            print(f"PASS {name}")
    finally:
        teardown_module()
    print("ALL TRANSCRIPT-TIMEOUT CHECKS PASSED")
