"""Production settings (SETUP-01). Import base, then harden. Secrets only via env."""
import os

from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = [h for h in os.getenv("ALLOWED_HOSTS", "app.educlip.ai").split(",") if h]
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CORS_ALLOW_ALL_ORIGINS = False

STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

for var in ("DJANGO_SECRET_KEY", "MONGODB_ATLAS_URI", "REDIS_URL"):
    if not os.getenv(var):
        raise RuntimeError(f"Missing required env var in prod: {var}")
