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
