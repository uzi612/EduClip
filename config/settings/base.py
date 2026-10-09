"""Base settings (SETUP-01). Env-driven via python-dotenv. See docs/ARCHITECTURE.md §3."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = [h for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "apps.videos",
    "apps.analytics",
    "apps.flashcards",
    "apps.api_v1",
]

MIDDLEWARE = [
    "apps.api_v1.middleware.RequestIdMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "apps.api_v1.middleware.RequestLoggingMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# No relational models in v1 (MongoDB Atlas is the system of record).
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    }
]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "process_video": "10/hour"},
    "EXCEPTION_HANDLER": "apps.api_v1.exceptions.educlip_exception_handler",
}

CORS_ALLOW_ALL_ORIGINS = DEBUG

# --- EduClip services ---
MONGODB_ATLAS_URI = os.getenv("MONGODB_ATLAS_URI", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "educlip")
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
EDUCLIP_VERSION = "1.0.0"
