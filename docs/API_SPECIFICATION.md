# EduClip AI — REST API Specification

> **Base URL:** `https://app.educlip.ai/api/v1` (dev: `http://localhost:8000/api/v1`)
> **Protocol:** HTTPS only (prod) · **Format:** JSON (`Content-Type: application/json`)
> **Versioning:** URL path (`/v1/`); breaking changes → `/v2/`, old version supported 6 months.
> **Auth (v1):** Public prototype — IP rate-limit + optional `Idempotency-Key`. Auth (JWT) reserved for v1.1.

---

## Table of Contents

1. [Conventions](#1-conventions)
2. [Endpoints Overview](#2-endpoints-overview)
3. [POST /process-video](#3-post-process-video)
4. [GET /video/<id>/](#4-get-videoid)
5. [GET /video/<id>/chapters](#5-get-videoidchapters)
6. [GET /video/<id>/flashcards](#6-get-videoidflashcards)
7. [GET /video/<id>/analytics](#7-get-videoidanalytics)
8. [GET /videos/ (list)](#8-get-videos-list)
9. [DELETE /video/<id>/](#9-delete-videoid)
10. [GET /health](#10-get-health)
11. [Asynchronous Processing States](#11-asynchronous-processing-states)
12. [Error Handling Schema](#12-error-handling-schema)
13. [Rate Limiting & Headers](#13-rate-limiting--headers)
14. [Frontend Integration Snippets](#14-frontend-integration-snippets)

---

## 1. Conventions

- **IDs:** MongoDB ObjectId as 24-char hex string (`video_id`, e.g. `670f1a2b3c4d5e6f7890abcd`).
- **Timestamps:** ISO-8601 UTC (`2026-10-05T12:00:00Z`). Video positions in **seconds** (integer).
- **Envelope:** Success → resource JSON directly. Errors → `{"error": {"code", "message", "details"}}`.
- **Idempotency:** `POST /process-video` accepts `Idempotency-Key: <uuid>`; same key + same URL within 24h returns original response without re-queueing.

---

## 2. Endpoints Overview

| Method | Path | Purpose | Auth | Rate Limit |
|--------|------|---------|------|------------|
| `POST` | `/process-video` | Submit YouTube URL, start async pipeline | None | 10/hour/IP |
| `GET` | `/video/<id>/` | Full video dashboard payload (poll for status) | None | 60/min/IP |
| `GET` | `/video/<id>/chapters` | Chapter list only (lightweight) | None | 60/min/IP |
| `GET` | `/video/<id>/flashcards` | Flashcards with pagination | None | 60/min/IP |
| `GET` | `/video/<id>/analytics` | Chart.js-ready graph datasets | None | 60/min/IP |
| `GET` | `/videos/` | Recent videos (paginated) | None | 60/min/IP |
| `DELETE` | `/video/<id>/` | Delete video + cascaded docs | None (v1.1: owner) | 20/hour/IP |
| `GET` | `/health` | Liveness + dependency checks | None | Unlimited |

---

## 3. POST /process-video

Starts transcription + LLM pipeline. **Always returns fast** (<300ms); work happens in Celery.

### Request

```http
POST /api/v1/process-video HTTP/1.1
Content-Type: application/json
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000

{
  "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "options": {
    "language": "en",
    "flashcard_count": 10,
    "include_analytics": true
  }
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `youtube_url` | string | ✅ | Valid `youtube.com/watch`, `youtu.be/`, `youtube.com/shorts/` URL; max 500 chars |
| `options.language` | string | ❌ | BCP-47, default `"en"` |
| `options.flashcard_count` | int | ❌ | 5–20, default `10` |
| `options.include_analytics` | bool | ❌ | Default `true` |

### Responses

**202 Accepted — new job queued:**

```json
{
  "video_id": "670f1a2b3c4d5e6f7890abcd",
  "youtube_id": "dQw4w9WgXcQ",
  "task_id": "a3bbc1c8-4d2e-4f6a-9b1c-8f2e3d4c5b6a",
  "status": "processing",
  "progress": 0.05,
  "poll_url": "/api/v1/video/670f1a2b3c4d5e6f7890abcd/",
  "estimated_seconds": 45
}
```

**200 OK — already ready (dedupe):**

```json
{
  "video_id": "670f1a2b3c4d5e6f7890abcd",
  "youtube_id": "dQw4w9WgXcQ",
  "status": "ready",
  "poll_url": "/api/v1/video/670f1a2b3c4d5e6f7890abcd/"
}
```

**400 / 429 — error (see §12):**

```json
{
  "error": {
    "code": "INVALID_URL",
    "message": "Not a valid YouTube URL. Expected youtube.com/watch?v=... or youtu.be/...",
    "details": { "field": "youtube_url" }
  }
}
```

### Django (DRF) Implementation

```python
# apps/api_v1/serializers.py
from rest_framework import serializers
import re

YT_RE = re.compile(r"^(https?://)?(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)[A-Za-z0-9_-]{11}")

class ProcessVideoSerializer(serializers.Serializer):
    youtube_url = serializers.CharField(max_length=500)
    options = serializers.DictField(required=False, default=dict)

    def validate_youtube_url(self, v):
        if not YT_RE.search(v):
            raise serializers.ValidationError("Not a valid YouTube URL.")
        return v.strip()
```

---

## 4. GET /video/<id>/

Returns the full dashboard payload. **Frontend polls this** every 3s while `status` is `queued|processing|analyzing`.

```http
GET /api/v1/video/670f1a2b3c4d5e6f7890abcd/ HTTP/1.1
```

### 200 — Processing (incomplete)

```json
{
  "video_id": "670f1a2b3c4d5e6f7890abcd",
  "youtube_id": "dQw4w9WgXcQ",
  "title": "Intro to Photosynthesis",
  "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
  "duration_sec": 842,
  "status": "analyzing",
  "progress": 0.7,
  "degraded": false,
  "created_at": "2026-10-05T12:00:00Z"
}
```

### 200 — Ready (complete)

```json
{
  "video_id": "670f1a2b3c4d5e6f7890abcd",
  "youtube_id": "dQw4w9WgXcQ",
  "title": "Intro to Photosynthesis",
  "channel": "Bio Master",
  "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
  "duration_sec": 842,
  "status": "ready",
  "progress": 1.0,
  "degraded": false,
  "transcript_source": "youtube_captions",
  "summary": "Photosynthesis converts light energy into chemical energy...",
  "chapters": [
    { "index": 0, "title": "Light Reactions", "start_sec": 0, "end_sec": 240, "summary": "..." },
    { "index": 1, "title": "Calvin Cycle", "start_sec": 241, "end_sec": 600, "summary": "..." }
  ],
  "keywords": [
    { "term": "chlorophyll", "score": 0.92, "count": 14 },
    { "term": "ATP", "score": 0.87, "count": 11 }
  ],
  "flashcard_count": 10,
  "analytics_preview": {
    "top_keywords": ["chlorophyll", "ATP", "stroma"],
    "chapter_count": 4,
    "reading_minutes": 6
  },
  "created_at": "2026-10-05T12:00:00Z",
  "updated_at": "2026-10-05T12:01:30Z"
}
```

### 422 — Failed

```json
{
  "video_id": "670f1a2b3c4d5e6f7890abcd",
  "status": "failed",
  "progress": 0.0,
  "error": {
    "code": "TRANSCRIPT_UNAVAILABLE",
    "message": "No captions found and audio fallback failed.",
    "retryable": false
  }
}
```

---

## 5. GET /video/<id>/chapters

Lightweight chapter list for the timeline sidebar.

```http
GET /api/v1/video/<id>/chapters HTTP/1.1
```

```json
{
  "video_id": "670f1a2b3c4d5e6f7890abcd",
  "duration_sec": 842,
  "chapters": [
    {
      "index": 0,
      "title": "Light Reactions",
      "start_sec": 0,
      "end_sec": 240,
      "summary": "Chlorophyll captures photons...",
      "thumbnail_sec": 12
    }
  ]
}
```

---

## 6. GET /video/<id>/flashcards

```http
GET /api/v1/video/<id>/flashcards?page=1&page_size=10 HTTP/1.1
```

```json
{
  "video_id": "670f1a2b3c4d5e6f7890abcd",
  "page": 1,
  "page_size": 10,
  "total": 10,
  "flashcards": [
    {
      "card_id": "670f1b2c3c4d5e6f7890abce",
      "front": "What pigment captures light in photosystems?",
      "back": "Chlorophyll a (and accessory chlorophyll b/carotenoids).",
      "timestamp_sec": 45,
      "difficulty": "easy",
      "tags": ["pigments"]
    }
  ]
}
```

---

## 7. GET /video/<id>/analytics

Returns **Chart.js-native datasets** — frontend renders without transformation.

```http
GET /api/v1/video/<id>/analytics HTTP/1.1
```

```json
{
  "video_id": "670f1a2b3c4d5e6f7890abcd",
  "graphs": {
    "keyword_density": {
      "type": "bar",
      "data": {
        "labels": ["0:00", "1:00", "2:00", "3:00"],
        "datasets": [
          { "label": "chlorophyll", "data": [3, 5, 1, 0] },
          { "label": "ATP", "data": [0, 2, 4, 5] }
        ]
      }
    },
    "chapter_duration": {
      "type": "doughnut",
      "data": {
        "labels": ["Light Reactions", "Calvin Cycle", "Q&A"],
        "datasets": [{ "data": [240, 360, 242] }]
      }
    },
    "engagement_curve": {
      "type": "line",
      "data": {
        "labels": ["0:00", "2:00", "4:00", "6:00"],
        "datasets": [{ "label": "Attention score", "data": [0.8, 0.65, 0.9, 0.7], "fill": true }]
      }
    }
  },
  "stats": {
    "word_count": 4210,
    "reading_minutes": 6,
    "avg_words_per_min": 702,
    "top_keywords": ["chlorophyll", "ATP", "stroma"]
  }
}
```

Builder (backend) reference:

```python
def build_keyword_density(segments, keywords, bucket_sec=60):
    buckets = {}
    for s in segments:
        b = int(s["start"] // bucket_sec)
        buckets.setdefault(b, {})
        for kw in keywords[:5]:
            if kw in s["text"].lower():
                buckets[b][kw] = buckets[b].get(kw, 0) + 1
    labels = [f"{b*bucket_sec//60}:{b*bucket_sec%60:02d}" for b in sorted(buckets)]
    return {"labels": labels, "datasets": [...]}
```

---

## 8. GET /videos/ (list)

```http
GET /api/v1/videos/?page=1&page_size=12&status=ready&search=photosynthesis HTTP/1.1
```

```json
{
  "page": 1,
  "page_size": 12,
  "total": 42,
  "items": [
    {
      "video_id": "670f1a2b3c4d5e6f7890abcd",
      "youtube_id": "dQw4w9WgXcQ",
      "title": "Intro to Photosynthesis",
      "thumbnail": "https://i.ytimg.com/vi/.../hqdefault.jpg",
      "duration_sec": 842,
      "status": "ready",
      "created_at": "2026-10-05T12:00:00Z"
    }
  ]
}
```

---

## 9. DELETE /video/<id>/

```http
DELETE /api/v1/video/670f1a2b3c4d5e6f7890abcd/ HTTP/1.1
```

- `204 No Content` on success (deletes video + flashcards + analytics).
- `404` if not found.

---

## 10. GET /health

```http
GET /api/v1/health HTTP/1.1
```

```json
{
  "status": "ok",
  "version": "1.0.0",
  "checks": {
    "mongodb": "ok (12ms)",
    "redis": "ok (2ms)",
    "llm": "ok"
  },
  "uptime_sec": 86400
}
```

Returns `503` with `{"status": "degraded", ...}` if any check fails.

---

## 11. Asynchronous Processing States

| `status` | `progress` | Poll Interval | Terminal? |
|----------|------------|---------------|-----------|
| `queued` | 0.05 | 2s | No |
| `processing` | 0.2–0.6 | 3s | No |
| `analyzing` | 0.7–0.9 | 3s | No |
| `ready` | 1.0 | stop | ✅ |
| `failed` | 0.0 | stop | ✅ |

**Polling contract:**

1. `POST /process-video` → `202` with `poll_url`.
2. `GET poll_url` until `status == "ready"` (max 5 min, then show timeout UI with retry).
3. On `failed`, display `error.message`; offer “Retry” (re-POST same URL).

```python
# Celery progress updates
video.update(status="processing", progress=0.2)
video.update(status="analyzing", progress=0.7)
video.update(status="ready", progress=1.0)
```

---

## 12. Error Handling Schema

All errors use HTTP status + unified envelope:

```json
{
  "error": {
    "code": "UPPER_SNAKE_CODE",
    "message": "Human-readable sentence.",
    "details": {},
    "request_id": "req_abc123",
    "retryable": false
  }
}
```

| HTTP | `code` | When |
|------|--------|------|
| 400 | `INVALID_URL` | Malformed YouTube URL |
| 400 | `VALIDATION_ERROR` | Serializer errors; `details.fields` maps field → messages |
| 404 | `VIDEO_NOT_FOUND` | Unknown `video_id` |
| 422 | `TRANSCRIPT_UNAVAILABLE` | No captions + Whisper failed |
| 422 | `VIDEO_TOO_LONG` | Duration > 3h limit |
| 422 | `LLM_FAILED` | LLM invalid JSON after retries (auto-degraded instead where possible) |
| 429 | `RATE_LIMITED` | Throttled; `details.retry_after_sec` |
| 500 | `INTERNAL_ERROR` | Unhandled; `request_id` for Sentry lookup |
| 503 | `SERVICE_UNAVAILABLE` | Mongo/Redis/LLM down |

Custom exception handler:

```python
# apps/api_v1/exceptions.py
from rest_framework.views import exception_handler
from rest_framework.response import Response

def educlip_exception_handler(exc, context):
    resp = exception_handler(exc, context)
    if resp is not None:
        code = "VALIDATION_ERROR" if resp.status_code == 400 else "API_ERROR"
        return Response({"error": {"code": code, "message": str(resp.data), "details": resp.data}}, status=resp.status_code)
    return Response({"error": {"code": "INTERNAL_ERROR", "message": "Unexpected error.", "retryable": True}}, status=500)
```

---

## 13. Rate Limiting & Headers

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 120
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1696500000

{
  "error": { "code": "RATE_LIMITED", "message": "10 requests per hour exceeded.", "details": { "retry_after_sec": 120 } }
}
```

**Configuration:**

```python
# config/settings/base.py
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "anon": "60/min",
    "process_video": "10/hour",
}
```

| Header | Purpose |
|--------|---------|
| `Idempotency-Key` | Dedupe POSTs |
| `X-Request-Id` | Trace (echoed back) |
| `Cache-Control: public, max-age=60` | GET video/chapters cacheable for 60s |

---

## 14. Frontend Integration Snippets

### Submit + Poll (vanilla JS)

```javascript
async function processVideo(youtubeUrl) {
  const res = await fetch("/api/v1/process-video", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify({ youtube_url: youtubeUrl }),
  });
  if (res.status === 429) throw new Error("Rate limited. Try again later.");
  if (!res.ok) {
    const { error } = await res.json();
    throw new Error(error.message);
  }
  const { poll_url } = await res.json();
  return pollUntilReady(poll_url);
}

async function pollUntilReady(pollUrl, timeoutMs = 5 * 60 * 1000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const r = await fetch(pollUrl);
    const video = await r.json();
    updateProgressBar(video.progress, video.status);
    if (video.status === "ready") return video;
    if (video.status === "failed") throw new Error(video.error?.message ?? "Processing failed");
    await new Promise((r) => setTimeout(r, 3000));
  }
  throw new Error("Processing timed out. Please retry.");
}
```

### Render Chart.js Analytics

```javascript
async function renderAnalytics(videoId) {
  const res = await fetch(`/api/v1/video/${videoId}/analytics`);
  const { graphs } = await res.json();
  new Chart(document.getElementById("keywordChart"), {
    type: graphs.keyword_density.type,
    data: graphs.keyword_density.data,
    options: { responsive: true, plugins: { legend: { labels: { color: "#e5e7eb" } } } },
      scales: { x: { ticks: { color: "#9ca3af" } }, y: { ticks: { color: "#9ca3af" } } } },
  });
}
```

---

*Related: `ARCHITECTURE.md` · `DATABASE_DESIGN.md` · `FRONTEND_SPECIFICATION.md`*
