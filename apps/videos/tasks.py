"""Celery pipeline: transcribe -> analyze -> persist (BACKEND-03).

Queues: transcribe (IO-bound). Analytics *graphs* are intentionally not built
here — CHARTS-04 adds the Chart.js formatters; flashcards + video fields are
persisted now. See docs/ARCHITECTURE.md §8 for the status contract.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="transcribe",
             name="apps.videos.tasks.process_video_task")
def process_video_task(self, video_id):
    from apps.analytics.pipeline import run_analysis
    from apps.flashcards.models import Flashcard
    from apps.videos import transcribe as transcribe_mod
    from apps.videos.db import ensure_mongoengine
    from apps.videos.models import Chapter, Keyword, TranscriptSegment, Video

    ensure_mongoengine()
    video = Video.objects(id=video_id).first()
    if video is None:
        logger.warning("process_video_task: unknown video %s", video_id)
        return {"status": "failed", "error": "unknown video"}
    if video.status == "ready":
        return {"status": "ready", "video_id": video_id}

    try:
        video.update(set__status="processing", set__progress=0.2)
        video.reload()
        segments, full_text, source = transcribe_mod.transcribe_video(video.youtube_id)
        video.update(
            set__transcript_segments=[
                TranscriptSegment(start=s["start"], duration=s["duration"], text=s["text"])
                for s in segments
            ],
            set__full_text=full_text,
            set__word_count=len(full_text.split()),
            set__transcript_source=source,
            set__status="analyzing",
            set__progress=0.7,
        )
        video.reload()
        result = run_analysis(segments, video.title, video.duration_sec)
        cards = result.get("flashcards", [])[:20]
        video.update(
            set__summary=result.get("summary", ""),
            set__chapters=[
                Chapter(index=c["index"], title=c["title"], start_sec=c["start_sec"],
                        end_sec=c["end_sec"], summary=c.get("summary", ""),
                        keyword_refs=c.get("keyword_refs", []))
                for c in result.get("chapters", [])
            ],
            set__keywords=[
                Keyword(term=k["term"], score=k["score"], count=k["count"])
                for k in result.get("keywords", [])
            ],
            set__flashcard_count=len(cards),
            set__degraded=bool(result.get("degraded", False)),
            set__status="ready",
            set__progress=1.0,
        )
        Flashcard.objects(video_id=video).delete()
        for card in cards:
            Flashcard(video_id=video, front=card["front"], back=card["back"],
                      timestamp_sec=card.get("timestamp_sec", 0)).save()
        logger.info("process_video_task: %s ready (degraded=%s)", video_id,
                    result.get("degraded", False))
        return {"status": "ready", "video_id": video_id,
                "degraded": bool(result.get("degraded", False))}
    except Exception as exc:
        try:
            video.update(set__status="failed", set__error=str(exc)[:500])
        except Exception:
            pass
        logger.exception("process_video_task: %s failed", video_id)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)
