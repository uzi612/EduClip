"""CHARTS-04 verification: graph builders, validator, pipeline + task wiring.

Run: python apps/analytics/tests/test_graphs.py (needs repo root on PYTHONPATH)
No network. MongoEngine uses in-memory mongomock where needed.
"""
from unittest.mock import patch

import mongomock
import mongoengine as me

from apps.analytics.graphs import (
    build_all_graphs,
    build_chapter_share,
    build_engagement_curve,
    build_keyword_density,
)
from apps.analytics.validators import ChartValidationError, ChartValidator

SEGS = [{"start": float(i * 30), "duration": 30.0,
         "text": "chlorophyll captures light" if i % 2 == 0 else "atp stores energy"}
        for i in range(8)]  # 4 min span
KEYWORDS = [{"term": "chlorophyll", "score": 0.9, "count": 4},
            {"term": "atp", "score": 0.8, "count": 4}]
CHAPTERS = [{"index": 0, "title": "A", "start_sec": 0, "end_sec": 240,
             "summary": "", "keyword_refs": []}]


def test_empty_transcript_still_valid():
    graphs = build_all_graphs([], [], [], 0)
    assert ChartValidator.validate(graphs) is True
    assert graphs["keyword_density"]["data"]["datasets"][0]["data"] == [0]
    assert graphs["chapter_duration"]["data"]["datasets"][0]["data"] == [0]


def test_single_chapter_doughnut():
    pie = build_chapter_share(CHAPTERS)
    assert pie["type"] == "doughnut"
    assert pie["data"]["labels"] == ["A"] and pie["data"]["datasets"][0]["data"] == [240]


def test_long_video_bucket_counts():
    segs = [{"start": 0.0, "duration": 5.0, "text": "chlorophyll intro"},
            {"start": 3660.0, "duration": 5.0, "text": "chlorophyll finale"}]
    density = build_keyword_density(segs, KEYWORDS, 3720)
    labels = density["data"]["labels"]
    assert len(labels) == 62 and labels[0] == "0:00" and labels[-1] == "61:00", len(labels)
    chloro = next(d["data"] for d in density["data"]["datasets"] if d["label"] == "chlorophyll")
    assert chloro[0] == 1 and chloro[61] == 1 and sum(chloro) == 2
    curve = build_engagement_curve(segs, CHAPTERS, 3720, KEYWORDS)
    assert len(curve["data"]["datasets"][0]["data"]) == 62
    assert all(0.05 <= v <= 0.95 for v in curve["data"]["datasets"][0]["data"])


def test_validator_rejects_bad_shapes():
    good = build_all_graphs(SEGS, KEYWORDS, CHAPTERS, 240)
    wrong_type = {"type": "bar",
                  "data": {"labels": ["x"], "datasets": [{"data": [1]}]}}
    short_data = {"type": "bar",
                  "data": {"labels": ["a", "b"],
                           "datasets": [{"label": "k", "data": [1]}]}}
    non_numeric = {"type": "doughnut",
                   "data": {"labels": ["a"], "datasets": [{"data": ["x"]}]}}
    for broken in (
        {},
        {**good, "engagement_curve": wrong_type},
        {**good, "keyword_density": short_data},
        {**good, "chapter_duration": non_numeric},
    ):
        try:
            ChartValidator.validate(broken)
        except ChartValidationError:
            continue
        raise AssertionError(f"expected ChartValidationError for {broken}")


def test_pipeline_paths_include_valid_graphs():
    import sys
    import types

    from apps.analytics import pipeline
    from services import llm_client

    llm_client.clear_cache()
    raw = {"summary": "S",
           "chapters": [{"title": "A", "start_sec": 0, "end_sec": 600, "summary": ""}],
           "keywords": [{"term": "chlorophyll", "score": 0.9}],
           "flashcards": [{"front": "Q?", "back": "A.", "timestamp_sec": 5}]}
    with patch.object(llm_client, "analyze_video", return_value=dict(raw)):
        out = pipeline.run_analysis(SEGS, "T", 600)
    assert out["degraded"] is False
    assert ChartValidator.validate(out["graphs"]) is True
    assert out["graphs"]["chapter_duration"]["data"]["datasets"][0]["data"] == [600]

    degraded = pipeline.degraded_analysis(SEGS, "T", 600)
    assert degraded["degraded"] is True
    assert ChartValidator.validate(degraded["graphs"]) is True


def test_task_persists_analytics_doc():
    me.disconnect_all()
    me.connect("educlip-test", mongo_client_class=mongomock.MongoClient)
    try:
        from apps.analytics.models import Analytics
        from apps.videos.models import Video
        from apps.videos.tasks import process_video_task
        from apps.videos.video_service import get_or_create_video

        for doc in (Analytics, Video):
            doc.objects.delete()
        meta = {"title": "T", "channel": "C",
                "thumbnail": "https://i.ytimg.com/vi/x/hqdefault.jpg", "duration_sec": 600}
        video, _ = get_or_create_video("dQw4w9WgXcQ", meta)
        segs = [{"start": 0.0, "duration": 5.0, "text": "chlorophyll atp"}]
        result = dict(ANALYSIS)
        with patch("apps.videos.transcribe.transcribe_video",
                   return_value=(segs, "chlorophyll atp", "youtube_captions")), patch(
            "apps.analytics.pipeline.run_analysis", return_value=result):
            out = process_video_task.run(str(video.id))
        assert out["status"] == "ready"
        doc = Analytics.objects(video_id=video).first()
        assert doc is not None and ChartValidator.validate(doc.graphs) is True
        assert doc.stats["word_count"] == 12
    finally:
        me.disconnect_all()


ANALYSIS = {
    "summary": "S",
    "chapters": [{"index": 0, "title": "A", "start_sec": 0, "end_sec": 600,
                  "summary": "", "keyword_refs": []}],
    "keywords": [{"term": "chlorophyll", "score": 0.9, "count": 3}],
    "flashcards": [{"front": "Q?", "back": "A.", "timestamp_sec": 5}],
    "stats": {"word_count": 12, "reading_minutes": 1, "avg_words_per_min": 12,
              "top_keywords": ["chlorophyll"]},
    "complexity": {"type_token_ratio": 0.5, "avg_words_per_sentence": 4.0,
                   "long_word_ratio": 0.2},
    "graphs": build_all_graphs(
        [{"start": 0.0, "duration": 5.0, "text": "chlorophyll"}],
        [{"term": "chlorophyll", "score": 0.9, "count": 1}],
        [{"index": 0, "title": "A", "start_sec": 0, "end_sec": 600,
          "summary": "", "keyword_refs": []}], 600),
    "degraded": False,
}


if __name__ == "__main__":
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    print("ALL CHARTS-04 CHECKS PASSED")
