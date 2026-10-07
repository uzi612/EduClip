"""YouTube transcript extraction engine (BACKEND-01).

Tier T1 of the 3-tier pipeline (see docs/ARCHITECTURE.md §5):
  T1 youtube-transcript-api → T2 captions API → T3 audio + Whisper fallback
  (T2/T3 live in services/fallback_transcribe.py; orchestration in
  apps/videos/transcribe.py).

youtube-transcript-api is imported lazily so `manage.py check` works without
optional ingestion dependencies installed.
"""
import re
from urllib.parse import parse_qs, urlparse

VIDEO_ID_PATTERN = r"[A-Za-z0-9_-]{11}"
VIDEO_ID_RE = re.compile(rf"^({VIDEO_ID_PATTERN})$")
YOUTUBE_ID_RES = [
    re.compile(r"(?:v=|/v/|/embed/|/live/|/shorts/)([A-Za-z0-9_-]{11})"),
    re.compile(rf"youtu\.be/({VIDEO_ID_PATTERN})"),
]
BRACKET_MARKER_RE = re.compile(r"^\s*\[[^\]]*\]\s*$")
MAX_FULL_TEXT_CHARS = 200_000
TRUNCATION_MARKER = "…[truncated]"

PREFERRED_LANGUAGES = ("en", "en-US", "en-GB")


class InvalidYouTubeURLError(ValueError):
    """Raised when a URL is not a watchable single-video YouTube URL."""


class TranscriptUnavailableError(Exception):
    """Raised when no transcript tier can produce segments."""

    def __init__(self, message, *, retryable=False, source=None):
        super().__init__(message)
        self.retryable = retryable
        self.source = source


def extract_video_id(url):
    """Extract the 11-char video ID from watch / youtu.be / shorts / embed / live URLs.

    Returns None for playlists, channels, handles, search, and non-YouTube URLs.
    """
    if not url or not isinstance(url, str):
        return None
    text = url.strip()
    if len(text) > 500:
        return None
    lowered = text.lower()
    for bad in ("/playlist", "/channel/", "/c/", "/user/", "/results", "/feed/", "/hashtag/"):
        if bad in lowered:
            return None
    if re.search(r"youtube\.com/@[A-Za-z0-9_.-]+", text):
        return None

    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = (parsed.hostname or "").lower().replace("m.", "", 1)
    if host not in ("youtube.com", "www.youtube.com", "youtu.be", "youtube-nocookie.com",
                    "www.youtube-nocookie.com"):
        # Bare ID form (handy for tests / internal callers).
        return text if VIDEO_ID_RE.match(text) else None

    if host == "youtu.be":
        m = re.search(rf"youtu\.be/({VIDEO_ID_PATTERN})", text)
        return m.group(1) if m else None

    qs = parse_qs(parsed.query)
    for candidate in qs.get("v", []):
        if VIDEO_ID_RE.match(candidate or ""):
            return candidate
    for pattern in YOUTUBE_ID_RES:
        m = pattern.search(text)
        if m and VIDEO_ID_RE.match(m.group(1)):
            return m.group(1)
    return None


def _snippet_to_dict(snippet):
    if isinstance(snippet, dict):
        return {
            "start": float(snippet.get("start", 0.0)),
            "duration": float(snippet.get("duration", 0.0)),
            "text": str(snippet.get("text", "")),
        }
    get = lambda name, default=0.0: getattr(snippet, name, snippet.get(name, default)) \
        if isinstance(snippet, dict) else getattr(snippet, name, default)
    text = getattr(snippet, "text", "")
    if isinstance(snippet, dict):
        text = snippet.get("text", "")
    return {"start": float(get("start")), "duration": float(get("duration")), "text": str(text)}


def fetch_transcript(youtube_id, languages=PREFERRED_LANGUAGES):
    """Fetch timed captions (T1). Returns (segments, source).

    Raises TranscriptUnavailableError with retryable=True for IP/rate blocks
    (caller should try the next tier) and retryable=False when the video has
    no captions or does not exist.
    """
    if not youtube_id or not VIDEO_ID_RE.match(youtube_id):
        raise InvalidYouTubeURLError(f"Not a valid YouTube video ID: {youtube_id!r}")
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise TranscriptUnavailableError(
            "youtube-transcript-api is not installed.", retryable=False,
            source="youtube_captions",
        ) from exc

    from youtube_transcript_api._errors import (
        IpBlocked,
        NoTranscriptFound,
        RequestBlocked,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    api = YouTubeTranscriptApi()
    try:
        try:
            transcript = api.list(youtube_id).find_transcript(list(languages))
        except NoTranscriptFound:
            try:
                transcript = api.list(youtube_id).find_generated_transcript(["en"])
            except Exception:
                transcript = next(iter(api.list(youtube_id)))
        fetched = transcript.fetch()
    except TranscriptsDisabled as exc:
        raise TranscriptUnavailableError(
            f"Captions are disabled for video {youtube_id}.", retryable=False,
            source="youtube_captions",
        ) from exc
    except NoTranscriptFound as exc:
        raise TranscriptUnavailableError(
            f"No transcript found for video {youtube_id}.", retryable=False,
            source="youtube_captions",
        ) from exc
    except VideoUnavailable as exc:
        raise TranscriptUnavailableError(
            f"Video {youtube_id} is unavailable.", retryable=False,
            source="youtube_captions",
        ) from exc
    except (IpBlocked, RequestBlocked) as exc:
        raise TranscriptUnavailableError(
            "Transcript fetch was rate-limited/blocked; trying fallback tier.",
            retryable=True, source="youtube_captions",
        ) from exc
    except Exception as exc:
        raise TranscriptUnavailableError(
            f"Transcript fetch failed for video {youtube_id}: {exc}",
            retryable=True, source="youtube_captions",
        ) from exc

    segments = [_snippet_to_dict(s) for s in fetched]
    if not segments:
        raise TranscriptUnavailableError(
            f"Empty transcript for video {youtube_id}.", retryable=False,
            source="youtube_captions",
        )
    return segments, "youtube_captions"


def normalize_segments(segments, merge_gap=1.2, max_chars=MAX_FULL_TEXT_CHARS):
    """Clean raw segments. Returns (segments, full_text).

    - Drops fully-bracketed markers (`[Music]`, `[Applause]`) and empties.
    - Merges segments separated by less than `merge_gap` seconds.
    - Caps joined text at `max_chars` with a truncation marker.
    """
    cleaned = []
    for seg in segments or []:
        text = " ".join(str(seg.get("text", "")).split())
        if not text or BRACKET_MARKER_RE.match(text):
            continue
        cleaned.append({
            "start": float(seg.get("start", 0.0)),
            "duration": float(seg.get("duration", 0.0)),
            "text": text,
        })
    merged = []
    for seg in sorted(cleaned, key=lambda s: s["start"]):
        if merged and seg["start"] - (merged[-1]["start"] + merged[-1]["duration"]) < merge_gap:
            prev = merged[-1]
            prev["duration"] = (seg["start"] + seg["duration"]) - prev["start"]
            prev["text"] = f"{prev['text']} {seg['text']}"
        else:
            merged.append(dict(seg))
    full_text = " ".join(s["text"] for s in merged)
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + TRUNCATION_MARKER
    return merged, full_text


def get_video_metadata(youtube_id):
    """Fetch title/channel/duration via YouTube Data API v3 when configured.

    Without YOUTUBE_API_KEY returns thumbnail-only metadata so ingestion can
    still proceed (transcript-first prototype mode).
    """
    from django.conf import settings

    meta = {
        "youtube_id": youtube_id,
        "title": "",
        "channel": "",
        "thumbnail": f"https://i.ytimg.com/vi/{youtube_id}/hqdefault.jpg",
        "duration_sec": 0,
    }
    api_key = getattr(settings, "YOUTUBE_API_KEY", "") or ""
    if not api_key:
        return meta
    try:
        from googleapiclient.discovery import build

        yt = build("youtube", "v3", developerKey=api_key)
        resp = yt.videos().list(part="snippet,contentDetails", id=youtube_id).execute()
        items = resp.get("items", [])
        if not items:
            raise TranscriptUnavailableError(
                f"Video {youtube_id} not found.", retryable=False, source="metadata")
        snippet = items[0].get("snippet", {})
        meta.update({
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "thumbnail": (snippet.get("thumbnails", {}).get("high", {}).get("url")
                          or meta["thumbnail"]),
        })
        return meta
    except TranscriptUnavailableError:
        raise
    except Exception as exc:
        raise TranscriptUnavailableError(
            f"Metadata lookup failed for video {youtube_id}: {exc}",
            retryable=True, source="metadata",
        ) from exc
