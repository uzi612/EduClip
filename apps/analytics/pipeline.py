"""Analysis orchestrator: LLM -> normalize -> rescore -> store-ready dict.

Degraded mode: if the LLM fails (timeout, quota, invalid JSON), fall back to
an extractive summary + uniform chapters + frequency-mined keywords so the
video still reaches `ready` with `degraded=True` (docs/ARCHITECTURE.md §6).
"""
import re

from services import llm_client
from services.chapterizer import normalize_chapters
from services.text_metrics import (
    complexity_metrics,
    compute_stats,
    rescore_keywords,
    tokenize,
    top_terms,
)

FLASHCARD_TARGET = 10
CHAPTER_UNIFORM_SEC = 300


def _extractive_summary(full_text, sentences_per_quartile=3):
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text or "") if s.strip()]
    if not sentences:
        return ""
    n = len(sentences)
    picked = []
    for q in range(4):
        start = (n * q) // 4
        picked.extend(sentences[start : start + sentences_per_quartile])
    return " ".join(picked[: sentences_per_quartile * 4])


def _uniform_chapters(duration, words_per_sec=2.5, full_text=""):
    chunks, start = [], 0
    idx = 0
    while start < duration:
        end = min(duration, start + CHAPTER_UNIFORM_SEC)
        chunks.append({
            "index": idx, "title": f"Part {idx + 1} ({start // 60}:{start % 60:02d})",
            "start_sec": start, "end_sec": end,
            "summary": "", "keyword_refs": [],
        })
        start, idx = end, idx + 1
    return chunks


def _fallback_flashcards(chapters, full_text):
    cards = []
    for ch in chapters:
        cards.append({
            "front": f"What is the main idea of '{ch['title']}'?"[:140],
            "back": (ch.get("summary") or
                     f"Review the segment {ch['start_sec']}s–{ch['end_sec']}s.")[:300],
            "timestamp_sec": ch["start_sec"],
        })
        if len(cards) >= FLASHCARD_TARGET:
            break
    return cards


def degraded_analysis(segments, title, duration_sec):
    """Rule-based fallback when the LLM is unavailable. Never raises."""
    from apps.analytics.graphs import build_all_graphs

    full_text = " ".join(s.get("text", "") for s in (segments or []))
    duration = max(int(duration_sec or 0), 30)
    chapters = _uniform_chapters(duration, full_text=full_text)
    keywords = top_terms(full_text)[:10]
    stats = compute_stats(full_text, [k["term"] for k in keywords])
    return {
        "summary": _extractive_summary(full_text),
        "chapters": chapters,
        "keywords": keywords,
        "flashcards": _fallback_flashcards(chapters, full_text)[:FLASHCARD_TARGET],
        "stats": stats,
        "complexity": complexity_metrics(full_text),
        "graphs": build_all_graphs(segments, keywords, chapters, duration),
        "degraded": True,
    }


def run_analysis(segments, title, duration_sec, provider=None):
    """Full pipeline. Returns store-ready dict with degraded flag.

    Raises only degraded_analysis output on LLM failure (never propagates).
    """
    full_text = " ".join(s.get("text", "") for s in (segments or []))
    try:
        raw = llm_client.analyze_video(segments, title, provider=provider)
    except Exception:
        return degraded_analysis(segments, title, duration_sec)
    try:
        chapters = normalize_chapters(raw.get("chapters", []), duration_sec)
        keywords = rescore_keywords(raw.get("keywords", []), full_text)
        flashcards = []
        for card in (raw.get("flashcards", []) or [])[:FLASHCARD_TARGET]:
            front = " ".join(str(card.get("front", "")).split())[:140]
            back = " ".join(str(card.get("back", "")).split())[:300]
            if not front or not back:
                continue
            try:
                ts = max(0, int(float(card.get("timestamp_sec", 0))))
            except (TypeError, ValueError):
                ts = 0
            flashcards.append({"front": front, "back": back, "timestamp_sec": ts})
        stats = compute_stats(full_text, [k["term"] for k in keywords])
        from apps.analytics.graphs import build_all_graphs
        from apps.analytics.validators import ChartValidator

        graphs = build_all_graphs(segments, keywords, chapters, duration_sec)
        ChartValidator.validate(graphs)  # redundant by construction; blocks silent drift
        return {
            "summary": str(raw.get("summary", "")),
            "chapters": chapters,
            "keywords": keywords,
            "flashcards": flashcards,
            "stats": stats,
            "complexity": complexity_metrics(full_text),
            "graphs": graphs,
            "degraded": False,
        }
    except Exception:
        return degraded_analysis(segments, title, duration_sec)


__all__ = ["run_analysis", "degraded_analysis", "tokenize"]
