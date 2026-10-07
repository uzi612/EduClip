"""MongoEngine documents for videos (BACKEND-05).

See docs/DATABASE_DESIGN.md §3-5, §8.
Collection: `videos`. Chapters are embedded (bounded, <50/video).
"""
from datetime import datetime

import mongoengine as me

STATUS = ("queued", "processing", "analyzing", "ready", "failed")
TRANSCRIPT_SOURCES = ("youtube_captions", "captions_api", "whisper_fallback")
SCHEMA_VERSION = 3


class Chapter(me.EmbeddedDocument):
    index = me.IntField(required=True, min_value=0)
    title = me.StringField(required=True, max_length=80)
    start_sec = me.IntField(required=True, min_value=0)
    end_sec = me.IntField(required=True)
    summary = me.StringField(max_length=500)
    keyword_refs = me.ListField(me.StringField(max_length=40))


class Keyword(me.EmbeddedDocument):
    term = me.StringField(required=True, max_length=40)
    score = me.FloatField(required=True, min_value=0, max_value=1)
    count = me.IntField(required=True, min_value=1)


class TranscriptSegment(me.EmbeddedDocument):
    start = me.FloatField(required=True)
    duration = me.FloatField(required=True)
    text = me.StringField(required=True, max_length=500)


class Video(me.Document):
    meta = {
        "collection": "videos",
        "indexes": [
            {"fields": ["youtube_id"], "unique": True},
            {"fields": ["status", "-created_at"]},
            {"fields": ["-created_at"]},
        ],
    }

    youtube_id = me.StringField(required=True, unique=True, regex=r"^[A-Za-z0-9_-]{11}$")
    title = me.StringField(required=True, max_length=300)
    channel = me.StringField(max_length=200)
    channel_id = me.StringField(max_length=100)
    thumbnail = me.URLField()
    duration_sec = me.IntField(required=True, min_value=10, max_value=10800)
    view_count = me.IntField(min_value=0)
    language = me.StringField(max_length=10, default="en")
    status = me.StringField(choices=STATUS, default="queued")
    progress = me.FloatField(default=0.0, min_value=0, max_value=1)
    degraded = me.BooleanField(default=False)
    transcript_source = me.StringField(choices=TRANSCRIPT_SOURCES)
    transcript_segments = me.ListField(me.EmbeddedDocumentField(TranscriptSegment))
    transcript_version = me.IntField(default=1, min_value=1)
    full_text = me.StringField()
    word_count = me.IntField(min_value=0)
    summary = me.StringField()
    chapters = me.ListField(me.EmbeddedDocumentField(Chapter))
    keywords = me.ListField(me.EmbeddedDocumentField(Keyword))
    task_id = me.StringField()
    error = me.StringField()
    flashcard_count = me.IntField(default=0, min_value=0)
    idempotency_key = me.StringField()
    created_at = me.DateTimeField(default=datetime.utcnow)
    updated_at = me.DateTimeField(default=datetime.utcnow)
    schema_version = me.IntField(default=SCHEMA_VERSION)
