# EduClip AI — Database Design (MongoDB Atlas)

> **Engine:** MongoDB Atlas (M10+ prod, M0 dev) · **ODM:** MongoEngine 0.29 + PyMongo 4.8
> **DB Name:** `educlip` · **TLS:** Required · **Write Concern:** `majority`

---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [Collections Overview](#2-collections-overview)
3. [Videos Collection](#3-videos-collection)
4. [Transcripts (Embedded + Overflow)](#4-transcripts-embedded--overflow)
5. [Chapters (Structured Array)](#5-chapters-structured-array)
6. [Analytics Graphs Collection](#6-analytics-graphs-collection)
7. [Flashcards Collection](#7-flashcards-collection)
8. [MongoEngine Models](#8-mongoengine-models)
9. [PyMongo Direct-Access Patterns](#9-pymongo-direct-access-patterns)
10. [Indexes & Atlas Search](#10-indexes--atlas-search)
11. [Validation Rules & Migrations](#11-validation-rules--migrations)
12. [Backup, TTL & Lifecycle](#12-backup-ttl--lifecycle)

---

## 1. Design Principles

1. **Document-per-video:** One `videos` document owns metadata + summary + embedded chapters. Transcripts and analytics scale independently.
2. **Embed when bounded, reference when unbounded:** Chapters (<50/video) are embedded. Flashcards (unbounded, individually reviewed) are referenced.
3. **Immutable transcript segments:** Never update segments after `ready`; version via `transcript_version`.
4. **Compute-once, read-many:** Analytics graphs are precomputed JSON (Chart.js-native) at processing time.
5. **No JOINs at read time:** Dashboard `GET /video/<id>/` is satisfiable with ≤2 queries (video + flashcards count).

---

## 2. Collections Overview

| Collection | Pattern | Avg Size | Reads | Writes |
|------------|---------|----------|-------|--------|
| `videos` | Document-per-video + embedded chapters | 20–80 KB | Very high | Write-once + status transitions |
| `transcripts_overflow` | Bucket per long video (>2000 segments) | 100–500 KB | Medium | Write-once |
| `analytics` | One doc per video (1:1) | 10–30 KB | High | Write-once |
| `flashcards` | One doc per card (1:N) | 1–2 KB | High | Write-once + spaced-repetition updates |
| `processing_jobs` | Audit log per Celery task | 2 KB | Low | Append |

```text
videos (1) ──< embeds chapters[]
videos (1) ──< references transcripts_overflow (optional, 1:1)
videos (1) ──< references analytics (1:1)
videos (1) ──< references flashcards (1:N)
videos (1) ──< references processing_jobs (1:N audit)
```

---

## 3. Videos Collection

### 3.1 Example Document

```json
{
  "_id": { "$oid": "670f1a2b3c4d5e6f7890abcd" },
  "youtube_id": "dQw4w9WgXcQ",
  "title": "Intro to Photosynthesis",
  "channel": "Bio Master",
  "channel_id": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
  "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
  "duration_sec": 842,
  "view_count": 125400,
  "published_at": { "$date": "2024-03-10T00:00:00Z" },
  "language": "en",
  "status": "ready",
  "progress": 1.0,
  "degraded": false,
  "transcript_source": "youtube_captions",
  "transcript_version": 1,
  "full_text": "welcome back today we cover light reactions...",
  "word_count": 4210,
  "summary": "Photosynthesis converts light energy into chemical energy across two stages...",
  "chapters": [
    {
      "index": 0,
      "title": "Light Reactions",
      "start_sec": 0,
      "end_sec": 240,
      "summary": "Chlorophyll captures photons...",
      "keyword_refs": ["chlorophyll", "ATP"]
    },
    {
      "index": 1,
      "title": "Calvin Cycle",
      "start_sec": 241,
      "end_sec": 600,
      "summary": "Carbon fixation in the stroma...",
      "keyword_refs": ["stroma", "RuBisCO"]
    }
  ],
  "keywords": [
    { "term": "chlorophyll", "score": 0.92, "count": 14 },
    { "term": "ATP", "score": 0.87, "count": 11 }
  ],
  "task_id": "a3bbc1c8-4d2e-4f6a-9b1c-8f2e3d4c5b6a",
  "error": null,
  "flashcard_count": 10,
  "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": { "$date": "2026-10-05T12:00:00Z" },
  "updated_at": { "$date": "2026-10-05T12:01:30Z" },
  "schema_version": 3
}
```

### 3.2 Field Rules

| Field | Type | Constraints |
|-------|------|-------------|
| `youtube_id` | string(11) | **Unique**, immutable, regex `^[A-Za-z0-9_-]{11}$` |
| `status` | enum | `queued\|processing\|analyzing\|ready\|failed` |
| `progress` | float | 0.0–1.0 |
| `duration_sec` | int | 10–10800 (reject >3h at API layer) |
| `full_text` | string | Max 200k chars; truncated with `…[truncated]` marker |
| `chapters` | array | Max 50; sorted by `start_sec`; validated server-side |
| `schema_version` | int | Current `3`; bump on breaking field changes |

---

## 4. Transcripts (Embedded + Overflow)

Short videos embed segments directly in `videos.transcript_segments` (cap 2000). Long videos overflow to `transcripts_overflow` bucketed at 500 segments/doc.

**Embedded (default):**

```json
"transcript_segments": [
  { "start": 0.0, "duration": 3.2, "text": "Welcome back to Bio Master." },
  { "start": 3.2, "duration": 4.1, "text": "Today we cover light reactions." }
]
```

**Overflow document:**

```json
{
  "_id": { "$oid": "..." },
  "video_id": { "$oid": "670f1a2b3c4d5e6f7890abcd" },
  "bucket": 0,
  "segments": [ { "start": 0.0, "duration": 3.2, "text": "..." } ],
  "segment_count": 500
}
```

Retrieval rule:

```python
def get_transcript(video):
    if "transcript_segments" in video:
        return video["transcript_segments"]
    buckets = db.transcripts_overflow.find({"video_id": video["_id"]}).sort("bucket")
    return [s for b in buckets for s in b["segments"]]
```

---

## 5. Chapters (Structured Array)

Chapters are **embedded** — always read with the video, never paginated.

```json
{
  "index": 1,
  "title": "Calvin Cycle",
  "start_sec": 241,
  "end_sec": 600,
  "summary": "Carbon fixation in the stroma via RuBisCO.",
  "keyword_refs": ["stroma", "RuBisCO"]
}
```

**Integrity rules (enforced in `chapterizer.py`):**

1. `start_sec < end_sec`; `end_sec - start_sec >= 30` (merge shorter).
2. Contiguous coverage: `chapters[i].end_sec + 1 >= chapters[i+1].start_sec`.
3. Last `end_sec == duration_sec`.
4. Titles ≤80 chars, deduplicated (`Part 2` suffix if LLM repeats).

```python
def normalize_chapters(raw: list[dict], duration: int) -> list[dict]:
    ch = sorted(raw, key=lambda c: c["start_sec"])
    ch[0]["start_sec"] = 0
    ch[-1]["end_sec"] = duration
    # fill gaps / clamp overlaps
    for i in range(len(ch) - 1):
        if ch[i]["end_sec"] < ch[i+1]["start_sec"]:
            ch[i]["end_sec"] = ch[i+1]["start_sec"] - 1
    return [c for c in ch if c["end_sec"] - c["start_sec"] >= 30]
```

---

## 6. Analytics Graphs Collection

One `analytics` doc per video, storing **Chart.js-ready payloads** so the frontend renders with zero transformation.

```json
{
  "_id": { "$oid": "..." },
  "video_id": { "$oid": "670f1a2b3c4d5e6f7890abcd" },
  "stats": {
    "word_count": 4210,
    "reading_minutes": 6,
    "avg_words_per_min": 702,
    "top_keywords": ["chlorophyll", "ATP", "stroma"]
  },
  "graphs": {
    "keyword_density": {
      "type": "bar",
      "data": {
        "labels": ["0:00", "1:00", "2:00"],
        "datasets": [{ "label": "chlorophyll", "data": [3, 5, 1] }]
      }
    },
    "chapter_duration": {
      "type": "doughnut",
      "data": {
        "labels": ["Light Reactions", "Calvin Cycle"],
        "datasets": [{ "data": [240, 360] }]
      }
    },
    "engagement_curve": {
      "type": "line",
      "data": {
        "labels": ["0:00", "2:00", "4:00"],
        "datasets": [{ "label": "Attention score", "data": [0.8, 0.65, 0.9], "fill": true }]
      }
    }
  },
  "computed_at": { "$date": "2026-10-05T12:01:30Z" },
  "schema_version": 2
}
```

> **Rule:** `graphs.*.data` must be valid Chart.js `data` objects. Backend validates with a JSON-schema check before marking `ready`.

---

## 7. Flashcards Collection

One document per card — enables per-card spaced repetition without rewriting the video doc.

```json
{
  "_id": { "$oid": "670f1b2c3c4d5e6f7890abce" },
  "video_id": { "$oid": "670f1a2b3c4d5e6f7890abcd" },
  "front": "What pigment captures light in photosystems?",
  "back": "Chlorophyll a (plus accessory chlorophyll b and carotenoids).",
  "timestamp_sec": 45,
  "difficulty": "easy",
  "tags": ["pigments"],
  "review": {
    "ease_factor": 2.5,
    "interval_days": 1,
    "repetitions": 0,
    "next_review_at": { "$date": "2026-10-06T12:00:00Z" }
  },
  "created_at": { "$date": "2026-10-05T12:01:30Z" }
}
```

**Generation contract:** 8–12 cards per video, `front` ≤140 chars (question), `back` ≤300 chars (answer), at least one card per chapter, `timestamp_sec` links card → video seek.

---

## 8. MongoEngine Models

```python
# apps/videos/models.py
import mongoengine as me
from datetime import datetime

STATUS = ("queued", "processing", "analyzing", "ready", "failed")

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
    thumbnail = me.URLField()
    duration_sec = me.IntField(required=True, min_value=10, max_value=10800)
    status = me.StringField(choices=STATUS, default="queued")
    progress = me.FloatField(default=0.0, min_value=0, max_value=1)
    degraded = me.BooleanField(default=False)
    transcript_source = me.StringField(choices=("youtube_captions", "captions_api", "whisper_fallback"))
    transcript_segments = me.ListField(me.EmbeddedDocumentField(TranscriptSegment))
    full_text = me.StringField()
    summary = me.StringField()
    chapters = me.ListField(me.EmbeddedDocumentField(Chapter))
    keywords = me.ListField(me.EmbeddedDocumentField(Keyword))
    task_id = me.StringField()
    error = me.StringField()
    flashcard_count = me.IntField(default=0)
    idempotency_key = me.StringField()
    created_at = me.DateTimeField(default=datetime.utcnow)
    updated_at = me.DateTimeField(default=datetime.utcnow)
    schema_version = me.IntField(default=3)
```

```python
# apps/flashcards/models.py
class Flashcard(me.Document):
    meta = {
        "collection": "flashcards",
        "indexes": [{"fields": ["video_id", "timestamp_sec"]}],
    }
    video_id = me.LazyReferenceField("Video", required=True)
    front = me.StringField(required=True, max_length=140)
    back = me.StringField(required=True, max_length=300)
    timestamp_sec = me.IntField(required=True, min_value=0)
    difficulty = me.StringField(choices=("easy", "medium", "hard"), default="medium")
    tags = me.ListField(me.StringField(max_length=30))
```

```python
# apps/analytics/models.py
class Analytics(me.Document):
    meta = {"collection": "analytics", "indexes": [{"fields": ["video_id"], "unique": True}]}
    video_id = me.LazyReferenceField("Video", required=True, unique=True)
    stats = me.DictField(required=True)
    graphs = me.DictField(required=True)  # Chart.js-native
    computed_at = me.DateTimeField(default=datetime.utcnow)
```

---

## 9. PyMongo Direct-Access Patterns

Use PyMongo for hot paths (aggregation, bulk writes); MongoEngine for CRUD.

```python
# services/mongo.py — hot-path helpers
def mark_ready(db, video_id, payload: dict):
    """Atomic status transition; returns True if transitioned."""
    r = db.videos.update_one(
        {"_id": video_id, "status": {"$in": ["processing", "analyzing"]}},
        {"$set": {**payload, "status": "ready", "progress": 1.0}},
    )
    return r.modified_count == 1

def insert_flashcards_bulk(db, cards: list[dict]):
    if cards:
        db.flashcards.insert_many(cards, ordered=False)

def recent_videos(db, page=1, page_size=12, status="ready"):
    q = {} if not status else {"status": status}
    cur = db.videos.find(q, {"full_text": 0, "transcript_segments": 0}).sort("created_at", -1)
    return list(cur.skip((page - 1) * page_size).limit(page_size))
```

---

## 10. Indexes & Atlas Search

```javascript
// Run via mongosh or Atlas UI
db.videos.createIndex({ youtube_id: 1 }, { unique: true });
db.videos.createIndex({ status: 1, created_at: -1 });
db.videos.createIndex({ created_at: -1 });
db.flashcards.createIndex({ video_id: 1, timestamp_sec: 1 });
db.analytics.createIndex({ video_id: 1 }, { unique: true });
db.processing_jobs.createIndex({ video_id: 1, started_at: -1 }, { expireAfterSeconds: 7776000 }); // 90d TTL
```

**Atlas Search index (`transcript_search`)** for future semantic search:

```json
{
  "name": "transcript_search",
  "collectionName": "videos",
  "mappings": { "dynamic": false, "fields": {
    "title": { "type": "string" },
    "full_text": { "type": "string" },
    "chapters.title": { "type": "string" }
  }}
}
```

---

## 11. Validation Rules & Migrations

**Schema validation (MongoDB JSON Schema, `schema_version: 3`):**

```json
{
  "$jsonSchema": {
    "bsonType": "object",
    "required": ["youtube_id", "title", "duration_sec", "status", "schema_version"],
    "properties": {
      "youtube_id": { "bsonType": "string", "pattern": "^[A-Za-z0-9_-]{11}$" },
      "status": { "enum": ["queued", "processing", "analyzing", "ready", "failed"] },
      "duration_sec": { "bsonType": "int", "minimum": 10, "maximum": 10800 }
    }
  }
}
```

**Migration policy:**

- Additive changes only (new optional fields). Never rename in place — dual-write then backfill.
- Backfill script pattern: `scripts/migrate_v2_to_v3.py` paginates with `hint`, updates in batches of 500, logs to `processing_jobs`.

---

## 12. Backup, TTL & Lifecycle

| Policy | Setting |
|--------|---------|
| Cluster backups | Continuous + PITR, 7-day retention (30d prod) |
| `processing_jobs` | TTL 90 days (`expireAfterSeconds`) |
| Failed videos | Retained 30 days, then auto-purge via nightly Celery beat |
| Connection string | `mongodb+srv://.../educlip?retryWrites=true&w=majority&tls=true` — never commit credentials |
| Deletion cascade | `DELETE /video/<id>/` removes `videos` + `analytics` + `flashcards` + overflow buckets in a transaction (replica-set required) |

```python
# apps/videos/services.py — transactional cascade delete
from services.mongo import get_client

def delete_video_cascade(video_id):
    with get_client().start_session() as s:
        with s.start_transaction():
            db = get_client().educlip
            db.videos.delete_one({"_id": video_id}, session=s)
            db.analytics.delete_many({"video_id": video_id}, session=s)
            db.flashcards.delete_many({"video_id": video_id}, session=s)
            db.transcripts_overflow.delete_many({"video_id": video_id}, session=s)
```

---

*Related: `ARCHITECTURE.md` · `API_SPECIFICATION.md` · `FRONTEND_SPECIFICATION.md`*
