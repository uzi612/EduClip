"""MongoEngine documents for multiple-choice questions (MCQs).

See docs/DATABASE_DESIGN.md §7 (1:N from videos, like flashcards): one document
per question so individual review stats can evolve without rewriting the video.
"""
from datetime import datetime

import mongoengine as me


class MCQ(me.Document):
    meta = {
        "collection": "mcqs",
        "indexes": [{"fields": ["video_id", "timestamp_sec"]}],
    }

    video_id = me.LazyReferenceField("Video", required=True)
    question = me.StringField(required=True, max_length=200)
    options = me.ListField(me.StringField(max_length=200), required=True)
    answer_index = me.IntField(required=True, min_value=0, max_value=3)
    explanation = me.StringField(required=True, max_length=500)
    timestamp_sec = me.IntField(required=True, min_value=0)
    created_at = me.DateTimeField(default=datetime.utcnow)

    def clean(self):
        if len(self.options or []) != 4:
            raise me.ValidationError("MCQ options must contain exactly 4 entries.")
