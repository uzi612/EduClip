"""BACKEND-02 verification: chapters, keywords, LLM client, pipeline.

Run: python apps/analytics/tests/test_llm_pipeline.py (needs repo root on PYTHONPATH)
OpenAI is stubbed via sys.modules — no network, no `openai` package needed.
"""
import json
import os
import sys
import types
from unittest.mock import patch

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

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
    "mcqs": [
        {"question": "What captures light?",
         "options": ["Chlorophyll", "Water", "Oxygen", "Soil"],
         "answer_index": 0, "explanation": "Chlorophyll absorbs photons.", "timestamp_sec": 45},
        {"question": "Too few options?", "options": ["Only", "Two"],
         "answer_index": 0, "explanation": "Dropped: needs 4 options.", "timestamp_sec": 10},
        {"question": "Bad index?", "options": ["A", "B", "C", "D"],
         "answer_index": 9, "explanation": "Dropped: index out of range.", "timestamp_sec": 10},
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


def test_top_terms_excludes_filler_words():
    from services.text_metrics import top_terms

    # Regression: "one/what/how" once topped real-video keyword lists.
    text = ("what one neuron does and how one layer learns "
            "what weights do and how neurons connect. " * 8).strip()
    terms = [k["term"] for k in top_terms(text)]
    for filler in ("one", "what", "how", "does", "and"):
        assert filler not in terms, terms
    assert "neuron" in terms and "weights" in terms, terms


def test_analyze_video_mocked_and_cached():
    from django.test.utils import override_settings

    llm_client.clear_cache()
    CALLS["n"] = 0
    with override_settings(OPENAI_API_KEY="test-key"):
        first = llm_client.analyze_video(SEGS, "Photosynthesis", provider="openai")
    assert first["summary"].startswith("Plants") and first["_meta"]["cached"] is False
    assert CALLS["kwargs"]["temperature"] == 0.3
    assert CALLS["kwargs"]["response_format"] == {"type": "json_object"}
    second = llm_client.analyze_video(SEGS, "Photosynthesis", provider="openai")
    assert second["_meta"]["cached"] is True and CALLS["n"] == 1


def test_analyze_video_invalid_json_raises():
    from services.llm_client import LLMError

    llm_client.clear_cache()
    with patch.object(llm_client, "_call_openai", side_effect=[
        LLMError("bad json", retryable=False, provider="openai")
    ]):
        try:
            llm_client.analyze_video(SEGS, "T", provider="openai", use_cache=False)
        except LLMError:
            return
    raise AssertionError("expected LLMError on invalid payload")


def test_run_analysis_full_path():
    from django.test.utils import override_settings

    llm_client.clear_cache()
    with override_settings(OPENAI_API_KEY="test-key"):
        out = pipeline.run_analysis(SEGS, "Photosynthesis", 842, provider="openai")
    assert out["degraded"] is False
    assert out["chapters"][-1]["end_sec"] == 842
    assert len(out["flashcards"]) == 2  # empty-front card dropped
    stamps = [c["timestamp_sec"] for c in out["flashcards"]]
    assert stamps == sorted(stamps) and 45 in stamps  # chronological deck
    assert all(c["difficulty"] in ("easy", "medium", "hard")
               and isinstance(c["tags"], list) for c in out["flashcards"])
    assert len(out["mcqs"]) == 1 and out["mcqs"][0]["answer_index"] == 0  # bad ones dropped
    assert out["stats"]["word_count"] > 0 and out["complexity"]["type_token_ratio"] > 0


def test_clean_flashcard_validates_and_normalizes():
    from services.llm_client import clean_flashcard

    card = clean_flashcard({"front": "  What captures light?  ",
                            "back": "Chlorophyll a.", "timestamp_sec": "45.9",
                            "difficulty": "EASY", "tags": [" Pigments ", "pigments", "  ", "x"]})
    assert card == {"front": "What captures light?", "back": "Chlorophyll a.",
                    "timestamp_sec": 45, "difficulty": "easy",
                    "tags": ["Pigments"]}
    # Garbage degrades instead of blowing up the deck.
    assert clean_flashcard({"front": "Q", "back": "A", "difficulty": "impossible"})\
        ["difficulty"] == "medium"
    assert clean_flashcard({"front": "Q", "back": "A", "timestamp_sec": "bad"})\
        ["timestamp_sec"] == 0
    assert clean_flashcard("not-a-dict") is None
    assert clean_flashcard({"front": " ", "back": "A"}) is None
    # Negative timestamps clamp; >3 tags truncated.
    assert clean_flashcard({"front": "Q", "back": "A", "timestamp_sec": -5,
                            "tags": ["a", "b", "c", "d", "e"]})["tags"] == ["a", "b", "c"]
    # Oversized tags are dropped, never truncated into garbage fragments.
    assert clean_flashcard({"front": "Q", "back": "A",
                            "tags": ["ok", "x" * 40]})["tags"] == ["ok"]


def test_spread_flashcards_one_card_per_chapter():
    chapters = [{"index": 0, "title": "A", "start_sec": 0, "end_sec": 300},
                {"index": 1, "title": "B", "start_sec": 300, "end_sec": 600},
                {"index": 2, "title": "C", "start_sec": 600, "end_sec": 900}]
    # LLM clustered everything into chapter 0 — spread must donate.
    cards = [{"front": f"Q{i}?", "back": "A", "timestamp_sec": 10 + i,
              "difficulty": "medium", "tags": []} for i in range(9)]

    out = pipeline._spread_flashcards(cards, chapters)

    assert len(out) == 9
    by_chapter = [0, 0, 0]
    for card in out:
        by_chapter[pipeline._chapter_index_for_ts(card["timestamp_sec"], chapters)] += 1
    assert min(by_chapter) >= 1, by_chapter
    stamps = [c["timestamp_sec"] for c in out]
    assert stamps == sorted(stamps)  # chronological deck order
    # Donated cards are re-anchored inside the previously-empty chapters.
    assert any(300 <= t < 600 for t in stamps), stamps
    assert any(600 <= t < 900 for t in stamps), stamps


def test_spread_flashcards_small_deck_keeps_all_cards():
    chapters = [{"index": 0, "title": "A", "start_sec": 0, "end_sec": 300},
                {"index": 1, "title": "B", "start_sec": 300, "end_sec": 600}]
    pairs = [{"front": "Q1", "back": "A", "timestamp_sec": 5,
              "difficulty": "hard", "tags": ["chlorophyll"]},
             {"front": "Q2", "back": "A", "timestamp_sec": 15,
              "difficulty": "easy", "tags": []}]
    out = pipeline._spread_flashcards(pairs, chapters)
    assert len(out) == 2  # huge decks shrink to target; small decks keep every card
    assert out[0]["timestamp_sec"] == 5 and out[0]["difficulty"] in ("hard",)
    assert 300 <= out[1]["timestamp_sec"] < 600  # donated into the empty chapter


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


def test_unicode_transcript_metrics():
    # Regression: Hindi/Devanagari transcript (video IecCQPX-QsI) collapsed to
    # one bogus keyword and a full-text "summary" before Unicode-aware handling.
    from apps.analytics import pipeline as pipeline_mod
    from services.text_metrics import tokenize, top_terms

    text = " ".join(f"पोर्टफोलियो डेटा विश्लेषण भाग {i}।" for i in range(30))
    assert len(tokenize(text)) > 50
    terms = top_terms(text)
    assert terms and terms[0]["count"] >= 10
    summary = pipeline_mod._extractive_summary(text)
    assert 0 < len(summary) <= pipeline_mod.MAX_SUMMARY_CHARS


if __name__ == "__main__":
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    print("ALL BACKEND-02 CHECKS PASSED")
