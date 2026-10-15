"""MCQ generation, persistence, and serving (watch streamline).

Run: python apps/quiz/tests/test_mcqs.py (needs repo root on PYTHONPATH)
LLM is mocked; MongoEngine uses in-memory mongomock.
"""
import os
from unittest.mock import patch

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

from apps.analytics import pipeline as pipeline_mod  # noqa: E402
from apps.quiz.models import MCQ  # noqa: E402
from apps.videos.models import Video  # noqa: E402
from services.llm_client import clean_mcq  # noqa: E402

META = {"title": "T", "channel": "C",
        "thumbnail": "https://i.ytimg.com/vi/x/hqdefault.jpg", "duration_sec": 600}
VALID = {"question": "What captures light?",
         "options": ["Chlorophyll", "Water", "Oxygen", "Soil"],
         "answer_index": 0, "explanation": "Chlorophyll absorbs photons.",
         "timestamp_sec": 5}


def setup_module():
    me.disconnect_all()
    me.connect("educlip-test", mongo_client_class=mongomock.MongoClient)


def teardown_module():
    me.disconnect_all()


def _clean():
    for doc in (MCQ, Video):
        doc.objects.delete()


def test_clean_mcq_accepts_valid_rejects_broken():
    assert clean_mcq(dict(VALID))["answer_index"] == 0
    assert clean_mcq({"question": "Q?", "options": ["A", "B"], "answer_index": 0,
                      "explanation": "E", "timestamp_sec": 0}) is None  # <4 options
    assert clean_mcq({**VALID, "answer_index": 4}) is None
    assert clean_mcq({**VALID, "explanation": ""}) is None
    assert clean_mcq({**VALID, "question": "  "}) is None
    assert clean_mcq("not-a-dict") is None


def test_degraded_mcqs_rotate_keys_and_pad_deck():
    chapters = [{"index": 0, "title": "Alpha", "start_sec": 0, "end_sec": 300,
                 "summary": "", "keyword_refs": []},
                {"index": 1, "title": "Beta", "start_sec": 300, "end_sec": 600,
                 "summary": "", "keyword_refs": []}]
    questions = pipeline_mod._fallback_mcqs(chapters)
    assert len(questions) == 2
    for i, q in enumerate(questions):
        assert len(q["options"]) == 4 and q["options"][q["answer_index"]] == chapters[i]["title"]
    assert [q["answer_index"] for q in questions] == [0, 1]  # rotated, not all A
    cards = pipeline_mod._fallback_flashcards(chapters[:1], "some words here")
    assert len(cards) >= pipeline_mod.MIN_FLASHCARDS  # short-video floor of 5


def test_fallback_flashcards_quote_real_content():
    chapters = [{"index": 0, "title": "Part 1 (0:00)", "start_sec": 0, "end_sec": 300,
                 "summary": "", "keyword_refs": []}]
    segs = [{"start": 10.0, "duration": 5.0, "text": "Neurons pass signals onward."},
            {"start": 400.0, "duration": 5.0, "text": "Weights tune the response."}]
    cards = pipeline_mod._fallback_flashcards(chapters, "ignored full text", segs)
    assert cards[0]["back"].startswith("Neurons pass signals onward."), cards[0]
    # No usable sentences in range -> honest generic fallback, never empty.
    cards = pipeline_mod._fallback_flashcards(chapters, "", [])
    assert cards[0]["back"], cards[0]


def test_degraded_suppresses_trivial_mcqs_and_flags_endpoint():
    segs = [{"start": float(i * 10), "duration": 10.0,
             "text": f"Lesson segment {i} about alpha."} for i in range(60)]
    out = pipeline_mod.degraded_analysis(segs, "T", 600)
    assert out["mcqs"] == []  # uniform titles would make label-matching filler
    assert len(out["flashcards"]) >= pipeline_mod.MIN_FLASHCARDS
    _clean()
    from apps.videos.video_service import get_or_create_video

    video, _ = get_or_create_video("dQw4w9WgXcQ", META)
    video.update(set__status="ready", set__degraded=True)
    client = APIClient(HTTP_HOST="testserver")
    with override_settings(MONGODB_ATLAS_URI=""):
        body = client.get(f"/api/v1/video/{video.id}/mcqs",
                          HTTP_HOST="testserver").json()
    assert body == {"video_id": str(video.id), "total": 0, "degraded": True, "mcqs": []}


def test_task_persists_mcqs_and_endpoint_serves():
    from apps.videos.tasks import process_video_task
    from apps.videos.video_service import get_or_create_video

    _clean()
    video, _ = get_or_create_video("dQw4w9WgXcQ", META)
    segs = [{"start": 0.0, "duration": 5.0, "text": "chlorophyll lesson"}]
    analysis = {"summary": "S",
                "chapters": [{"index": 0, "title": "A", "start_sec": 0, "end_sec": 600,
                              "summary": "", "keyword_refs": []}],
                "keywords": [], "flashcards": [], "stats": {}, "complexity": {},
                "graphs": {}, "mcqs": [dict(VALID)], "degraded": False}
    with override_settings(MONGODB_ATLAS_URI=""), patch(
        "apps.videos.transcribe.transcribe_video",
        return_value=(segs, "chlorophyll lesson", "youtube_captions")), patch(
        "apps.analytics.pipeline.run_analysis", return_value=analysis):
        out = process_video_task.run(str(video.id))
    assert out["status"] == "ready"
    video.reload()
    assert video.mcq_count == 1
    assert MCQ.objects(video_id=video).count() == 1
    client = APIClient(HTTP_HOST="testserver")
    with override_settings(MONGODB_ATLAS_URI=""):
        body = client.get(f"/api/v1/video/{video.id}/mcqs",
                          HTTP_HOST="testserver").json()
        detail = client.get(f"/api/v1/video/{video.id}/",
                            HTTP_HOST="testserver").json()
    assert body["total"] == 1
    served = body["mcqs"][0]
    assert served["options"][served["answer_index"]] == "Chlorophyll"
    assert served["explanation"].startswith("Chlorophyll absorbs")
    assert detail["mcq_count"] == 1
    with override_settings(MONGODB_ATLAS_URI=""):
        assert client.delete(f"/api/v1/video/{video.id}/",
                             HTTP_HOST="testserver").status_code == 204
    assert MCQ.objects.count() == 0  # cascade


def test_mcqs_unknown_video_404s():
    from bson import ObjectId

    client = APIClient(HTTP_HOST="testserver")
    with override_settings(MONGODB_ATLAS_URI=""):
        r = client.get(f"/api/v1/video/{ObjectId()}/mcqs", HTTP_HOST="testserver")
    assert r.status_code == 404


if __name__ == "__main__":
    setup_module()
    try:
        for name, fn in sorted([(k, v) for k, v in globals().items()
                                if k.startswith("test_")]):
            fn()
            print(f"PASS {name}")
    finally:
        teardown_module()
    print("ALL MCQ CHECKS PASSED")
