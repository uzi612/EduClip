"""Chart.js payload formatters (CHARTS-04): deterministic builders producing
Chart.js-native graphs so the frontend renders with zero transformation.

Shapes follow docs/API_SPECIFICATION.md §7 and docs/DATABASE_DESIGN.md §6:
- keyword_density (bar): top-5 keywords x 60s buckets.
- chapter_duration (doughnut): per-chapter seconds.
- engagement_curve (line): heuristic 0..1 attention per bucket.
"""
BUCKET_SEC = 60
MAX_KEYWORD_DATASETS = 5


def _bucket_labels(n_buckets, bucket_sec=BUCKET_SEC):
    return [f"{(b * bucket_sec) // 60}:{(b * bucket_sec) % 60:02d}" for b in range(n_buckets)]


def _n_buckets(segments, duration_sec, bucket_sec=BUCKET_SEC):
    latest = max([float(s.get("start", 0)) for s in (segments or [])] + [0.0])
    span = max(float(duration_sec or 0), latest)
    return max(1, int(span // bucket_sec) + (1 if span % bucket_sec else 0))


def build_keyword_density(segments, keywords, duration_sec=0, bucket_sec=BUCKET_SEC):
    """Count keyword mentions per time bucket for the top keywords."""
    terms = [str(k.get("term", "")).lower() for k in (keywords or [])][:MAX_KEYWORD_DATASETS]
    terms = [t for t in terms if t]
    n = _n_buckets(segments, duration_sec, bucket_sec)
    lowered = [(float(s.get("start", 0)), str(s.get("text", "")).lower())
               for s in (segments or [])]
    if not terms:
        # Degenerate input (e.g. empty transcript): keep a valid, all-zero shape
        # so validators pass and the frontend renders an empty chart.
        terms = ["mentions"]
    datasets = []
    for term in terms:
        counts = [0] * n
        for start, text in lowered:
            if term in text:
                counts[min(int(start // bucket_sec), n - 1)] += 1
        datasets.append({"label": term, "data": counts})
    return {"type": "bar",
            "data": {"labels": _bucket_labels(n, bucket_sec), "datasets": datasets}}


def build_chapter_share(chapters):
    """Doughnut of seconds per chapter."""
    labels, data = [], []
    for ch in chapters or []:
        labels.append(str(ch.get("title", "Untitled")))
        data.append(max(0, int(ch.get("end_sec", 0)) - int(ch.get("start_sec", 0))))
    if not labels:
        labels, data = ["Full video"], [0]
    return {"type": "doughnut",
            "data": {"labels": labels, "datasets": [{"data": data}]}}


def build_engagement_curve(segments, chapters, duration_sec=0, keywords=(),
                           bucket_sec=BUCKET_SEC):
    """Heuristic attention score per bucket (deterministic, documented).

    base 0.70; +0.10 when a chapter starts in the bucket (novelty spike);
    -0.15 on the opening bucket (intro dip); +0.05 per keyword hit up to +0.15
    (density holds attention). Clamped to [0.05, 0.95].
    """
    n = _n_buckets(segments, duration_sec, bucket_sec)
    starts = {int(float(c.get("start_sec", -1)) // bucket_sec) for c in (chapters or [])}
    terms = [str(k.get("term", "")).lower() for k in (keywords or [])][:MAX_KEYWORD_DATASETS]
    hits = [0] * n
    for start, text in [((float(s.get("start", 0))), str(s.get("text", "")).lower())
                        for s in (segments or [])]:
        bucket = min(int(start // bucket_sec), n - 1)
        hits[bucket] += sum(1 for t in terms if t and t in text)
    scores = []
    for b in range(n):
        score = 0.70
        if b in starts:
            score += 0.10
        if b == 0:
            score -= 0.15
        score += min(hits[b], 3) * 0.05
        scores.append(round(max(0.05, min(0.95, score)), 2))
    return {"type": "line",
            "data": {"labels": _bucket_labels(n, bucket_sec),
                     "datasets": [{"label": "Attention score",
                                   "data": scores, "fill": True}]}}


def build_all_graphs(segments, keywords, chapters, duration_sec, bucket_sec=BUCKET_SEC):
    """Build the full graphs payload validated by ChartValidator."""
    from apps.analytics.validators import ChartValidator

    graphs = {
        "keyword_density": build_keyword_density(segments, keywords, duration_sec,
                                                 bucket_sec),
        "chapter_duration": build_chapter_share(chapters),
        "engagement_curve": build_engagement_curve(segments, chapters, duration_sec,
                                                   keywords, bucket_sec),
    }
    ChartValidator.validate(graphs)
    return graphs


__all__ = ["build_keyword_density", "build_chapter_share", "build_engagement_curve",
           "build_all_graphs", "BUCKET_SEC"]
