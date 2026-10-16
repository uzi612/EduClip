"""Bot-check mitigation tests: hardened yt-dlp opts, cookie wiring, sanitized errors.

Run: python -m pytest apps/videos/tests/test_botcheck_mitigation.py
No network: yt_dlp.YoutubeDL is mocked in every test.
"""
import os
from unittest.mock import MagicMock, patch

from services import fallback_transcribe as fallback
from services.fallback_transcribe import (
    _ytdlp_opts,
    is_botcheck_error,
    whisper_transcribe,
)
from services.youtube import (
    YOUTUBE_PLAYER_CLIENTS,
    TranscriptUnavailableError,
    _metadata_without_key,
)

BOT_MSG = ("ERROR: [youtube] abc12345678: Sign in to confirm you're not a bot. "
           "Use --cookies-from-browser or --cookies for the authentication.")


def test_player_clients_android_first():
    assert YOUTUBE_PLAYER_CLIENTS[0] == "android"
    assert "web" in YOUTUBE_PLAYER_CLIENTS
    opts = _ytdlp_opts()
    assert opts["extractor_args"]["youtube"]["player_client"] == ["android", "web"]


def test_cookiefile_wired_only_when_file_exists(tmp_path):
    with patch.dict(os.environ, {"YOUTUBE_COOKIES_PATH": str(tmp_path / "nope.txt")}):
        assert "cookiefile" not in _ytdlp_opts()
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    with patch.dict(os.environ, {"YOUTUBE_COOKIES_PATH": str(cookies)}):
        assert _ytdlp_opts()["cookiefile"] == str(cookies)


def test_ffmpeg_location_wired_only_when_dir_exists(tmp_path):
    with patch.dict(os.environ, {"FFMPEG_LOCATION": str(tmp_path / "nodir")}):
        assert "ffmpeg_location" not in _ytdlp_opts()
    with patch.dict(os.environ, {"FFMPEG_LOCATION": str(tmp_path)}):
        assert _ytdlp_opts()["ffmpeg_location"] == str(tmp_path)


def test_av_open_shim_strips_removed_kwarg():
    import types

    from services.fallback_transcribe import _patch_av_open

    calls = []

    def strict_open(*args, **kwargs):
        if "metadata_errors" in kwargs:
            raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
        calls.append((args, kwargs))
        return "opened"

    fake_av = types.SimpleNamespace(open=strict_open)
    assert _patch_av_open(fake_av, needs_shim=True) is True
    assert fake_av.open("f.mp3", metadata_errors="ignore") == "opened"
    assert calls[0][1] == {}
    # Second call is a no-op (already shimmed).
    assert _patch_av_open(fake_av, needs_shim=True) is False


def test_av_open_shim_noop_when_not_needed():
    import types

    from services.fallback_transcribe import _patch_av_open

    def legacy_open(path, metadata_errors=None):
        return "legacy"

    fake_av = types.SimpleNamespace(open=legacy_open)
    assert _patch_av_open(fake_av, needs_shim=False) is False
    assert fake_av.open is legacy_open


def test_av_probe_detects_rejection_on_this_env():
    from services.fallback_transcribe import _av_rejects_metadata_errors

    # Live PyAV is v19 (kwarg removed) — the probe must say shim-needed.
    assert _av_rejects_metadata_errors() is True


def test_is_botcheck_error():
    assert is_botcheck_error(BOT_MSG)
    assert is_botcheck_error("sign in to confirm you’re not a bot")  # curly apostrophe
    assert not is_botcheck_error("HTTP Error 429: Too Many Requests")
    assert not is_botcheck_error("")
    assert not is_botcheck_error(None)


def test_whisper_botcheck_error_is_sanitized_and_retryable():
    with patch("yt_dlp.YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.side_effect = Exception(BOT_MSG)
        try:
            whisper_transcribe("abc12345678")
        except TranscriptUnavailableError as exc:
            assert exc.retryable is True
            assert exc.source == "whisper_fallback"
            assert "bot-check" in str(exc)
            assert "YOUTUBE_COOKIES_PATH" in str(exc)
            assert "github.com/yt-dlp" not in str(exc)  # no raw FAQ dump
            return
    raise AssertionError("expected TranscriptUnavailableError")


def test_whisper_other_errors_keep_raw_cause():
    with patch("yt_dlp.YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.side_effect = Exception("disk on fire")
        try:
            whisper_transcribe("abc12345678")
        except TranscriptUnavailableError as exc:
            assert "disk on fire" in str(exc)
            return
    raise AssertionError("expected TranscriptUnavailableError")


def test_metadata_uses_hardened_opts():
    info = {"title": "T", "channel": "C", "thumbnail": "http://t.jpg", "duration": 90}
    with patch("yt_dlp.YoutubeDL") as ydl_cls:
        inst = ydl_cls.return_value.__enter__.return_value
        inst.extract_info.return_value = dict(info)
        meta = {"youtube_id": "abc12345678", "title": "", "channel": "",
                "thumbnail": "http://d.jpg", "duration_sec": 0}
        out = _metadata_without_key("abc12345678", meta)
    assert out["duration_sec"] == 90 and out["title"] == "T"
    passed_opts = ydl_cls.call_args[0][0]
    assert passed_opts["extractor_args"]["youtube"]["player_client"][0] == "android"
