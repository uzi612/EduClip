# EduClip AI — System Architecture

> **Stack:** Django 5.x + MongoDB Atlas + Tailwind CSS + Vanilla JS + Chart.js + LLM Analytics
> **Version:** 1.0.0 | **Status:** Prototype → Enterprise | **Last Updated:** 2026-10-05

---

## Table of Contents

1. [Executive Overview](#1-executive-overview)
2. [System Topology](#2-system-topology)
3. [Django Backend Layer](#3-django-backend-layer)
4. [MongoDB Atlas Integration Layer](#4-mongodb-atlas-integration-layer)
5. [YouTube Transcription Pipeline](#5-youtube-transcription-pipeline)
6. [LLM Analytics Processor](#6-llm-analytics-processor)
7. [Frontend Delivery Layer](#7-frontend-delivery-layer)
8. [Asynchronous Processing Model](#8-asynchronous-processing-model)
9. [Security Architecture](#9-security-architecture)
10. [Observability & Ops](#10-observability--ops)
11. [Configuration Reference](#11-configuration-reference)
12. [Scaling Strategy](#12-scaling-strategy)

---

## 1. Executive Overview

**EduClip AI** transforms any YouTube educational video into an interactive learning dashboard: auto-generated chapters, timestamped transcripts, AI summaries, keyword analytics, and flashcards.

Design principles:

- **API-first:** Django exposes `/api/v1/*` REST endpoints; frontend is a decoupled consumer.
- **Async-by-default:** Video processing is long-running (transcription + LLM). All heavy work is offloaded to background workers.
- **Document-native persistence:** MongoDB Atlas stores semi-structured video, chapter, and analytics documents without rigid migrations.
- **Graceful degradation:** Transcription has a 3-tier fallback chain; LLM has rule-based fallback if quota fails.
- **Stateless app tier:** Horizontal scaling via stateless Django + Celery workers.

---

## 2. System Topology

### 2.1 High-Level Diagram

```text
                    ┌─────────────────────┐
                    │   Client Browser    │
                    │ Tailwind + JS +     │
                    │ Chart.js + IFrame   │
                    └─────────┬───────────┘
                              │ HTTPS (443)
                              ▼
                    ┌─────────────────────┐
                    │  Django App Tier    │
                    │  - REST API v1      │
                    │  - Template Views   │
                    │  - Auth / Throttle  │
                    └─────────┬───────────┘
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
   ┌────────────────┐ ┌──────────────┐ ┌──────────────────┐
   │ Celery Workers │ │ MongoDB Atlas│ │ External Services│
   │ - Transcriber  │ │ (M10+ Cluster)│ │ - YouTube Data  │
   │ - LLM Analyzer │ │ videos       │ │   API v3         │
   │ - Chaptorizer  │ │ transcripts  │ │ - youtube-       │
   │ Redis Broker   │ │ analytics    │ │   transcript-api │
   └────────────────┘ │ flashcards   │ │ - OpenAI /       │
                      └──────────────┘ │   Gemini LLM     │
                                       └──────────────────┘
```

### 2.2 Network Zones

| Zone | Components | Ingress | Egress |
|------|------------|---------|--------|
| `public` | Cloudflare CDN → Gunicorn/Nginx | 443 only | None direct |
| `app` | Django, Celery, Redis | Internal VPC | Atlas (27017 TLS), OpenAI (443), YouTube (443) |
| `data` | MongoDB Atlas (AWS `eu-west-1`), Redis ElastiCache | VPC peering / IP allowlist | None |

### 2.3 Repository Topology (Monolith-first)

```text
educlip/
├── config/                  # settings/base.py, prod.py, celery.py, urls.py
├── apps/
│   ├── videos/              # ingestion, transcription orchestration
│   ├── analytics/           # LLM processor, chart data builders
│   ├── flashcards/          # flashcard generation & CRUD
│   └── api_v1/              # DRF viewsets, serializers, throttling
├── services/
│   ├── youtube.py           # transcript + metadata fetcher
│   ├── llm_client.py        # unified LLM wrapper (OpenAI/Gemini)
│   └── chapterizer.py       # timestamp → chapter algorithm
├── templates/ + static/     # Tailwind + JS dashboard
└── docs/                    # this specification set
```

> **Rule:** `apps/` may never import from each other directly. All cross-domain logic goes through `services/`.

---

## 3. Django Backend Layer

### 3.1 Version & Dependencies

```txt
Django==5.0.6
djangorestframework==3.15.1
django-cors-headers==4.3.1
celery==5.3.6
redis==5.0.3
pymongo==4.8.0
mongoengine==0.29.0
youtube-transcript-api==0.6.2
google-api-python-client==2.143.0
openai==1.35.0
gunicorn==22.0.0
```

### 3.2 Settings Architecture

```python
# config/settings/base.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "apps.videos",
    "apps.analytics",
    "apps.flashcards",
    "apps.api_v1",
]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "30/min", "process_video": "10/hour"},
    "EXCEPTION_HANDLER": "apps.api_v1.exceptions.educlip_exception_handler",
}
```

```python
# config/settings/prod.py
from .base import *
import dj_database_url  # only for Django session/admin SQLite; primary data is Mongo

DEBUG = False
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "app.educlip.ai").split(",")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

CELERY_BROKER_URL = os.environ["REDIS_URL"]
MONGODB_URI = os.environ["MONGODB_ATLAS_URI"]
YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # openai | gemini
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
```

### 3.3 Request Lifecycle (POST /api/v1/process-video)

```text
1. Client POST { youtube_url } → DRF View (validate URL, rate-limit, idempotency-key)
2. View → Mongo: lookup videos by youtube_id; if status in (ready, processing) return 200/202 (dedupe)
3. View → Celery: process_video_task.delay(video_id) → return 202 Accepted { task_id, video_id, status }
4. Worker: transcribe → chapterize → LLM analyze → flashcards → mark ready
5. Client polls GET /api/v1/video/<id>/ until status == "ready"
```

```python
# apps/api_v1/views.py
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework import status
from services.youtube import extract_video_id, get_video_metadata
from apps.videos.models import Video

@api_view(["POST"])
def process_video(request):
    url = request.data.get("youtube_url", "")
    youtube_id = extract_video_id(url)
    if not youtube_id:
        return Response({"error": {"code": "INVALID_URL", "message": "Not a valid YouTube URL."}}, status=400)

    existing = Video.objects(youtube_id=youtube_id).first()
    if existing and existing.status in ("ready", "processing"):
        code = 200 if existing.status == "ready" else 202
        return Response({"video_id": str(existing.id), "status": existing.status}, status=code)

    meta = get_video_metadata(youtube_id)  # YouTube Data API v3
    video = Video(youtube_id=youtube_id, status="queued", **meta).save()
    from apps.videos.tasks import process_video_task
    task = process_video_task.delay(str(video.id))
    video.update(task_id=task.id, status="processing")
    return Response({"video_id": str(video.id), "task_id": task.id, "status": "processing"}, status=202)
```

### 3.4 Hosting

- **Dev:** `python manage.py runserver` + local Redis via Docker.
- **Prod:** `gunicorn config.wsgi:application -w 3 -k gthread` behind Nginx. Static via WhiteNoise or S3 + CloudFront.
- **Workers:** `celery -A config worker -Q transcribe,llm,default --concurrency=4 -l info`.

---

## 4. MongoDB Atlas Integration Layer

### 4.1 Connection Management (Singleton + Fork-safe)

```python
# services/mongo.py
from pymongo import MongoClient
from django.conf import settings

_client: MongoClient | None = None

def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(
            settings.MONGODB_URI,
            tls=True,
            retryWrites=True,
            w="majority",
            maxPoolSize=50,
            minPoolSize=5,
            serverSelectionTimeoutMS=5000,
        )
    return _client

def get_db():
    return get_client()[settings.MONGODB_DB_NAME]  # "educlip"
```

MongoEngine registration:

```python
# apps/videos/models.py
import mongoengine as me

me.connect(host=settings.MONGODB_URI, alias="default")
```

### 4.2 Atlas Configuration Rules

1. **Cluster:** M10+ (production), M0 (dev). Region co-located with app (e.g., `eu-west-1`).
2. **Network:** IP Access List = NAT gateway IPs + Vercel/Render egress; no `0.0.0.0/0` in prod.
3. **User:** Least-privilege `educlip-app` role: `readWrite@educlip` only.
4. **Indexes:** See `DATABASE_DESIGN.md` — `youtube_id` unique, `status` + `created_at` compound, Atlas Search index on `transcripts.text`.
5. **Backups:** Continuous cloud backups, PITR enabled, 7-day retention minimum.
6. **Alerts:** Query targeting >1000 scanned, replication lag, disk >70%.

---

## 5. YouTube Transcription Pipeline

### 5.1 Three-Tier Fallback Chain

| Tier | Method | When Used |
|------|--------|-----------|
| T1 | `youtube-transcript-api` (timed captions) | Default — fastest, timestamped |
| T2 | YouTube Data API v3 `captions.download` (OAuth) | T1 has no captions / IP-blocked |
| T3 | Audio download + Whisper (`faster-whisper`) | No captions exist at all; marked `auto_generated: true` |

```python
# services/youtube.py
import re
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

YOUTUBE_RE = re.compile(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})")

def extract_video_id(url: str) -> str | None:
    m = YOUTUBE_RE.search(url or "")
    return m.group(1) if m else None

def fetch_transcript(youtube_id: str) -> list[dict]:
    """Returns [{start: float, duration: float, text: str}]. Raises NoTranscriptError."""
    api = YouTubeTranscriptApi()
    # Prefer English; fall back to any auto-generated track
    tracks = api.list(youtube_id)
    try:
        t = tracks.find_transcript(["en", "en-US", "en-GB"])
    except Exception:
        t = tracks.find_generated_transcript(["en"])
    return t.fetch()  # list of FetchedTranscriptSnippet
```

Worker orchestration with fallback:

```python
# apps/videos/tasks.py
from celery import shared_task
from services.youtube import fetch_transcript
from services.fallback_transcribe import whisper_transcribe
from services.llm_client import analyze_video
from apps.videos.models import Video

@shared_task(bind=True, max_retries=3, queue="transcribe")
def process_video_task(self, video_id: str):
    video = Video.objects(id=video_id).first()
    try:
        try:
            segments = fetch_transcript(video.youtube_id)
            source = "youtube_captions"
        except Exception as e:
            segments = whisper_transcribe(video.youtube_id)  # T3 fallback
            source = "whisper_fallback"
        video.update(transcript_segments=segments, transcript_source=source, status="analyzing")
        analysis = analyze_video(segments, video.title)  # chapters + summary + keywords
        video.update(**analysis, status="ready")
    except Exception as exc:
        video.update(status="failed", error=str(exc)[:500])
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 10)
```

### 5.2 Normalization Rules

- Merge segments <1.2s apart if same sentence; strip `[Music]`, `[Applause]`.
- Store both raw segments and `full_text` (joined, max 200k chars).
- Language detect via first 500 chars; store `language: "en"`.
- Rate-limit: cache transcript in Mongo for 30 days; never re-fetch `ready` videos.

---

## 6. LLM Analytics Processor

### 6.1 Unified Client (Provider-agnostic)

```python
# services/llm_client.py
import json, os
from django.conf import settings

SYSTEM_PROMPT = """You are EduClip, an education analyst. Given a video transcript with
timestamps, return STRICT JSON: {"summary": str, "chapters": [...], "keywords": [...], "flashcards": [...]}.
Chapters: {title, start_sec, end_sec, summary}. Flashcards: {front, back, timestamp_sec} (8-12 cards)."""

def analyze_video(segments: list[dict], title: str) -> dict:
    transcript = "\n".join(f"[{s['start']:.0f}s] {s['text']}" for s in segments[:800])
    if settings.LLM_PROVIDER == "gemini":
        return _call_gemini(transcript, title)
    return _call_openai(transcript, title)

def _call_openai(transcript, title):
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=3000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"TITLE: {title}\nTRANSCRIPT:\n{transcript}"},
        ],
    )
    return json.loads(resp.choices[0].message.content)
```

### 6.2 Deterministic Post-Processing (Never trust LLM blindly)

1. **Chapter validation:** sort by `start_sec`, clamp to video duration, fill gaps, min chapter length 30s.
2. **Keyword scoring:** TF-IDF re-weight of LLM keywords against transcript; drop <0.15 score.
3. **Analytics graphs:** computed locally (not by LLM) — see `DATABASE_DESIGN.md`:
   - `keyword_density`: top-10 keywords × occurrences per 60s bucket.
   - `chapter_duration_pie`: chapter lengths for Chart.js doughnut.
   - `engagement_curve`: heuristic (intro dip, chapter-boundary spikes).
4. **Fallback:** if LLM times out / invalid JSON → extractive summary (first 3 sentences per quartile) + uniform 5-min chapters. Status still `ready`, flagged `degraded: true`.

### 6.3 Cost & Reliability Guards

- Truncate transcript to ~12k tokens; temperature 0.3; JSON mode enforced.
- Cache LLM result keyed by `sha256(full_text)` — identical re-uploads cost $0.
- Timeout 60s; 2 retries with exponential backoff; circuit-breaker after 5 consecutive failures.

---

## 7. Frontend Delivery Layer

Django serves SEO-friendly landing + dashboard shell; all dynamic data via `fetch()` to `/api/v1/*`. Full spec in `FRONTEND_SPECIFICATION.md`.

---

## 8. Asynchronous Processing Model

| State | Meaning | API Visibility |
|-------|---------|----------------|
| `queued` | DB row created, Celery not yet picked up | `202` + `status: queued` |
| `processing` | Transcribing | `202` + progress `0.2` |
| `analyzing` | LLM + chapterize running | `202` + progress `0.7` |
| `ready` | Dashboard can render | `200` full payload |
| `failed` | Terminal; `error` message present | `422` with error schema |
| `degraded` (flag) | Ready but fallback used | `200` + `degraded: true` |

Celery queues: `transcribe` (IO-bound, concurrency 8), `llm` (rate-limited, concurrency 2), `default`.

---

## 9. Security Architecture

- **Input:** Strict YouTube URL allowlist regex; 11-char video ID; max URL length 500. DRF throttling `10/hour` on `process-video` per IP.
- **Secrets:** Only via env / Docker secrets; never committed. `django-environ` + `.env.example`.
- **DB:** TLS to Atlas, SCRAM auth, least-privilege user, field-level redaction of `error` traces in API.
- **Headers:** `CSP: frame-src https://www.youtube.com`, `X-Content-Type-Options: nosniff`, HSTS.
- **Abuse:** Idempotency-Key header dedupes double-submits; honeypot on public form.

---

## 10. Observability & Ops

- **Logs:** JSON structured logs (`structlog`), Celery task_id + video_id in every record. Ship to Axiom/Datadog.
- **Metrics:** `/metrics` (django-prometheus): `educlip_process_duration_seconds`, `llm_tokens_total`, `transcript_fallback_count`.
- **Tracing:** Sentry (Django + Celery integrations), `traces_sample_rate=0.2`.
- **Health:** `/api/v1/health` checks Mongo ping + Redis ping + LLM heartbeat.

---

## 11. Configuration Reference

```bash
# .env (never commit; see .env.example)
DJANGO_SECRET_KEY=change-me
ALLOWED_HOSTS=localhost,app.educlip.ai
MONGODB_ATLAS_URI=mongodb+srv://educlip-app:<pw>@cluster0.xxxx.mongodb.net/educlip?retryWrites=true&w=majority
MONGODB_DB_NAME=educlip
REDIS_URL=redis://localhost:6379/0
YOUTUBE_API_KEY=AIza...
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...
CELERY_RESULT_BACKEND=redis://localhost:6379/1
SENTRY_DSN=https://...@sentry.io/...
```

---

## 12. Scaling Strategy

| Phase | Traffic | Change |
|-------|---------|--------|
| Prototype | <100 videos/day | Single Gunicorn + 1 Celery worker, M0 Atlas |
| Beta | <5k/day | 2 app replicas, separate `llm` queue, M10 Atlas, Redis Cloud |
| Enterprise | 100k+/day | K8s HPA on Celery queue depth, Atlas auto-scale + sharding by `youtube_id`, transcript CDN cache, Whisper GPU pool |

---

*Related: `API_SPECIFICATION.md` · `DATABASE_DESIGN.md` · `FRONTEND_SPECIFICATION.md` · `PROJECT_ROADMAP.md` · `TASK_ASSIGNMENTS.md`*
