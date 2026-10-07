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


# --- BACKEND-05: data-access helpers (PyMongo hot paths) ---
# See docs/DATABASE_DESIGN.md §9-10, §12.


def get_transcript(video_doc, db=None):
    """Return ordered transcript segments for a video.

    Short videos embed `transcript_segments`; long ones (>2000 segments)
    spill into `transcripts_overflow` buckets (500 each).
    """
    if video_doc.get("transcript_segments"):
        return video_doc["transcript_segments"]
    database = db if db is not None else get_db()
    buckets = database.transcripts_overflow.find({"video_id": video_doc["_id"]}).sort("bucket", 1)
    return [seg for bucket in buckets for seg in bucket["segments"]]


def mark_ready(db, video_id, payload: dict):
    """Atomically transition processing/analyzing -> ready. Returns True if transitioned."""
    result = db.videos.update_one(
        {"_id": video_id, "status": {"$in": ["processing", "analyzing"]}},
        {"$set": {**payload, "status": "ready", "progress": 1.0}},
    )
    return result.modified_count == 1


def insert_flashcards_bulk(db, cards: list):
    """Insert flashcard docs (one per card). No-op for empty lists."""
    if cards:
        db.flashcards.insert_many(cards, ordered=False)


def recent_videos(db, page=1, page_size=12, status="ready"):
    """Paginated videos, newest first. Excludes heavy transcript fields."""
    query = {} if not status else {"status": status}
    cursor = (
        db.videos.find(query, {"full_text": 0, "transcript_segments": 0})
        .sort("created_at", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return list(cursor)


def ensure_indexes(db):
    """Create all indexes from docs/DATABASE_DESIGN.md §10 (idempotent)."""
    db.videos.create_index("youtube_id", unique=True)
    db.videos.create_index([("status", 1), ("created_at", -1)])
    db.videos.create_index([("created_at", -1)])
    db.flashcards.create_index([("video_id", 1), ("timestamp_sec", 1)])
    db.analytics.create_index("video_id", unique=True)
    db.processing_jobs.create_index(
        [("video_id", 1), ("started_at", -1)], expireAfterSeconds=7776000
    )
