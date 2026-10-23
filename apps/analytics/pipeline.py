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


# Summary safety cap: sentence splitting is script-dependent (Latin .!? vs
# Devanagari ।), so a transcript with no recognized terminators must never
# become a multi-KB "summary".
MAX_SUMMARY_CHARS = 1200


def _extractive_summary(full_text, sentences_per_quartile=3):
    sentences = [s.strip() for s in re.split(r"(?<=[.!?।])\s+", full_text or "")
                 if s.strip()]
    if not sentences:
        return ""
    n = len(sentences)
    picked = []
    for q in range(4):
        start = (n * q) // 4
        picked.extend(sentences[start : start + sentences_per_quartile])
    summary = " ".join(picked[: sentences_per_quartile * 4])
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"
    return summary


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


MIN_FLASHCARDS = 5
MCQ_TARGET = 5
FLASHCARD_HARD_CAP = 20


def _chapter_index_for_ts(ts, chapters):
    """Bucket index for a timestamp: containing chapter, else nearest edge."""
    for i, ch in enumerate(chapters):
        if int(ch["start_sec"]) <= ts < int(ch["end_sec"]):
            return i
    if ts >= int(chapters[-1]["end_sec"]):
        return len(chapters) - 1
    return 0


def chapter_tags(chapter, stopwords=("part", "section", "video", "intro")):
    """Topical tags from a chapter title (isalnum tokens, >=3 chars, deduped)."""
    tags, seen = [], set()
    for word in str(chapter.get("title", "")).split():
        token = "".join(c for c in word.lower() if c.isalnum())[:30]
        if len(token) >= 3 and token not in stopwords and token not in seen:
            seen.add(token)
            tags.append(token)
        if len(tags) >= 2:
            break
    return tags


def _spread_flashcards(cards, chapters):
    """Even deck: >=1 card per chapter, drawn from the fullest chapter.

    Donation moves a card (not drops it): the over-represented chapter's
    card gets re-anchored to the empty chapter's midpoint. Never reorders
    beyond the final chronological sort, and only acts when the deck is
    richer than the donor rule allows — decks can't be split thinner than
    the number of cards available.
    """
    if not cards or not chapters or len(chapters) < 2:
        return sorted(cards, key=lambda c: c["timestamp_sec"])
    buckets = [[] for _ in chapters]
    for card in cards:
        buckets[_chapter_index_for_ts(int(card["timestamp_sec"]),
                                      chapters)].append(card)
    for empty_idx, bucket in enumerate(buckets):
        while not bucket:
            # A donor must keep >=1 card itself: pick the fullest chapter.
            donors = [j for j in range(len(buckets)) if len(buckets[j]) > 1]
            if not donors:
                break
            donor = max(donors, key=lambda j: len(buckets[j]))
            moved = buckets[donor].pop()
            ch = chapters[empty_idx]
            mid = int(ch["start_sec"]) + (int(ch["end_sec"]) - int(ch["start_sec"])) // 2
            buckets[empty_idx].append({**moved,
                                       "timestamp_sec": max(0, mid)})
    spread = sorted((card for bucket in buckets for card in bucket),
                    key=lambda c: c["timestamp_sec"])
    floor = min(len(chapters), len(spread), FLASHCARD_HARD_CAP)
    keep = max(min(FLASHCARD_TARGET, len(spread)), floor)
    return spread[:keep]

GENERIC_REVIEW_PROMPTS = [
    ("What is one key term introduced in this video?", "Replay the section and list the term with its definition."),
    ("What is the central claim of this video?", "State it in one sentence, then find the supporting point."),
    ("What example best illustrates the main idea?", "Describe the example and what it proves."),
]


def _chapter_lead_sentences(segments, start_sec, end_sec, max_sentences=2,
                            max_chars=280):
    """First sentences actually spoken inside a chapter window.

    Makes degraded cards quote real video content instead of circular
    "review the segment" filler. Returns "" when nothing usable is found.
    """
    texts = [str(s.get("text", "")) for s in (segments or [])
             if start_sec <= float(s.get("start", 0)) < end_sec]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?।])\s+", " ".join(texts))
                 if s.strip()]
    return " ".join(sentences[:max_sentences])[:max_chars]


def _fallback_flashcards(chapters, full_text, segments=None):
    cards = []
    for ch in chapters:
        lead = _chapter_lead_sentences(segments, ch["start_sec"], ch["end_sec"])
        cards.append({
            "front": f"What is the main idea of '{ch['title']}'?"[:140],
            "back": (lead or ch.get("summary")
                     or f"Review the segment {ch['start_sec']}s–{ch['end_sec']}s.")[:300],
            "timestamp_sec": ch["start_sec"],
            "difficulty": "medium",
            "tags": chapter_tags(ch),
        })
        if len(cards) >= FLASHCARD_TARGET:
            break
    # Guarantee a usable deck floor even for very short videos: cycle the
    # generic review prompts with advancing timestamps until MIN is met.
    anchor = chapters[0]["start_sec"] if chapters else 0
    i = 0
    while len(cards) < MIN_FLASHCARDS:
        front, back = GENERIC_REVIEW_PROMPTS[i % len(GENERIC_REVIEW_PROMPTS)]
        cards.append({"front": front[:140], "back": back[:300],
                      "timestamp_sec": anchor + i * 10,
                      "difficulty": "medium", "tags": []})
        i += 1
    return cards


def _fallback_mcqs(chapters):
    """Chapter-title MCQs: correct answer rotated across positions so the
    key is not always option A. Padded so short videos still yield a quiz."""
    titles = [c["title"] for c in chapters]
    questions = []
    for i, ch in enumerate(chapters):
        if len(questions) >= MCQ_TARGET:
            break
        distractors = [t for t in titles if t != ch["title"]][:3]
        while len(distractors) < 3:
            distractors.append(["Key terms review", "Summary recap",
                                "Counter-example check"][len(distractors) % 3])
        answer = i % 4  # rotate the key across positions
        options = list(distractors)
        options.insert(answer, ch["title"])
        questions.append({
            "question": f"Which best describes the section starting at {ch['start_sec']}s?"[:200],
            "options": options,
            "answer_index": answer,
            "explanation": (f"'{ch['title']}' covers this segment "
                            f"({ch['start_sec']}s–{ch['end_sec']}s).")[:500],
            "timestamp_sec": ch["start_sec"],
        })
    return questions


_UNIFORM_TITLE_RE = re.compile(r"^Part \d+ \(\d+:\d\d\)$")


def _titles_are_generic(chapters):
    """True when chapter titles are uniform-generated placeholders.

    Label-matching quizzes built on placeholder titles are trivially circular
    ("which label matches this timestamp?"), so degraded mode omits MCQs and
    lets the UI show its honest empty state instead of fake questions.
    """
    return bool(chapters) and all(
        _UNIFORM_TITLE_RE.match(str(c.get("title", ""))) for c in chapters)


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
        "flashcards": _fallback_flashcards(chapters, full_text, segments)[:FLASHCARD_TARGET],
        "mcqs": [] if _titles_are_generic(chapters)
        else _fallback_mcqs(chapters)[:MCQ_TARGET],
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
        from services.llm_client import clean_flashcard

        chapters = normalize_chapters(raw.get("chapters", []), duration_sec)
        keywords = rescore_keywords(raw.get("keywords", []), full_text)
        flashcards = [clean for clean in
                      (clean_flashcard(card) for card in
                       (raw.get("flashcards", []) or [])[:FLASHCARD_HARD_CAP])
                      if clean]
        flashcards = _spread_flashcards(flashcards, chapters)
        stats = compute_stats(full_text, [k["term"] for k in keywords])
        from apps.analytics.graphs import build_all_graphs
        from apps.analytics.validators import ChartValidator
        from services.llm_client import clean_mcq

        mcqs = [m for m in (clean_mcq(q) for q in (raw.get("mcqs", []) or []))
                if m][:8]
        graphs = build_all_graphs(segments, keywords, chapters, duration_sec)
        ChartValidator.validate(graphs)  # redundant by construction; blocks silent drift
        return {
            "summary": str(raw.get("summary", "")),
            "chapters": chapters,
            "keywords": keywords,
            "flashcards": flashcards,
            "mcqs": mcqs,
            "stats": stats,
            "complexity": complexity_metrics(full_text),
            "graphs": graphs,
            "degraded": False,
        }
    except Exception:
        return degraded_analysis(segments, title, duration_sec)


__all__ = ["run_analysis", "degraded_analysis", "tokenize"]
