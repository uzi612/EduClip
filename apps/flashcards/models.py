"""MongoEngine documents for flashcards (BACKEND-05).

See docs/DATABASE_DESIGN.md §7-8. One document per card (1:N from videos).
"""
from datetime import datetime

import mongoengine as me

DIFFICULTIES = ("easy", "medium", "hard")


class ReviewState(me.EmbeddedDocument):
    ease_factor = me.FloatField(default=2.5, min_value=1.3)
    interval_days = me.IntField(default=1, min_value=0)
    repetitions = me.IntField(default=0, min_value=0)
    next_review_at = me.DateTimeField()


class Flashcard(me.Document):
    meta = {
        "collection": "flashcards",
        "indexes": [{"fields": ["video_id", "timestamp_sec"]}],
    }

    video_id = me.LazyReferenceField("Video", required=True)
    front = me.StringField(required=True, max_length=140)
    back = me.StringField(required=True, max_length=300)
    timestamp_sec = me.IntField(required=True, min_value=0)
    difficulty = me.StringField(choices=DIFFICULTIES, default="medium")
    tags = me.ListField(me.StringField(max_length=30))
    review = me.EmbeddedDocumentField(ReviewState, default=ReviewState)
    created_at = me.DateTimeField(default=datetime.utcnow)
