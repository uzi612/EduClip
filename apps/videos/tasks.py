"""Celery pipeline: transcribe -> analyze -> persist (BACKEND-03, CHARTS-04).

Reliability contract (see apps/videos/reaper.py + docs/ARCHITECTURE.md §8):
- Terminal `failed` is written only when retries are exhausted or the error
  is non-retryable. Mid-flight retries keep the video at its last checkpoint
  status so the 3s poll contract stays non-terminal while work continues.
- A task whose video record has been re-dispatched (user resubmitted while a
  retry was pending) is superseded and no-ops instead of racing the live task.
- `ready` is flipped only AFTER flashcards/MCQs/analytics exist, so a crash
  between payload build and side-collection writes leaves the video at
  `analyzing` (recoverable) — never a lying `ready` with an empty dashboard.
- Every checkpoint bumps `updated_at`, the age signal the stale-job reaper
  uses to fail videos stranded by worker crashes (acks_late + reaper cover
  the rest).
"""
from datetime import datetime

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


def _now():
    return datetime.utcnow()


@shared_task(bind=True, max_retries=3, queue="transcribe",
             name="apps.videos.tasks.process_video_task")
def process_video_task(self, video_id):
    from apps.analytics.models import Analytics
    from apps.analytics.pipeline import run_analysis
    from apps.flashcards.models import Flashcard
    from apps.quiz.models import MCQ
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

    task_id = getattr(self.request, "id", None)
    owner = str(video.task_id) if video.task_id else None
    if owner and task_id is not None and str(task_id) != owner:
        logger.warning("task superseded: task_id=%s video_id=%s owner=%s -> giving up",
                       task_id, video_id, owner)
        return {"status": "superseded", "video_id": video_id}

    logger.info("task received: task_id=%s video_id=%s youtube_id=%s", task_id,
                video_id, video.youtube_id)
    try:
        video.update(set__status="processing", set__progress=0.2,
                     set__updated_at=_now())
        video.reload()
        lang = (video.language or "en").strip()[:10]
        if lang and lang != "en":
            languages = (lang, "en", "en-US", "en-GB")
        else:
            languages = ("en", "en-US", "en-GB")
        segments, full_text, source = transcribe_mod.transcribe_video(
            video.youtube_id, languages=languages, whisper_language=lang)
        logger.info("task transcribed: task_id=%s video_id=%s source=%s segments=%d",
                    task_id, video_id, source, len(segments))
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
            set__updated_at=_now(),
        )
        video.reload()
        logger.info("task analyzing: task_id=%s video_id=%s", task_id, video_id)
        result = run_analysis(segments, video.title, video.duration_sec)
        cards = result.get("flashcards", [])[:20]
        questions = result.get("mcqs", [])[:8]
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
            set__mcq_count=len(questions),
            set__degraded=bool(result.get("degraded", False)),
            set__updated_at=_now(),
        )
        video.reload()
        logger.info("task persisting side collections: task_id=%s video_id=%s",
                    task_id, video_id)
        Flashcard.objects(video_id=video).delete()
        for card in cards:
            Flashcard(video_id=video, front=card["front"], back=card["back"],
                      timestamp_sec=card.get("timestamp_sec", 0)).save()
        MCQ.objects(video_id=video).delete()
        for question in questions:
            MCQ(video_id=video, question=question["question"],
                options=question["options"], answer_index=question["answer_index"],
                explanation=question["explanation"],
                timestamp_sec=question.get("timestamp_sec", 0)).save()
        Analytics.objects(video_id=video).update_one(
            set__stats=result.get("stats", {}),
            set__graphs=result.get("graphs", {}),
            upsert=True,
        )
        video.update(set__status="ready", set__progress=1.0, set__updated_at=_now())
        video.reload()
        logger.info("task ready: task_id=%s video_id=%s degraded=%s cards=%d",
                    task_id, video_id, result.get("degraded", False), len(cards))
        return {"status": "ready", "video_id": video_id,
                "degraded": bool(result.get("degraded", False))}
    except Exception as exc:
        retryable = getattr(exc, "retryable", True)
        attempts_exhausted = self.request.retries >= self.max_retries
        ownership_lost = False
        try:
            video.reload()
            owner_now = video.task_id
            ownership_lost = bool(owner_now) and task_id is not None \
                and str(owner_now) != str(task_id)
        except Exception:
            ownership_lost = True  # deleted or unreachable mid-run; touch nothing
        if ownership_lost:
            logger.warning("task displaced mid-run: task_id=%s video_id=%s -> not "
                           "touching the row", task_id, video_id)
            return {"status": "superseded", "video_id": video_id}
        if retryable and not attempts_exhausted:
            logger.exception(
                "task retry scheduled: task_id=%s video_id=%s attempt=%d err=%s",
                task_id, video_id, self.request.retries + 1, exc)
            raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)
        try:
            video.update(set__status="failed", set__error=str(exc)[:500],
                         set__progress=0.0)
        except Exception:
            logger.exception("could not mark video failed: task_id=%s video_id=%s",
                             task_id, video_id)
        logger.exception("task gave up: task_id=%s video_id=%s retryable=%s "
                         "exhausted=%s err=%s", task_id, video_id, retryable,
                         attempts_exhausted, exc)
        raise


@shared_task(queue="default", name="apps.videos.tasks.reap_stale_videos_task")
def reap_stale_videos_task(max_age_minutes=None):
    from apps.videos.reaper import reap_stale_videos

    reaped = reap_stale_videos(max_age_minutes)
    if reaped:
        logger.warning("reaper failed %d stranded videos", reaped)
    return {"reaped": reaped}
