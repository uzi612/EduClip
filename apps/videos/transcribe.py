"""Transcription orchestration: T1 → T2 → T3 (BACKEND-01).

Used by the Celery pipeline (BACKEND-03). Returns (segments, source) where
source is one of youtube_captions / captions_api / whisper_fallback.
Raises TranscriptUnavailableError only when every tier fails.
"""
from services import fallback_transcribe
from services.youtube import TranscriptUnavailableError, fetch_transcript, normalize_segments


def transcribe_video(youtube_id, languages=("en", "en-US", "en-GB"), credentials=None):
    """Run the fallback chain and return normalized (segments, full_text, source)."""
    last_error = None
    try:
        segments, source = fetch_transcript(youtube_id, languages=languages)
        cleaned, full_text = normalize_segments(segments)
        if cleaned:
            return cleaned, full_text, source
        last_error = TranscriptUnavailableError("Empty transcript after normalization.",
                                                retryable=False, source=source)
    except TranscriptUnavailableError as exc:
        # Any T1 failure falls through to T2/T3; only invalid URLs
        # (InvalidYouTubeURLError) abort immediately.
        last_error = exc

    # T2 only when OAuth credentials exist; otherwise straight to T3 audio.
    if credentials is not None:
        try:
            segments, source = fallback_transcribe.captions_api_download(
                youtube_id, credentials=credentials)
            cleaned, full_text = normalize_segments(segments)
            if cleaned:
                return cleaned, full_text, source
        except TranscriptUnavailableError as exc:
            last_error = exc

    segments, source = fallback_transcribe.whisper_transcribe(youtube_id)
    cleaned, full_text = normalize_segments(segments)
    if not cleaned:
        raise TranscriptUnavailableError(
            "No transcript available from any tier.", retryable=False,
            source=source) from last_error
    return cleaned, full_text, source
