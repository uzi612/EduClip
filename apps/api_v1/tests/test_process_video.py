"""BACKEND-03 verification: POST /api/v1/process-video + Celery task.

Run: python apps/api_v1/tests/test_process_video.py (needs repo root on PYTHONPATH)
MongoEngine uses in-memory mongomock; Celery task + metadata are mocked.
"""
import os
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

from apps.analytics.models import Analytics  # noqa: E402
from apps.flashcards.models import Flashcard  # noqa: E402
from apps.videos.models import Video  # noqa: E402
from apps.videos.tasks import process_video_task  # noqa: E402
from services.youtube import TranscriptUnavailableError  # noqa: E402

VID = "dQw4w9WgXcQ"
URL = f"https://www.youtube.com/watch?v={VID}"
META = {"title": "T", "channel": "C",
        "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "duration_sec": 600}
API = "/api/v1/process-video"

ANALYSIS = {
    "summary": "S",
    "chapters": [{"index": 0, "title": "A", "start_sec": 0, "end_sec": 600,
                  "summary": "", "keyword_refs": []}],
    "keywords": [{"term": "atp", "score": 0.9, "count": 5}],
    "flashcards": [{"front": "Q?", "back": "A.", "timestamp_sec": 10},
                   {"front": "Q2?", "back": "A2.", "timestamp_sec": 20}],
    "stats": {"word_count": 10, "reading_minutes": 1,
              "avg_words_per_min": 10, "top_keywords": ["atp"]},
    "complexity": {"type_token_ratio": 0.5, "avg_words_per_sentence": 5.0,
                   "long_word_ratio": 0.1},
    "degraded": False,
}


def setup_module():
    me.disconnect_all()
    me.connect("educlip-test", mongo_client_class=mongomock.MongoClient)


def teardown_module():
    me.disconnect_all()


def _clean():
    for doc in (Flashcard, Analytics, Video):
        doc.objects.delete()


def _client():
    return APIClient(HTTP_HOST="testserver")


def _post(client, url=URL, key="key-1"):
    return client.post(API, {"youtube_url": url}, format="json",
                       HTTP_IDEMPOTENCY_KEY=key)


def _healthy_broker():
    """Pre-flight patch: tests assume a reachable worker broker."""
    return patch("apps.api_v1.views._check_redis", return_value=(True, 1))


def test_submit_queues_job():
    _clean()
    with patch("services.youtube.get_video_metadata", return_value=dict(META)), patch(
        "apps.videos.tasks.process_video_task") as task, _healthy_broker():
        task.delay.return_value = MagicMock(id="task-1")
        r = _post(_client())
    assert r.status_code == 202, r.content
    body = r.json()
    assert body["status"] == "processing" and body["task_id"] == "task-1"
    assert body["poll_url"] == f"/api/v1/video/{body['video_id']}/"
    assert task.delay.call_count == 1
    assert Video.objects(youtube_id=VID).first().status == "queued"


def test_duplicate_does_not_requeue():
    _clean()
    with patch("services.youtube.get_video_metadata", return_value=dict(META)), patch(
        "apps.videos.tasks.process_video_task") as task, _healthy_broker():
        task.delay.return_value = MagicMock(id="task-1")
        first = _post(_client()).json()
        second = _post(_client(), key="key-2").json()
    assert first["video_id"] == second["video_id"]
    assert task.delay.call_count == 1


def test_ready_dedupe_returns_200():
    _clean()
    with patch("services.youtube.get_video_metadata", return_value=dict(META)), patch(
        "apps.videos.tasks.process_video_task") as task, _healthy_broker():
        task.delay.return_value = MagicMock(id="task-1")
        vid = _post(_client()).json()["video_id"]
        Video.objects(id=vid).update_one(set__status="ready", set__progress=1.0)
        r = _post(_client(), key="key-3")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert task.delay.call_count == 1


def test_invalid_url_returns_400():
    _clean()
    r = _client().post(API, {"youtube_url": "https://example.com/x"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_URL"


def test_unavailable_video_returns_422():
    _clean()
    with patch("services.youtube.get_video_metadata",
               side_effect=TranscriptUnavailableError("gone", retryable=False)), \
            _healthy_broker():
        r = _post(_client())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VIDEO_UNAVAILABLE"


def test_throttle_kicks_in():
    # NOTE: DRF binds THROTTLE_RATES at import time, so override_settings cannot
    # retune the rate — patch the throttle class directly instead.
    _clean()
    from django.core.cache import caches

    from apps.api_v1.throttles import ProcessVideoThrottle

    caches["default"].clear()  # isolate from earlier tests sharing the throttle cache
    ids = ["dQw4w9WgXcQ", "9bZkp7q19f0", "jNQXAC9IVRw"]
    with patch.object(ProcessVideoThrottle, "THROTTLE_RATES",
                       {"process_video": "2/min"}), patch(
        "services.youtube.get_video_metadata", return_value=dict(META)), patch(
            "apps.videos.tasks.process_video_task") as task, _healthy_broker():
        task.delay.return_value = MagicMock(id="t")
        codes = [_client().post(
            API, {"youtube_url": f"https://youtu.be/{i}"}, format="json"
        ).status_code for i in ids]
    assert codes[:2] == [202, 202] and codes[2] == 429, codes


def test_task_happy_path_persists_everything():
    _clean()
    from apps.videos.video_service import get_or_create_video

    video, _ = get_or_create_video(VID, META)
    segs = [{"start": 0.0, "duration": 5.0, "text": "atp atp atp"}]
    with patch("apps.videos.transcribe.transcribe_video",
               return_value=(segs, "atp atp atp", "youtube_captions")), patch(
        "apps.analytics.pipeline.run_analysis", return_value=dict(ANALYSIS)):
        out = process_video_task.run(str(video.id))
    assert out["status"] == "ready"
    video.reload()
    assert (video.status, video.progress) == ("ready", 1.0)
    assert video.flashcard_count == 2 and len(video.chapters) == 1
    assert Flashcard.objects(video_id=video).count() == 2


def test_task_failure_marks_failed():
    _clean()
    from celery.exceptions import Retry

    from apps.videos.video_service import get_or_create_video

    video, _ = get_or_create_video(VID, META)
    with patch("apps.videos.transcribe.transcribe_video",
               side_effect=TranscriptUnavailableError("nope", retryable=False)):
        try:
            process_video_task.run(str(video.id))
        except (Retry, TranscriptUnavailableError):
            pass  # eager .run re-raises; the worker would schedule the retry
        else:
            raise AssertionError("expected failure to propagate")
    video.reload()
    assert video.status == "failed" and video.error


if __name__ == "__main__":
    setup_module()
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    teardown_module()
    print("ALL BACKEND-03 CHECKS PASSED")
