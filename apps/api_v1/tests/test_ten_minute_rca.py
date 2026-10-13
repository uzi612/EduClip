"""RCA regression: a standard ~10-minute video must process end to end.

Covers the exact failure found: the Data API path requested contentDetails
but never parsed its ISO 8601 duration, so duration_sec stayed 0 and every
keyed ingestion died with 422 VIDEO_UNAVAILABLE before transcription.

Run: python apps/api_v1/tests/test_ten_minute_rca.py (needs repo root on PYTHONPATH)
Network is mocked at the SDK boundary; everything else is real.
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

from apps.videos.models import Video  # noqa: E402
from services.youtube import (  # noqa: E402
    extract_video_id,
    parse_iso8601_duration,
)

TEN_MIN_ID = "dQw4w9WgXcQ"
DURATION = 605  # PT10M5S
META = {"title": "Ten Minute Test", "channel": "Tester",
        "thumbnail": "https://i.ytimg.com/vi/x/hqdefault.jpg",
        "duration_sec": DURATION}


def setup_module():
    me.disconnect_all()
    me.connect("educlip-test", mongo_client_class=mongomock.MongoClient)


def teardown_module():
    me.disconnect_all()


def _snip(start, text):
    s = MagicMock()
    s.start, s.duration, s.text = start, 10.0, text
    return s


def test_iso8601_durations():
    assert parse_iso8601_duration("PT10M5S") == 605
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_iso8601_duration("PT45S") == 45
    assert parse_iso8601_duration("") == 0
    assert parse_iso8601_duration("garbage") == 0
    assert parse_iso8601_duration(None) == 0


def test_url_variants_normalize():
    assert extract_video_id("https://www.youtube.com/watch?v=" + TEN_MIN_ID) == TEN_MIN_ID
    assert extract_video_id("https://youtu.be/" + TEN_MIN_ID) == TEN_MIN_ID
    assert extract_video_id("https://www.youtube.com/shorts/" + TEN_MIN_ID) == TEN_MIN_ID


def test_keyed_metadata_yields_duration():
    api_resp = {"items": [{"snippet": {
        "title": "Ten Minute Test", "channelTitle": "Tester",
        "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/x/hqdefault.jpg"}}},
        "contentDetails": {"duration": "PT10M5S"}}]}
    yt = MagicMock()
    yt.videos.return_value.list.return_value.execute.return_value = api_resp
    discovery = MagicMock()
    discovery.build = MagicMock(return_value=yt)
    with patch.dict("sys.modules", {"googleapiclient": MagicMock(),
                                    "googleapiclient.discovery": discovery}):
        with override_settings(YOUTUBE_API_KEY="key"):
            from services.youtube import get_video_metadata

            meta = get_video_metadata(TEN_MIN_ID)
    assert meta["duration_sec"] == 605, meta
    assert meta["title"] == "Ten Minute Test"


def test_full_600s_pipeline_to_ready():
    from apps.analytics.validators import ChartValidator
    from apps.videos.tasks import process_video_task
    from apps.videos.video_service import get_or_create_video

    for doc in (Video,):
        doc.objects.delete()
    segs = [{"start": float(i * 10), "duration": 10.0,
             "text": f"Lesson segment {i} about alpha and beta."} for i in range(60)]
    full = " ".join(s["text"] for s in segs)
    raw = {"summary": "Ten minute lesson.",
           "chapters": [{"title": "Part 1", "start_sec": 0, "end_sec": 300, "summary": "a"},
                        {"title": "Part 2", "start_sec": 300, "end_sec": 605, "summary": "b"}],
           "keywords": [{"term": "alpha", "score": 0.9}],
           "flashcards": [{"front": "Q?", "back": "A.", "timestamp_sec": 5}]}
    with override_settings(MONGODB_ATLAS_URI="", CELERY_TASK_ALWAYS_EAGER=True):
        video, created = get_or_create_video(TEN_MIN_ID, META)
        assert created and video.duration_sec == 605
        with patch("apps.videos.transcribe.transcribe_video",
                   return_value=(segs, full, "youtube_captions")), patch(
            "apps.analytics.pipeline.llm_client.analyze_video", return_value=dict(raw)):
            out = process_video_task.run(str(video.id))
    assert out["status"] == "ready", out
    client = APIClient(HTTP_HOST="testserver")
    with override_settings(MONGODB_ATLAS_URI=""):
        detail = client.get(f"/api/v1/video/{video.id}/", HTTP_HOST="testserver").json()
    assert detail["status"] == "ready"
    assert detail["chapters"][-1]["end_sec"] == 605
    assert detail["flashcard_count"] == 1
    with override_settings(MONGODB_ATLAS_URI=""):
        graphs = client.get(f"/api/v1/video/{video.id}/analytics",
                            HTTP_HOST="testserver").json()["graphs"]
    assert ChartValidator.validate(graphs) is True
    assert len(graphs["keyword_density"]["data"]["labels"]) == 11  # 605s -> 11 buckets


def test_missing_llm_key_fails_loudly_not_silently():
    from services import llm_client
    from services.llm_client import LLMError

    llm_client.clear_cache()
    segs = [{"start": 0.0, "duration": 5.0, "text": "alpha beta"}]
    with override_settings(GEMINI_API_KEY="", OPENAI_API_KEY=""):
        try:
            llm_client.analyze_video(segs, "T", provider="gemini", use_cache=False)
        except LLMError as exc:
            assert "GEMINI_API_KEY" in str(exc) and exc.retryable is False
            return
    raise AssertionError("expected a clear missing-key LLMError")


if __name__ == "__main__":
    setup_module()
    try:
        for name, fn in sorted([(k, v) for k, v in globals().items()
                                if k.startswith("test_")]):
            fn()
            print(f"PASS {name}")
    finally:
        teardown_module()
    print("ALL TEN-MINUTE RCA CHECKS PASSED")
