"""BACKEND-02 verification: chapters, keywords, LLM client, pipeline.

Run: python apps/analytics/tests/test_llm_pipeline.py (needs repo root on PYTHONPATH)
OpenAI is stubbed via sys.modules — no network, no `openai` package needed.
"""
import json
import sys
import types
from unittest.mock import patch

CALLS = {"n": 0}
CANNED = {
    "summary": "Plants convert light into chemical energy.",
    "chapters": [
        {"title": "Calvin Cycle", "start_sec": 500, "end_sec": 200,
         "summary": "bad range dropped"},
        {"title": "Light Reactions", "start_sec": 300, "end_sec": 200,
         "summary": "backwards dropped"},
        {"title": "Intro", "start_sec": 20, "end_sec": 25, "summary": "too short"},
        {"title": "Light Reactions", "start_sec": 0, "end_sec": 240, "summary": "photons"},
        {"title": "Light Reactions", "start_sec": 241, "end_sec": 600, "summary": "stroma"},
    ],
    "keywords": [
        {"term": "chlorophyll", "score": 0.9},
        {"term": "atp", "score": 0.8},
        {"term": "nonexistentxyz", "score": 0.95},
    ],
    "flashcards": [
        {"front": "What captures light?", "back": "Chlorophyll.", "timestamp_sec": 45},
        {"front": "   ", "back": "Empty front dropped.", "timestamp_sec": 10},
        {"front": "Where does fixation happen?", "back": "Stroma.", "timestamp_sec": "bad"},
    ],
}

fake_openai = types.ModuleType("openai")


class _Completions:
    @staticmethod
    def create(**kwargs):
        CALLS["n"] += 1
        CALLS["kwargs"] = kwargs
        msg = types.SimpleNamespace(content=json.dumps(CANNED))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


class _Chat:
    completions = _Completions()


class _Client:
    def __init__(self, *a, **k):
        pass

    chat = _Chat()


fake_openai.OpenAI = _Client
sys.modules.setdefault("openai", fake_openai)

from apps.analytics import pipeline  # noqa: E402
from services import llm_client  # noqa: E402
from services.chapterizer import normalize_chapters  # noqa: E402
from services.text_metrics import (  # noqa: E402
    complexity_metrics,
    compute_stats,
    rescore_keywords,
)

TEXT = ("chlorophyll chlorophyll chlorophyll atp atp stroma. " * 20).strip()
SEGS = [{"start": i * 10.0, "duration": 10.0, "text": "chlorophyll atp stroma lesson"}
        for i in range(5)]


def test_normalize_chapters():
    out = normalize_chapters(CANNED["chapters"], 842)
    assert out[0]["start_sec"] == 0 and out[-1]["end_sec"] == 842, out
    assert all(c["end_sec"] - c["start_sec"] >= 30 for c in out), out
    titles = [c["title"] for c in out]
    assert len(set(titles)) == len(titles), titles  # dupes suffixed
    assert [c["index"] for c in out] == list(range(len(out)))


def test_rescore_keywords():
    scored = rescore_keywords(CANNED["keywords"], TEXT)
    terms = [k["term"] for k in scored]
    assert "nonexistentxyz" not in terms, scored
    assert terms[0] == "chlorophyll" and all(k["score"] >= 0.15 for k in scored)
    assert all(k["count"] > 0 for k in scored)


def test_analyze_video_mocked_and_cached():
    llm_client.clear_cache()
    CALLS["n"] = 0
    first = llm_client.analyze_video(SEGS, "Photosynthesis")
    assert first["summary"].startswith("Plants") and first["_meta"]["cached"] is False
    assert CALLS["kwargs"]["temperature"] == 0.3
    assert CALLS["kwargs"]["response_format"] == {"type": "json_object"}
    second = llm_client.analyze_video(SEGS, "Photosynthesis")
    assert second["_meta"]["cached"] is True and CALLS["n"] == 1


def test_analyze_video_invalid_json_raises():
    from services.llm_client import LLMError

    llm_client.clear_cache()
    with patch.object(llm_client, "_call_openai", side_effect=[
        LLMError("bad json", retryable=False, provider="openai")
    ]):
        try:
            llm_client.analyze_video(SEGS, "T", use_cache=False)
        except LLMError:
            return
    raise AssertionError("expected LLMError on invalid payload")


def test_run_analysis_full_path():
    llm_client.clear_cache()
    out = pipeline.run_analysis(SEGS, "Photosynthesis", 842)
    assert out["degraded"] is False
    assert out["chapters"][-1]["end_sec"] == 842
    assert len(out["flashcards"]) == 2  # empty-front card dropped
    assert out["flashcards"][0]["timestamp_sec"] == 45
    assert out["stats"]["word_count"] > 0 and out["complexity"]["type_token_ratio"] > 0


def test_run_analysis_degraded_fallback():
    llm_client.clear_cache()
    segs = [{"start": i * 60.0, "duration": 60.0,
             "text": f"Lesson part {i}. Plants use sunlight. " * 5} for i in range(12)]
    with patch.object(llm_client, "analyze_video",
                      side_effect=Exception("quota exhausted")):
        out = pipeline.run_analysis(segs, "Long lecture", 720)
    assert out["degraded"] is True
    assert out["chapters"][0]["start_sec"] == 0 and out["chapters"][-1]["end_sec"] == 720
    assert 1 <= len(out["flashcards"]) <= 10 and out["summary"]


def test_stats_and_complexity():
    stats = compute_stats(TEXT, ["chlorophyll"])
    assert stats["word_count"] > 0 and stats["reading_minutes"] >= 1
    c = complexity_metrics(TEXT)
    assert 0 < c["type_token_ratio"] <= 1 and c["avg_words_per_sentence"] > 0


if __name__ == "__main__":
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    print("ALL BACKEND-02 CHECKS PASSED")
