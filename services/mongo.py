"""MongoDB Atlas connection layer (SETUP-01).

Fork-safe singleton: client is created lazily on first use (never at import
time), so gunicorn/celery prefork is safe. PyMongo is imported inside the
getter so `manage.py check` works even before `pip install -r requirements.txt`.

See docs/ARCHITECTURE.md §4 and docs/DATABASE_DESIGN.md.
"""
import time

from django.conf import settings

_client = None


def get_client():
    """Return the shared MongoClient (TLS, retryWrites, pool min5/max50)."""
    global _client
    if _client is None:
        from pymongo import MongoClient

        _client = MongoClient(
            settings.MONGODB_ATLAS_URI,
            tls=True,
            retryWrites=True,
            w="majority",
            maxPoolSize=50,
            minPoolSize=5,
            serverSelectionTimeoutMS=5000,
        )
    return _client


def get_db():
    """Return the EduClip database handle."""
    return get_client()[settings.MONGODB_DB_NAME]


def ping_mongo(timeout_ms=3000):
    """Ping Atlas. Returns (ok: bool, latency_ms: int|None). Never raises."""
    start = time.perf_counter()
    try:
        get_client().admin.command("ping")
        return True, int((time.perf_counter() - start) * 1000)
    except Exception:
        return False, None
