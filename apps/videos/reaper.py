"""Stale-job reaper (pipeline reliability pass).

Fails videos stranded in a non-terminal status whose `updated_at` is older
than the window. This is the safety net for worker crashes / lost tasks that
acks_late + task_reject_on_worker_lost cannot fully cover (e.g. a worker
OOM-killed before Redis records delivery).

The pipeline bumps `updated_at` on every checkpoint, so any video that has
not been touched for EDUCLIP_REAP_MINUTES (default 15) while still
queued/processing/analyzing is assumed dead and marked `failed` so the user
can resubmit.
"""
import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def reap_stale_videos(max_age_minutes=None, now=None):
    """Fail every active-status video older than the window. Returns count."""
    from apps.videos.models import Video

    if max_age_minutes is None:
        try:
            max_age_minutes = int(os.getenv("EDUCLIP_REAP_MINUTES", "15"))
        except ValueError:
            max_age_minutes = 15
    now = now or datetime.utcnow()
    cutoff = now - timedelta(minutes=max_age_minutes)
    stranded = Video.objects(
        status__in=("queued", "processing", "analyzing"),
        updated_at__lt=cutoff,
    ).only("id", "status")
    reaped = 0
    for video in stranded:
        video.update(
            set__status="failed",
            set__progress=0.0,
            set__error=(
                f"Processing stalled in '{video.status}' for over "
                f"{max_age_minutes} minutes. Submit the video again to retry."
            ),
        )
        reaped += 1
        logger.warning("reaped stranded video: video_id=%s previous_status=%s",
                       video.id, video.status)
    return reaped
