"""Celery app (SETUP-01): queues transcribe / llm / default."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

app = Celery("educlip")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.task_queues = {
    "transcribe": {"exchange": "transcribe"},
    "llm": {"exchange": "llm"},
    "default": {"exchange": "default"},
}
app.conf.task_default_queue = "default"

# Worker reliability (pipeline reliability pass): late acks so a worker lost
# mid-task redelivers instead of stranding the video, plus hard time limits.
# The reaper beat entry is the safety net for anything else that strands a
# video in a non-terminal status.
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=1800,
    task_soft_time_limit=1500,
)
app.conf.beat_schedule = {
    "reap-stale-videos": {
        "task": "apps.videos.tasks.reap_stale_videos_task",
        "schedule": 300.0,
        "options": {"queue": "default"},
    },
}
