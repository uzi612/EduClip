"""BACKEND-01 verification: URL parsing, normalization, tier mapping.

Run: python apps/videos/tests/test_youtube.py
"""
from unittest.mock import MagicMock, patch

from services.youtube import (
    InvalidYouTubeURLError,
    TranscriptUnavailableError,
    extract_video_id,
    fetch_transcript,
    normalize_segments,
)

VID = "dQw4w9WgXcQ"

URL_CASES = [
    (f"https://www.youtube.com/watch?v={VID}", VID),
    (f"https://www.youtube.com/watch?v={VID}&t=42s", VID),
    (f"https://www.youtube.com/watch?v={VID}&list=PLabc123", VID),
    (f"https://youtu.be/{VID}", VID),
    (f"https://youtu.be/{VID}?t=42", VID),
    (f"https://www.youtube.com/shorts/{VID}", VID),
    (f"https://m.youtube.com/watch?v={VID}", VID),
    (f"https://www.youtube.com/embed/{VID}", VID),
    (f"https://www.youtube.com/live/{VID}", VID),
    (f"youtube.com/watch?v={VID}", VID),
    (f"www.youtube.com/watch?v={VID}", VID),
    (f"https://www.youtube.com/watch?app=desktop&v={VID}", VID),
    (f"https://www.youtube.com/watch?v={VID}#t=1m2s", VID),
    (f"https://www.youtube-nocookie.com/embed/{VID}", VID),
    (VID, VID),  # bare ID passthrough
]

BAD_URLS = [
    "https://www.youtube.com/playlist?list=PLabc123",
    "https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw",
    "https://www.youtube.com/@somecreator",
    "https://www.youtube.com/results?search_query=cats",
    "https://www.youtube.com/feed/trending",
    "https://vimeo.com/123456789",
    "not a url at all",
    "",
    None,
    "https://www.youtube.com/watch?v=short",
    "x" * 501,
]


def _snip(start, duration, text):
    s = MagicMock()
    s.start, s.duration, s.text = start, duration, text
    return s


def _mock_api(fetch_result=None, find_side_effect=None):
    api = MagicMock()
    listing = MagicMock()
    track = MagicMock()
    if find_side_effect is not None:
        listing.find_transcript.side_effect = find_side_effect
    track.fetch.return_value = fetch_result or []
    if find_side_effect is None:
        listing.find_transcript.return_value = track
    api.list.return_value = listing
    return api


def test_url_variants():
    for url, expected in URL_CASES:
        got = extract_video_id(url)
        assert got == expected, f"{url} -> {got!r}, expected {expected!r}"


def test_bad_urls_rejected():
    for url in BAD_URLS:
        assert extract_video_id(url) is None, f"should reject {url!r}"


def test_normalize_strips_merges_caps():
    segs = [
        {"start": 0.0, "duration": 3.0, "text": "Hello world"},
        {"start": 3.5, "duration": 2.0, "text": "[Music]"},
        {"start": 3.8, "duration": 2.0, "text": "  second   sentence "},
        {"start": 30.0, "duration": 2.0, "text": "[Applause]"},
        {"start": 40.0, "duration": 1.0, "text": "far away"},
    ]
    merged, full = normalize_segments(segs)
    assert [s["text"] for s in merged] == ["Hello world second sentence", "far away"], merged
    assert "[Music]" not in full and "[Applause]" not in full
    merged2, full2 = normalize_segments(
        [{"start": 0.0, "duration": 1.0, "text": "y" * 100}], max_chars=10)
    assert full2.endswith("…[truncated]") and len(merged2) == 1


def test_fetch_success_and_invalid_id():
    api = _mock_api([_snip(0.0, 3.0, "hi")])
    with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=api):
        segs, source = fetch_transcript(VID)
    assert source == "youtube_captions" and segs[0]["text"] == "hi"
    try:
        fetch_transcript("short")
    except InvalidYouTubeURLError:
        pass
    else:
        raise AssertionError("expected InvalidYouTubeURLError")


def test_fetch_error_mapping():
    from youtube_transcript_api._errors import IpBlocked, TranscriptsDisabled

    api = _mock_api(find_side_effect=TranscriptsDisabled("x"))
    with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=api):
        try:
            fetch_transcript(VID)
        except TranscriptUnavailableError as exc:
            assert exc.retryable is False
        else:
            raise AssertionError("expected TranscriptUnavailableError (disabled)")

    api = _mock_api(find_side_effect=IpBlocked("blocked"))
    with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=api):
        try:
            fetch_transcript(VID)
        except TranscriptUnavailableError as exc:
            assert exc.retryable is True
        else:
            raise AssertionError("expected retryable TranscriptUnavailableError (blocked)")


def test_orchestrator_falls_back_to_whisper():
    from youtube_transcript_api._errors import NoTranscriptFound

    from apps.videos import transcribe as orch

    api = _mock_api(find_side_effect=NoTranscriptFound(VID, ["en"], {}))
    with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=api), patch.object(
        orch.fallback_transcribe, "whisper_transcribe",
        return_value=([{"start": 0.0, "duration": 2.0, "text": "audio words"}],
                      "whisper_fallback"),
    ):
        cleaned, full, source = orch.transcribe_video(VID)
    assert source == "whisper_fallback" and full == "audio words" and cleaned[0]["start"] == 0.0


def test_long_cue_splits_without_loss():
    # Regression: real auto-caption cues can exceed the 500-char document cap
    # (video IecCQPX-QsI failed the whole pipeline before this).
    long_text = ("Sentence one about portfolios. Sentence two about interviews. " * 20).strip()
    segs, _ = normalize_segments([{"start": 10.0, "duration": 120.0, "text": long_text}])
    assert len(segs) > 1 and all(len(s["text"]) <= 490 for s in segs)
    assert " ".join(s["text"] for s in segs) == long_text
    assert segs[0]["start"] == 10.0
    assert segs[-1]["start"] + segs[-1]["duration"] == 130.0


if __name__ == "__main__":
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    print("ALL BACKEND-01 CHECKS PASSED")
