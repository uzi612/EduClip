"""DEPLOY-01 verification: end-to-end lifecycle as the frontend consumes it.

Submit (202) -> poll detail -> chapters/flashcards/analytics/list contracts,
plus failure envelopes (400/404/422/429) and the JSON 404 route. Every
assertion mirrors a field the UI reads (player init, sidebar, deck, charts,
toasts), so a green run means the deployed UI cannot hit a shape it
doesn't understand.

Run: python -m pytest apps/api_v1/tests/test_e2e_lifecycle.py
MongoEngine uses in-memory mongomock; Celery + metadata are mocked.
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
from apps.videos.models import Chapter, Keyword, Video  # noqa: E402

VID = "dQw4w9WgXcQ"
URL = f"https://www.youtube.com/watch?v={VID}"
META = {"title": "Intro to Photosynthesis", "channel": "BioClass",
        "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "duration_sec": 842}
GRAPHS = {
    "keyword_density": {"type": "bar",
                        "data": {"labels": ["0:00", "1:00"],
                                 "datasets": [{"label": "chlorophyll", "data": [3, 5]},
                                              {"label": "atp", "data": [1, 2]}]}},
    "chapter_duration": {"type": "doughnut",
                         "data": {"labels": ["Light", "Dark"],
                                  "datasets": [{"data": [240, 602]}]}},
    "engagement_curve": {"type": "line",
                         "data": {"labels": ["0:00", "1:00"],
                                  "datasets": [{"label": "Attention score",
                                                "data": [0.55, 0.85], "fill": True}]}},
}
STATS = {"word_count": 1200, "reading_minutes": 6, "avg_words_per_min": 200,
         "top_keywords": ["chlorophyll", "atp"]}

OPEN_RATES = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "1000/min", "process_video": "1000/min"},
    "EXCEPTION_HANDLER": "apps.api_v1.exceptions.educlip_exception_handler",
}


def setup_module():
    me.disconnect_all()
    me.connect("educlip-e2e", mongo_client_class=mongomock.MongoClient)


def teardown_module():
    me.disconnect_all()


def _clean():
    for doc in (Flashcard, Analytics, Video):
        doc.objects.delete()


def _client():
    return APIClient(HTTP_HOST="testserver")


def _ready_video():
    video = Video(
        youtube_id=VID, title=META["title"], channel=META["channel"],
        thumbnail=META["thumbnail"], duration_sec=842, status="ready", progress=1.0,
        summary="Photosynthesis converts light to sugar.", word_count=1200,
        transcript_source="youtube_captions", degraded=False,
        chapters=[Chapter(index=0, title="Light Reactions", start_sec=0, end_sec=240,
                          summary="Chlorophyll captures photons."),
                  Chapter(index=1, title="Calvin Cycle", start_sec=240, end_sec=842,
                          summary="Carbon fixation in the stroma.")],
        keywords=[Keyword(term="chlorophyll", score=0.9, count=8),
                  Keyword(term="atp", score=0.7, count=5)],
        flashcard_count=2,
    ).save()
    Flashcard(video_id=video, front="What pigment captures light?",
              back="Chlorophyll a.", timestamp_sec=45,
              difficulty="easy", tags=["pigments"]).save()
    Flashcard(video_id=video, front="Where does the Calvin cycle run?",
              back="In the stroma.", timestamp_sec=300,
              difficulty="medium", tags=["cycle"]).save()
    Analytics(video_id=video, stats=dict(STATS), graphs=dict(GRAPHS)).save()
    return video


def _submit(client, url=URL, key="e2e-1"):
    return client.post("/api/v1/process-video", {"youtube_url": url},
                       format="json", HTTP_IDEMPOTENCY_KEY=key)


@override_settings(REST_FRAMEWORK=OPEN_RATES)
def test_flow_submit_returns_pollable_job():
    _clean()
    with patch("services.youtube.get_video_metadata", return_value=dict(META)), patch(
            "apps.videos.tasks.process_video_task") as task:
        task.delay.return_value = MagicMock(id="task-9")
        r = _submit(_client())
    assert r.status_code == 202, r.content
    body = r.json()
    assert body["status"] == "processing"
    assert body["video_id"] and body["poll_url"] == f"/api/v1/video/{body['video_id']}/"
    assert body["progress"] == 0.05
    # Poll contract while queued: status + progress for the progress bar.
    r2 = _client().get(body["poll_url"])
    assert r2.status_code == 200, r2.content
    assert r2.json()["status"] in ("queued", "processing")
    assert 0.0 <= r2.json()["progress"] <= 1.0


@override_settings(REST_FRAMEWORK=OPEN_RATES)
def test_flow_ready_detail_has_every_frontend_field():
    _clean()
    v = _ready_video()
    r = _client().get(f"/api/v1/video/{v.id}/")
    assert r.status_code == 200, r.content
    b = r.json()
    # Player init + header.
    assert b["status"] == "ready" and b["progress"] == 1.0
    assert b["youtube_id"] == VID and b["title"] and b["duration_sec"] == 842
    assert b["degraded"] is False and b["transcript_source"] == "youtube_captions"
    assert b["summary"] and b["flashcard_count"] == 2
    # Chapter sidebar contract.
    assert len(b["chapters"]) == 2
    c0 = b["chapters"][0]
    assert set(("index", "title", "start_sec", "end_sec", "summary")) <= set(c0)
    assert c0["start_sec"] == 0 and c0["end_sec"] == 240
    # Keywords + preview for stats row.
    assert b["keywords"][0]["term"] == "chlorophyll"
    assert b["analytics_preview"]["chapter_count"] == 2
    assert b["analytics_preview"]["reading_minutes"] == 6
    assert b["created_at"] and b["updated_at"]


@override_settings(REST_FRAMEWORK=OPEN_RATES)
def test_flow_chapters_flashcards_analytics_list_shapes():
    _clean()
    v = _ready_video()
    c = _client()

    r = c.get(f"/api/v1/video/{v.id}/chapters")
    assert r.status_code == 200, r.content
    assert r.json()["duration_sec"] == 842
    assert r.json()["chapters"][1]["title"] == "Calvin Cycle"

    r = c.get(f"/api/v1/video/{v.id}/flashcards?page=1&page_size=50")
    assert r.status_code == 200, r.content
    f = r.json()
    assert f["total"] == 2 and len(f["flashcards"]) == 2
    card = f["flashcards"][0]
    assert set(("card_id", "front", "back", "timestamp_sec", "difficulty", "tags")) <= set(card)
    assert card["timestamp_sec"] == 45 and card["tags"] == ["pigments"]

    r = c.get(f"/api/v1/video/{v.id}/analytics")
    assert r.status_code == 200, r.content
    g = r.json()["graphs"]
    kd = g["keyword_density"]
    assert kd["type"] == "bar" and len(kd["data"]["labels"]) == len(kd["data"]["datasets"][0]["data"])
    dd = g["chapter_duration"]
    assert dd["type"] == "doughnut" and sum(dd["data"]["datasets"][0]["data"]) == 842
    ec = g["engagement_curve"]
    assert ec["type"] == "line" and all(0 <= x <= 1 for x in ec["data"]["datasets"][0]["data"])

    r = c.get("/api/v1/videos/?page=1&page_size=9")
    assert r.status_code == 200, r.content
    item = r.json()["items"][0]
    assert set(("video_id", "youtube_id", "title", "thumbnail",
                "duration_sec", "status", "created_at")) <= set(item)
    assert "progress" not in item  # list projection stays light


@override_settings(REST_FRAMEWORK=OPEN_RATES)
def test_flow_failed_and_pending_states():
    _clean()
    v = _ready_video()
    v.update(status="failed", error="No captions.")
    r = _client().get(f"/api/v1/video/{v.id}/")
    assert r.status_code == 422, r.content
    assert r.json()["status"] == "failed"
    assert r.json()["error"]["code"] == "PROCESSING_FAILED"
    assert r.json()["error"]["request_id"]

    Analytics.objects.delete()  # still processing: no analytics row yet
    v.update(status="processing", progress=0.2)
    r = _client().get(f"/api/v1/video/{v.id}/analytics")
    assert r.status_code == 404, r.content
    assert r.json()["error"]["code"] == "ANALYTICS_PENDING"
    assert r.json()["error"]["retryable"] is True


@override_settings(REST_FRAMEWORK=OPEN_RATES)
def test_flow_invalid_ids_and_routes_never_500():
    _clean()
    c = _client()
    r = c.get("/api/v1/video/does-not-exist/")
    assert r.status_code == 404 and r.json()["error"]["code"] == "VIDEO_NOT_FOUND"
    assert r.json()["error"]["request_id"]
    r = c.get("/api/v1/video/abc/")
    assert r.status_code == 404, r.content  # malformed id guarded, no 500
    # handler404 serves the JSON envelope with DEBUG=False (as in prod).
    with override_settings(DEBUG=False):
        r = c.get("/api/v1/no-such-route/")
    assert r.status_code == 404, r.content
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert r["Content-Type"] == "application/json"  # envelope, not Django HTML


@override_settings(REST_FRAMEWORK=OPEN_RATES)
def test_flow_invalid_url_rejected_with_envelope():
    _clean()
    r = _submit(_client(), url="https://example.com/not-youtube")
    assert r.status_code == 400, r.content
    err = r.json()["error"]
    assert err["code"] == "INVALID_URL" and err["message"] and err["retryable"] is False
    assert err["request_id"] and isinstance(err["details"], dict)


def test_flow_throttle_returns_429_envelope_with_retry_after():
    # NOTE: DRF freezes SimpleThrottle.THROTTLE_RATES at import, so
    # override_settings cannot change rates — patch the class attr instead
    # (same pattern as test_error_handling) and clear the shared cache key.
    from django.core.cache import caches

    from apps.api_v1.throttles import ProcessVideoThrottle

    _clean()
    caches["default"].clear()
    ids = ["dQw4w9WgXcQ", "9bZkp7q19f0", "jNQXAC9IVRw"]
    with patch.object(ProcessVideoThrottle, "THROTTLE_RATES",
                      {"process_video": "2/min"}), patch(
            "services.youtube.get_video_metadata", return_value=dict(META)), patch(
                "apps.videos.tasks.process_video_task") as task:
        task.delay.return_value = MagicMock(id="t")
        c = _client()
        codes = [
            c.post("/api/v1/process-video", {"youtube_url": f"https://youtu.be/{i}"},
                   format="json", HTTP_IDEMPOTENCY_KEY=f"th-{i}").status_code
            for i in ids
        ]
    assert codes == [202, 202, 429], codes
    # Re-fire once more to inspect the envelope (still throttled).
    with patch.object(ProcessVideoThrottle, "THROTTLE_RATES",
                      {"process_video": "2/min"}):
        r = c.post("/api/v1/process-video", {"youtube_url": f"https://youtu.be/{ids[0]}"},
                   format="json", HTTP_IDEMPOTENCY_KEY="th-last")
    assert r.status_code == 429, r.content
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in r
