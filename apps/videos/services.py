"""Transactional helpers for videos (BACKEND-05). See docs/DATABASE_DESIGN.md §12."""
from services.mongo import get_client


def delete_video_cascade(video_id):
    """Delete a video and all related docs in one transaction (replica set required)."""
    with get_client().start_session() as s:
        with s.start_transaction():
            db = get_client().get_database()
            db.videos.delete_one({"_id": video_id}, session=s)
            db.analytics.delete_many({"video_id": video_id}, session=s)
            db.flashcards.delete_many({"video_id": video_id}, session=s)
            db.transcripts_overflow.delete_many({"video_id": video_id}, session=s)
