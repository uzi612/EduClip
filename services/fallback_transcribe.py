"""Fallback transcription tiers T2/T3 (BACKEND-01).

T2: YouTube Data API v3 captions.download (needs OAuth user credentials).
T3: audio download via yt-dlp + local transcription via faster-whisper.
Both are imported lazily; missing optional dependencies raise a clear
TranscriptUnavailableError instead of breaking `manage.py check`.

Successful T3 results are marked `transcript_source="whisper_fallback"`.
See docs/ARCHITECTURE.md §5.
"""
import os
import tempfile

from services.youtube import TranscriptUnavailableError


def captions_api_download(youtube_id, credentials=None):
    """Tier T2: download an official caption track. Requires OAuth credentials."""
    if credentials is None:
        raise TranscriptUnavailableError(
            "No OAuth credentials for captions.download; skipping to audio fallback.",
            retryable=False, source="captions_api",
        )
    try:
        from googleapiclient.discovery import build

        yt = build("youtube", "v3", credentials=credentials)
        tracks = yt.captions().list(part="snippet", videoId=youtube_id).execute().get("items", [])
        if not tracks:
            raise TranscriptUnavailableError(
                f"No caption tracks for video {youtube_id}.",
                retryable=False, source="captions_api",
            )
        track_id = tracks[0]["id"]
        data = yt.captions().download(id=track_id, tfmt="vtt").execute()
        return _vtt_to_segments(data.decode("utf-8", "replace")), "captions_api"
    except TranscriptUnavailableError:
        raise
    except Exception as exc:
        raise TranscriptUnavailableError(
            f"captions.download failed for video {youtube_id}: {exc}",
            retryable=True, source="captions_api",
        ) from exc


def _vtt_to_segments(vtt):
    import re

    def ts_to_sec(ts):
        h, m, rest = ts.split(":")
        s = rest.replace(",", ".")
        return int(h) * 3600 + int(m) * 60 + float(s)

    blocks = re.split(r"\n\s*\n", vtt)
    segments, stamp = [], re.compile(r"(\d+:\d+:\d+[.,]\d+)\s+-->\s+(\d+:\d+:\d+[.,]\d+)")
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines or lines[0].upper() == "WEBVTT":
            continue
        m = stamp.search(lines[0])
        body_start = 1 if m else 0
        if not m and len(lines) > 1:
            m = stamp.search(lines[1])
            body_start = 2
        if not m:
            continue
        start, end = ts_to_sec(m.group(1)), ts_to_sec(m.group(2))
        text = " ".join(lines[body_start:]).strip()
        if text:
            segments.append({"start": start, "duration": max(0.0, end - start), "text": text})
    if not segments:
        raise TranscriptUnavailableError("Caption track contained no cues.", retryable=False,
                                         source="captions_api")
    return segments


def whisper_transcribe(youtube_id, language="en", model_size="base"):
    """Tier T3: download audio and transcribe locally. Returns (segments, source)."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise TranscriptUnavailableError(
            "yt-dlp is not installed; audio fallback unavailable.",
            retryable=False, source="whisper_fallback",
        ) from exc
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptUnavailableError(
            "faster-whisper is not installed; audio fallback unavailable.",
            retryable=False, source="whisper_fallback",
        ) from exc

    try:
        with tempfile.TemporaryDirectory(prefix="educlip-audio-") as tmp:
            target = os.path.join(tmp, "%(id)s.%(ext)s")
            with yt_dlp.YoutubeDL({
                "format": "bestaudio/best", "outtmpl": target,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
                "quiet": True, "no_warnings": True,
            }) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={youtube_id}", download=True)
                audio_path = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".mp3"
            model = WhisperModel(model_size, compute_type="int8")
            raw_segments, _ = model.transcribe(audio_path, language=language, vad_filter=True)
            segments = [
                {"start": float(s.start), "duration": float(max(0.0, s.end - s.start)),
                 "text": " ".join(s.text.split())}
                for s in raw_segments if s.text and s.text.strip()
            ]
    except TranscriptUnavailableError:
        raise
    except Exception as exc:
        raise TranscriptUnavailableError(
            f"Audio fallback failed for video {youtube_id}: {exc}",
            retryable=True, source="whisper_fallback",
        ) from exc
    if not segments:
        raise TranscriptUnavailableError(
            f"Audio fallback produced no segments for video {youtube_id}.",
            retryable=False, source="whisper_fallback",
        )
    return segments, "whisper_fallback"
