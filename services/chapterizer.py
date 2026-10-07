"""Chapter normalization (BACKEND-02): never trust LLM timestamps blindly.

Rules (docs/ARCHITECTURE.md §6):
1. Sort by start_sec; clamp into [0, duration].
2. First starts at 0, last ends at duration; fill gaps between chapters.
3. Merge chapters shorter than MIN_CHAPTER_SEC into a neighbor.
4. Dedupe repeated titles with a "Part N" suffix; reindex 0..n.
"""
MIN_CHAPTER_SEC = 30
MAX_TITLE_LEN = 80


def _clean_title(title, seen):
    title = " ".join(str(title or "Untitled").split())[:MAX_TITLE_LEN] or "Untitled"
    if title not in seen:
        seen[title] = 1
        return title
    seen[title] += 1
    suffix = f" Part {seen[title]}"
    return (title[: MAX_TITLE_LEN - len(suffix)] + suffix) or f"Untitled{suffix}"


def normalize_chapters(raw, duration):
    """Normalize raw LLM chapters. Returns a list of dicts with index/title/start/end/summary."""
    duration = max(int(duration or 0), MIN_CHAPTER_SEC)
    items = []
    for ch in raw or []:
        try:
            start = max(0, int(float(ch.get("start_sec", 0))))
            end = min(duration, int(float(ch.get("end_sec", 0))))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        items.append({
            "title": ch.get("title", "Untitled"),
            "start_sec": start,
            "end_sec": end,
            "summary": str(ch.get("summary", ""))[:500],
        })
    if not items:
        return [{
            "index": 0, "title": "Full video", "start_sec": 0,
            "end_sec": duration, "summary": "", "keyword_refs": [],
        }]
    items.sort(key=lambda c: c["start_sec"])
    items[0]["start_sec"] = 0
    items[-1]["end_sec"] = duration
    for i in range(len(items) - 1):
        if items[i]["end_sec"] >= items[i + 1]["start_sec"]:
            items[i]["end_sec"] = max(items[i]["start_sec"] + 1, items[i + 1]["start_sec"] - 1)
        elif items[i]["end_sec"] < items[i + 1]["start_sec"]:
            items[i]["end_sec"] = items[i + 1]["start_sec"] - 1

    merged = []
    for ch in items:
        if merged and ch["end_sec"] - ch["start_sec"] < MIN_CHAPTER_SEC:
            prev = merged[-1]
            prev["end_sec"] = ch["end_sec"]
            if ch.get("summary"):
                prev["summary"] = (prev.get("summary", "") + " " + ch["summary"]).strip()[:500]
            continue
        if ch["end_sec"] - ch["start_sec"] < MIN_CHAPTER_SEC and not merged:
            # First chapter too short: extend into the next one instead of dropping.
            if len(items) > 1:
                ch["end_sec"] = min(duration, ch["start_sec"] + MIN_CHAPTER_SEC)
            else:
                ch["end_sec"] = duration
        merged.append(ch)
    # Drop any remaining short tail by folding it into its predecessor.
    while len(merged) > 1 and merged[-1]["end_sec"] - merged[-1]["start_sec"] < MIN_CHAPTER_SEC:
        tail = merged.pop()
        merged[-1]["end_sec"] = tail["end_sec"]

    seen, out = {}, []
    for i, ch in enumerate(merged):
        out.append({
            "index": i,
            "title": _clean_title(ch["title"], seen),
            "start_sec": ch["start_sec"],
            "end_sec": ch["end_sec"],
            "summary": ch.get("summary", ""),
            "keyword_refs": list(ch.get("keyword_refs", []) or [])[:5],
        })
    return out
