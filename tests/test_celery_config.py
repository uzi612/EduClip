"""Worker reliability config verification (pipeline reliability pass).

Run: python tests/test_celery_config.py (needs repo root on PYTHONPATH)
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from config.celery import app  # noqa: E402


def test_late_acks_and_worker_lost_rejection():
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True


def test_time_limits_present():
    assert app.conf.task_time_limit and app.conf.task_time_limit >= 900
    assert app.conf.task_soft_time_limit
    assert app.conf.task_soft_time_limit < app.conf.task_time_limit


def test_reaper_beat_scheduled_on_default_queue():
    entry = app.conf.beat_schedule["reap-stale-videos"]
    assert entry["task"] == "apps.videos.tasks.reap_stale_videos_task"
    assert entry["options"]["queue"] == "default"
    assert entry["schedule"] <= 600


def test_reaper_task_registered():
    import apps.videos.tasks as tasks_mod

    registered = app.tasks["apps.videos.tasks.reap_stale_videos_task"]
    assert registered.name == "apps.videos.tasks.reap_stale_videos_task"
    assert registered.__module__ == "apps.videos.tasks"
    assert callable(tasks_mod.reap_stale_videos_task)


if __name__ == "__main__":
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    print("ALL CELERY-CONFIG CHECKS PASSED")
