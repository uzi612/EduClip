"""BACKEND-04 verification: retrieval endpoints (detail, chapters, flashcards,
analytics, list, delete).

Run: python apps/api_v1/tests/test_video_retrieval.py (needs repo root on PYTHONPATH)
MongoEngine uses in-memory mongomock.
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from django.conf import settings  # noqa: E402

if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]

import mongomock  # noqa: E402
import mongoengine as me  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.analytics.models import Analytics  # noqa: E402
from apps.flashcards.models import Flashcard  # noqa: E402
from apps.videos.models import Chapter, Keyword, Video  # noqa: E402

GRAPHS = {
    "keyword_density": {"type": "bar",
                        "data": {"labels": ["0:00"], "datasets": [{"label": "atp", "data": [3]}]}},
    "chapter_duration": {"type": "doughnut",
                         "data": {"labels": ["A"], "datasets": [{"data": [600]}]}},
    "engagement_curve": {"type": "line",
                         "data": {"labels": ["0:00"],
                                  "datasets": [{"label": "Attention", "data": [0.8], "fill": True}]}},
}
STATS = {"word_count": 1200, "reading_minutes": 6, "avg_words_per_min": 200,
         "top_keywords": ["atp"]}


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


def _ready_video(youtube_id="dQw4w9WgXcQ", with_analytics=True):
    video = Video(
        youtube_id=youtube_id, title="T", channel="C",
        thumbnail="https://i.ytimg.com/vi/x/hqdefault.jpg",
        duration_sec=600, status="ready", progress=1.0,
        summary="S", word_count=1200,
        chapters=[Chapter(index=0, title="A", start_sec=0, end_sec=600, summary="")],
        keywords=[Keyword(term="atp", score=0.9, count=5)],
        flashcard_count=5,
    ).save()
    for i in range(5):
        Flashcard(video_id=video, front=f"Q{i}?", back=f"A{i}.",
                  timestamp_sec=i * 60).save()
    if with_analytics:
        Analytics(video_id=video, stats=dict(STATS), graphs=dict(GRAPHS)).save()
    return video


def test_detail_ready_full_payload():
    _clean()
    v = _ready_video()
    r = _client().get(f"/api/v1/video/{v.id}/")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["status"] == "ready" and body["flashcard_count"] == 5
    assert len(body["chapters"]) == 1 and body["chapters"][0]["title"] == "A"
    assert body["keywords"][0]["term"] == "atp"
    assert body["analytics_preview"]["chapter_count"] == 1
    assert r["Cache-Control"] == "public, max-age=60"


def test_detail_processing_returns_progress():
    _clean()
    v = Video(youtube_id="dQw4w9WgXcQ", title="T", duration_sec=600,
              status="analyzing", progress=0.7).save()
    body = _client().get(f"/api/v1/video/{v.id}/").json()
    assert body["status"] == "analyzing" and body["progress"] == 0.7
    assert "chapters" not in body


def test_detail_failed_returns_422():
    _clean()
    v = Video(youtube_id="dQw4w9WgXcQ", title="T", duration_sec=600,
              status="failed", error="boom").save()
    r = _client().get(f"/api/v1/video/{v.id}/")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PROCESSING_FAILED"


def test_detail_unknown_and_malformed_404():
    _clean()
    from bson import ObjectId

    r = _client().get(f"/api/v1/video/{ObjectId()}/")
    assert r.status_code == 404 and r.json()["error"]["code"] == "VIDEO_NOT_FOUND"
    r = _client().get("/api/v1/video/not-an-id/")
    assert r.status_code == 404 and r.json()["error"]["code"] == "VIDEO_NOT_FOUND"


def test_chapters_endpoint():
    _clean()
    v = _ready_video()
    body = _client().get(f"/api/v1/video/{v.id}/chapters").json()
    assert body["duration_sec"] == 600 and len(body["chapters"]) == 1
    assert body["chapters"][0]["thumbnail_sec"] == 10


def test_flashcards_pagination():
    _clean()
    v = _ready_video()
    c = _client()
    first = c.get(f"/api/v1/video/{v.id}/flashcards?page=1&page_size=2").json()
    assert (first["total"], first["page"]) == (5, 1) and len(first["flashcards"]) == 2
    assert first["flashcards"][0]["timestamp_sec"] == 0
    second = c.get(f"/api/v1/video/{v.id}/flashcards?page=2&page_size=2").json()
    assert second["flashcards"][0]["timestamp_sec"] == 120
    bad = c.get(f"/api/v1/video/{v.id}/flashcards?page=nope")
    assert bad.status_code == 400


def test_analytics_passthrough_and_pending():
    _clean()
    v = _ready_video()
    body = _client().get(f"/api/v1/video/{v.id}/analytics").json()
    assert set(body["graphs"]) == {"keyword_density", "chapter_duration", "engagement_curve"}
    assert body["stats"]["word_count"] == 1200
    v2 = _ready_video(youtube_id="9bZkp7q19f0", with_analytics=False)
    r = _client().get(f"/api/v1/video/{v2.id}/analytics")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ANALYTICS_PENDING"


def test_list_filter_search_pagination():
    _clean()
    _ready_video()
    Video(youtube_id="9bZkp7q19f0", title="Other", duration_sec=100,
          status="processing", progress=0.2).save()
    c = _client()
    default = c.get("/api/v1/videos/").json()
    assert default["total"] == 1  # ready only by default
    all_items = c.get("/api/v1/videos/?status=all").json()
    assert all_items["total"] == 2
    searched = c.get("/api/v1/videos/?status=all&search=oth").json()
    assert searched["total"] == 1 and searched["items"][0]["title"] == "Other"


def test_delete_cascades_then_404s():
    _clean()
    v = _ready_video()
    vid = str(v.id)
    c = _client()
    assert c.delete(f"/api/v1/video/{vid}/").status_code == 204
    assert Video.objects(id=vid).first() is None
    assert Flashcard.objects.count() == 0 and Analytics.objects.count() == 0
    assert c.delete(f"/api/v1/video/{vid}/").status_code == 404
    assert c.get(f"/api/v1/video/{vid}/").status_code == 404


if __name__ == "__main__":
    setup_module()
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    teardown_module()
    print("ALL BACKEND-04 CHECKS PASSED")
