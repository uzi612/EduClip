"""T3 fallback safety verification (pipeline reliability pass).

Run: python apps/videos/tests/test_fallback_transcribe.py (needs repo root on PYTHONPATH)
"""
import os
import sys
import types
from unittest.mock import patch

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from services.fallback_transcribe import whisper_transcribe  # noqa: E402
from services.youtube import TranscriptUnavailableError  # noqa: E402

VID = "dQw4w9WgXcQ"


def _fake_modules(captured):
    class FakeYDL:
        def __init__(self, opts=None, *args, **kwargs):
            captured.update(opts or {})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, *args, **kwargs):
            return {"id": VID}

        def prepare_filename(self, info):
            return f"{info['id']}.mp3"

    fake_yt = types.ModuleType("yt_dlp")
    fake_yt.YoutubeDL = FakeYDL

    fake_fw = types.ModuleType("faster_whisper")

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *args, **kwargs):
            return [], None

    fake_fw.WhisperModel = FakeModel
    return {"yt_dlp": fake_yt, "faster_whisper": fake_fw}


def test_download_socket_timeout_is_bounded():
    captured = {}
    with patch.dict(sys.modules, _fake_modules(captured)):
        try:
            whisper_transcribe(VID, language="en")
        except TranscriptUnavailableError:
            pass  # empty segments without a real model — expected here
    assert captured.get("socket_timeout") == 20, captured


def test_download_failure_maps_to_retryable_unavailable():
    class FakeYDL:
        def __init__(self, opts=None, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, *args, **kwargs):
            raise RuntimeError("network stall")

        def prepare_filename(self, info):
            return "x.mp3"

    fake_yt = types.ModuleType("yt_dlp")
    fake_yt.YoutubeDL = FakeYDL
    fake_fw = types.ModuleType("faster_whisper")

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *args, **kwargs):
            return [], None

    fake_fw.WhisperModel = FakeModel
    with patch.dict(sys.modules, {"yt_dlp": fake_yt, "faster_whisper": fake_fw}):
        try:
            whisper_transcribe(VID, language="en")
        except TranscriptUnavailableError as exc:
            assert exc.retryable is True and exc.source == "whisper_fallback"
        else:
            raise AssertionError("expected TranscriptUnavailableError")


if __name__ == "__main__":
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    print("ALL FALLBACK-TRANSCRIBE CHECKS PASSED")
