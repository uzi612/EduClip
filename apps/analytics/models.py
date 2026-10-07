"""MongoEngine documents for analytics (BACKEND-05).

See docs/DATABASE_DESIGN.md §6, §8. One doc per video (1:1).
`graphs` stores Chart.js-native payloads (compute-once, read-many).
"""
from datetime import datetime

import mongoengine as me


class Analytics(me.Document):
    meta = {
        "collection": "analytics",
        "indexes": [{"fields": ["video_id"], "unique": True}],
    }

    video_id = me.LazyReferenceField("Video", required=True, unique=True)
    stats = me.DictField(required=True)
    graphs = me.DictField(required=True)  # Chart.js-native
    computed_at = me.DateTimeField(default=datetime.utcnow)
    schema_version = me.IntField(default=2)
