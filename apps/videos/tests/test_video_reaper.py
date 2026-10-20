"""Stale-job reaper verification (pipeline reliability pass).

Run: python apps/videos/tests/test_video_reaper.py (needs repo root on PYTHONPATH)
"""
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

import mongomock  # noqa: E402
import mongoengine as me  # noqa: E402

from apps.videos.models import Video  # noqa: E402
from apps.videos.video_service import get_or_create_video  # noqa: E402

META = {"title": "T", "channel": "C",
        "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "duration_sec": 600}
_SEQ = 0


def setup_module():
    me.disconnect_all()
    me.connect("educlip-reaper-test", mongo_client_class=mongomock.MongoClient)


def teardown_module():
    me.disconnect_all()


def _clean():
    Video.objects.delete()


def _stranded_video(status, age_minutes):
    global _SEQ
    _SEQ += 1
    vid = f"aaa{_SEQ:08d}"  # 11 chars, unique per video
    video, _ = get_or_create_video(vid, META)
    video.update(
        set__status=status,
        set__updated_at=datetime.utcnow() - timedelta(minutes=age_minutes),
    )
    return video


def test_reaps_stale_processing_video():
    from apps.flashcards.models import Flashcard
    from apps.videos.reaper import reap_stale_videos

    _clean()
    video = _stranded_video("processing", 60)
    n = reap_stale_videos(max_age_minutes=15)
    assert n == 1, n
    video.reload()
    assert video.status == "failed"
    assert video.progress == 0.0
    assert video.error
    assert Flashcard.objects(video_id=video).count() == 0


def test_spares_fresh_and_terminal_videos():
    from apps.videos.reaper import reap_stale_videos

    _clean()
    fresh = _stranded_video("processing", 5)
    _stranded_video("queued", 5)
    _stranded_video("analyzing", 5)
    ready = _stranded_video("ready", 99)
    failed = _stranded_video("failed", 99)
    n = reap_stale_videos(max_age_minutes=15)
    assert n == 0, n
    fresh.reload()
    assert fresh.status == "processing"
    for doc in (ready, failed):
        doc.reload()
        assert doc.status in ("ready", "failed")


def test_reaps_all_three_active_statuses():
    from apps.videos.reaper import reap_stale_videos

    _clean()
    _stranded_video("queued", 99)
    _stranded_video("processing", 99)
    _stranded_video("analyzing", 99)
    n = reap_stale_videos(max_age_minutes=15)
    assert n == 3, n
    assert {d.status for d in Video.objects.all()} == {"failed"}


def test_reaper_respects_default_env_window():
    from apps.videos.reaper import reap_stale_videos

    _clean()
    _stranded_video("processing", 20)
    with patch.dict(os.environ, {"EDUCLIP_REAP_MINUTES": "30"}):
        assert reap_stale_videos() == 0  # 20 min < 30 min window
        assert reap_stale_videos(max_age_minutes=10) == 1


if __name__ == "__main__":
    setup_module()
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    teardown_module()
    print("ALL REAPER CHECKS PASSED")
