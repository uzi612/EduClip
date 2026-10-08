"""JSON presenters for api_v1 (BACKEND-04). MongoEngine docs -> API contract.

Contracts follow docs/API_SPECIFICATION.md §4-8. Timestamps are ISO-8601 UTC.
"""
from apps.videos.models import Video


def iso8601(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt is not None else None


def chapter_dict(chapter):
    return {
        "index": chapter.index,
        "title": chapter.title,
        "start_sec": chapter.start_sec,
        "end_sec": chapter.end_sec,
        "summary": chapter.summary or "",
        "thumbnail_sec": min(chapter.start_sec + 10, chapter.end_sec),
    }


def keyword_dict(keyword):
    return {"term": keyword.term, "score": keyword.score, "count": keyword.count}


def flashcard_dict(card):
    return {
        "card_id": str(card.id),
        "front": card.front,
        "back": card.back,
        "timestamp_sec": card.timestamp_sec,
        "difficulty": card.difficulty,
        "tags": list(card.tags or []),
    }


def base_video(video):
    return {
        "video_id": str(video.id),
        "youtube_id": video.youtube_id,
        "title": video.title,
        "thumbnail": video.thumbnail or "",
        "duration_sec": video.duration_sec,
        "status": video.status,
        "progress": video.progress,
        "created_at": iso8601(video.created_at),
    }


def progress_video(video):
    """Incomplete states (queued/processing/analyzing): status + progress only."""
    return base_video(video)


def detail_video(video, analytics=None):
    """Ready state: full dashboard payload."""
    chapters = [chapter_dict(c) for c in (video.chapters or [])]
    keywords = [keyword_dict(k) for k in (video.keywords or [])]
    if analytics is not None:
        stats = dict(analytics.stats or {})
        preview = {
            "top_keywords": list(stats.get("top_keywords", [k["term"] for k in keywords[:3]]))[:5],
            "chapter_count": len(chapters),
            "reading_minutes": stats.get("reading_minutes",
                                         max(0, (video.word_count or 0) // 200)),
        }
    else:
        preview = {
            "top_keywords": [k["term"] for k in keywords[:3]],
            "chapter_count": len(chapters),
            "reading_minutes": max(0, (video.word_count or 0) // 200),
        }
    payload = base_video(video)
    payload.update({
        "channel": video.channel or "",
        "transcript_source": video.transcript_source or "",
        "degraded": bool(video.degraded),
        "summary": video.summary or "",
        "chapters": chapters,
        "keywords": keywords,
        "flashcard_count": video.flashcard_count or 0,
        "analytics_preview": preview,
        "updated_at": iso8601(video.updated_at),
    })
    return payload


def list_item(video):
    item = base_video(video)
    item.pop("progress", None)
    return item


def video_lookup_or_none(video_id):
    """Return the Video doc or None (never raises on malformed ids)."""
    try:
        from bson import ObjectId
    except ImportError:
        return None
    if not video_id or not ObjectId.is_valid(video_id):
        return None
    return Video.objects(id=video_id).first()


__all__ = ["base_video", "progress_video", "detail_video", "list_item",
           "chapter_dict", "keyword_dict", "flashcard_dict",
           "video_lookup_or_none", "iso8601"]
