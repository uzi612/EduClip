"""Transcription orchestration: T1 → T2 → T3 (BACKEND-01).

Used by the Celery pipeline (BACKEND-03). Returns (segments, source) where
source is one of youtube_captions / captions_api / whisper_fallback.
Raises TranscriptUnavailableError only when every tier fails. Each tier
boundary is logged so terminal output pinpoints transcript vs LLM failures.
"""
import logging
import time

from services import fallback_transcribe
from services.youtube import TranscriptUnavailableError, fetch_transcript, normalize_segments

logger = logging.getLogger(__name__)


def transcribe_video(youtube_id, languages=("en", "en-US", "en-GB"), credentials=None,
                     transcript_timeout_sec=None):
    """Run the fallback chain and return normalized (segments, full_text, source)."""
    timeout_kw = {} if transcript_timeout_sec is None else {
        "timeout_sec": transcript_timeout_sec}
    logger.info("transcribe start: video=%s", youtube_id)
    started = time.perf_counter()
    last_error = None
    try:
        segments, source = fetch_transcript(youtube_id, languages=languages, **timeout_kw)
        cleaned, full_text = normalize_segments(segments)
        if cleaned:
            logger.info("transcribe tier ok: video=%s tier=%s segments=%d ms=%d",
                        youtube_id, source, len(cleaned),
                        int((time.perf_counter() - started) * 1000))
            return cleaned, full_text, source
        last_error = TranscriptUnavailableError("Empty transcript after normalization.",
                                                retryable=False, source=source)
    except TranscriptUnavailableError as exc:
        # Any T1 failure falls through to T2/T3; only invalid URLs
        # (InvalidYouTubeURLError) abort immediately.
        logger.warning("transcribe tier failed: video=%s tier=youtube_captions "
                       "retryable=%s err=%s", youtube_id, exc.retryable, exc)
        last_error = exc

    # T2 only when OAuth credentials exist; otherwise straight to T3 audio.
    if credentials is not None:
        try:
            segments, source = fallback_transcribe.captions_api_download(
                youtube_id, credentials=credentials)
            cleaned, full_text = normalize_segments(segments)
            if cleaned:
                logger.info("transcribe tier ok: video=%s tier=%s segments=%d",
                            youtube_id, source, len(cleaned))
                return cleaned, full_text, source
        except TranscriptUnavailableError as exc:
            logger.warning("transcribe tier failed: video=%s tier=captions_api "
                           "retryable=%s err=%s", youtube_id, exc.retryable, exc)
            last_error = exc

    logger.info("transcribe tier start: video=%s tier=whisper_fallback", youtube_id)
    segments, source = fallback_transcribe.whisper_transcribe(youtube_id)
    cleaned, full_text = normalize_segments(segments)
    if not cleaned:
        raise TranscriptUnavailableError(
            "No transcript available from any tier.", retryable=False,
            source=source) from last_error
    logger.info("transcribe tier ok: video=%s tier=%s segments=%d ms=%d",
                youtube_id, source, len(cleaned),
                int((time.perf_counter() - started) * 1000))
    return cleaned, full_text, source
