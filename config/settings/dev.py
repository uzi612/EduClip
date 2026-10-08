"""Local-review settings: zero external services (no Atlas/Redis/keys).

- MongoEngine runs on in-memory mongomock (data resets on restart).
- Celery runs tasks eagerly in-process (no broker needed).
- Transcript/LLM fallbacks do the rest: real captions via T1, yt-dlp metadata
  without an API key, extractive analysis without an LLM key.

Usage: python manage.py runserver --settings=config.settings.dev
"""
from .base import *  # noqa: F401,F403

DEBUG = True
CELERY_TASK_ALWAYS_EAGER = True

import mongoengine as me  # noqa: E402
import mongomock  # noqa: E402

me.disconnect_all()
me.connect(db="educlip-dev", mongo_client_class=mongomock.MongoClient)
