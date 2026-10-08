"""Video ingestion service: dedupe + creation (BACKEND-03).

Dedupe contract (docs/API_SPECIFICATION.md §3):
- Same youtube_id with status in queued/processing/analyzing/ready → reuse,
  never re-queue.
- A `failed` record is reset to queued so the user can retry.
"""
from datetime import datetime

ACTIVE_STATUSES = ("queued", "processing", "analyzing", "ready")


def get_or_create_video(youtube_id, metadata, idempotency_key=""):
    """Return (video, created). Raises mongoengine ValidationError on bad data."""
    from apps.videos.models import Video

    existing = Video.objects(youtube_id=youtube_id).first()
    if existing is not None and existing.status in ACTIVE_STATUSES:
        return existing, False
    now = datetime.utcnow()
    if existing is not None:  # failed → reset for retry
        existing.update(
            set__status="queued", set__progress=0.05, set__error=None,
            set__task_id=None, set__degraded=False,
            set__title=metadata.get("title", existing.title),
            set__channel=metadata.get("channel", existing.channel),
            set__thumbnail=metadata.get("thumbnail", existing.thumbnail),
            set__idempotency_key=idempotency_key, set__updated_at=now,
        )
        existing.reload()
        return existing, True
    video = Video(
        youtube_id=youtube_id,
        title=metadata.get("title", "") or f"YouTube video {youtube_id}",
        channel=metadata.get("channel", ""),
        thumbnail=metadata.get("thumbnail", ""),
        duration_sec=int(metadata.get("duration_sec", 0) or 0),
        status="queued",
        progress=0.05,
        idempotency_key=idempotency_key,
    ).save()
    return video, True
