# EduClip AI — Engineering Task Assignments & Backlog

> **Teams:** 🔧 Backend Data Services · 🗄️ Database Management · 🎨 Frontend Components · 📊 Visualization Graphing
> **Workflow:** GitHub Projects (or Linear) · Branches: `feat/<team>/<slug>` · PRs require 1 review + CI green.
> **Labels:** `P0-critical` `P1-next` `P2-nice` · `backend` `database` `frontend` `viz` · `good-first-issue`

---

## 1. How to Use This Backlog

1. Each task has **Owner team**, **Acceptance criteria**, **Estimate** (T-shirt: S <4h, M 1–2d, L 3–5d).
2. **Definition of Done:** code + tests + docs updated + demo GIF in PR.
3. Pick tasks top-down within your module; unblock cross-team dependencies first (marked 🔗).
4. Standup format: *done / doing / blocked + video_id used for manual test*.

---

## 2. Module A — Backend Data Services (🔧)

> **Owner:** Backend engineers · **Stack:** Django, DRF, Celery, `youtube-transcript-api`, OpenAI/Gemini

### A1. YouTube ingestion service [P0 · M] 🔗 (blocks all)

- [ ] Implement `services/youtube.py`: `extract_video_id()`, `fetch_transcript()`, `get_video_metadata()` (Data API v3: title, channel, duration, thumbnail).
- [ ] Handle Shorts (`/shorts/ID`), `youtu.be`, `?v=` + `&t=` params; reject playlists/channels with `INVALID_URL`.
- [ ] Unit tests: 15 URL variants + no-caption + IP-block simulation (mock).

```python
# Acceptance: pytest apps/videos/tests/test_youtube.py — 20/20 pass
assert extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=42") == "dQw4w9WgXcQ"
```

### A2. Transcription fallback chain [P0 · L]

- [ ] T1 `youtube-transcript-api` → T2 `captions.download` → T3 `faster-whisper` on audio.
- [ ] Normalize: strip `[Music]`, merge <1.2s gaps, cap 200k chars, detect language.
- [ ] Record `transcript_source`; emit metric `transcript_fallback_count{source}`.

### A3. Async pipeline (`process_video_task`) [P0 · L] 🔗

- [ ] Celery task: transcribe → `status=analyzing` → LLM → validate → `status=ready`; exceptions → `failed` + retry (exp backoff ×3).
- [ ] Progress updates: 0.05 queued → 0.2 transcribing → 0.7 analyzing → 1.0 ready.
- [ ] Idempotency-Key handling; duplicate `youtube_id` short-circuits.

```python
# apps/videos/tasks.py — acceptance: Flower shows task <90s median on eval set
@shared_task(bind=True, max_retries=3, queue="transcribe")
def process_video_task(self, video_id: str): ...
```

### A4. REST endpoints [P0 · M]

- [ ] `POST /process-video`, `GET /video/<id>/`, `GET /videos/`, `DELETE /video/<id>/`, `GET /health` per `API_SPECIFICATION.md`.
- [ ] DRF serializers + throttles (`process_video: 10/hour`) + unified error envelope.
- [ ] Integration tests with `mongomock` for 202→poll→200 lifecycle.

### A5. LLM analytics processor [P0 · L] 🔗 (blocks viz)

- [ ] `services/llm_client.py`: JSON-mode prompt, temp 0.3, 60s timeout, 2 retries.
- [ ] Post-process: `normalize_chapters()`, TF-IDF keyword re-score, graceful degraded fallback.
- [ ] Cache by `sha256(full_text)`; token/cost logging per video.

### A6. Hardening [P1 · M]

- [ ] Sentry + `/metrics` (Prometheus) + structured logs; `X-Request-Id` echo.
- [ ] `pip-audit`, CSP headers, HSTS, secrets scan in CI.

---

## 3. Module B — Database Management (🗄️)

> **Owner:** Backend/DB engineers · **Stack:** MongoDB Atlas, MongoEngine, PyMongo

### B1. Cluster provisioning [P0 · S] 🔗

- [ ] Create Atlas projects `educlip-dev` (M0) / `educlip-prod` (M10+); region `eu-west-1`.
- [ ] IP allowlist (no `0.0.0.0/0` in prod), `educlip-app` least-privilege user, TLS enforced.
- [ ] Store URI in secrets manager; publish `.env.example` (no real creds).

```bash
# Acceptance: mongosh connects with app user, fails with bad IP
mongosh "mongodb+srv://educlip-app:<pw>@cluster0.xxxx.mongodb.net/educlip"
```

### B2. ODM models [P0 · M]

- [ ] Implement `Video`, `Chapter`, `Flashcard`, `Analytics` MongoEngine docs per `DATABASE_DESIGN.md` (`schema_version` included).
- [ ] Field validation: 11-char `youtube_id` regex, duration 10–10800s, chapter contiguity.

### B3. Indexes & search [P0 · S]

- [ ] `youtube_id` unique, `(status, -created_at)`, `flashcards(video_id, timestamp_sec)`, `analytics(video_id)` unique.
- [ ] Atlas Search index `transcript_search` (title, full_text, chapters.title).
- [ ] Verify with `db.videos.getIndexes()` + `explain("executionStats")` <50ms on 10k docs.

### B4. Data-access layer [P1 · M]

- [ ] `services/mongo.py` singleton client (pool 5–50), `mark_ready()` atomic transition, bulk flashcard insert, paginated `recent_videos()` (projection excludes `full_text`).
- [ ] Transactional cascade delete (video + analytics + flashcards + overflow).

### B5. Lifecycle & backups [P1 · S]

- [ ] PITR + 7d retention; quarterly restore drill; TTL on `processing_jobs` (90d); nightly purge of `failed` >30d via Celery beat.

---

## 4. Module C — Frontend Components (🎨)

> **Owner:** Frontend engineers · **Stack:** Tailwind, vanilla JS, YouTube IFrame API

### C1. Shell + landing [P0 · M]

- [ ] `base.html`, `navbar`, `footer`, `toast` partials; `tailwind.config.js` dark theme; Inter + JetBrains Mono.
- [ ] Hero + intake form + progress bar + recent grid (`GET /videos/`); form validation + `Idempotency-Key`.
- [ ] Acceptance: Lighthouse perf ≥90, mobile 360px no horizontal scroll.

### C2. Player + chapters [P0 · M] 🔗 (needs API A4)

- [ ] `player.js`: IFrame API init, `playerVars {rel:0, modestbranding:1}`, `syncChapter()` 1s ticker, chapter toast, `data-seek` delegation.
- [ ] Chapter sidebar: active `ring-2` glow, mono timestamps (`m:ss`), duration labels, skeleton while processing.

### C3. Flashcards deck [P0 · M]

- [ ] `flashcards.css` 3D flip (preserve-3d, 0.6s cubic-bezier), `flashcards.js` click + Enter/Space, shuffle, prev/next, counter, `data-seek` jump.
- [ ] Empty/degraded states; `prefers-reduced-motion` disables animation.
- [ ] A11y: `role="button"`, focus ring, screen-reader front/back labels.

### C4. Summary + keywords + states [P1 · S]

- [ ] Summary card (line-clamp + expand), keyword chips with scores, stats row (reading min, WPM).
- [ ] Processing view: animated steps (Fetching → Analyzing → Flashcards); failed view with retry button.

### C5. Polish [P2 · M]

- [ ] Page-transition fade-up stagger, sticky mobile player, footer + OG meta tags, favicon set.

---

## 5. Module D — Visualization Graphing (📊)

> **Owner:** Frontend + backend pair · **Stack:** Chart.js 4.x, backend graph builders

### D1. Graph builders (backend) [P0 · M] 🔗 (needs A5)

- [ ] `apps/analytics/graphs.py`: `build_keyword_density()` (60s buckets), `build_chapter_pie()`, `build_engagement_curve()` returning Chart.js-native JSON.
- [ ] Validate payloads against JSON schema before `ready`; unit tests with fixture transcript.

```python
# Acceptance
graphs = build_all_graphs(segments, chapters, keywords)
assert set(graphs) == {"keyword_density", "chapter_duration", "engagement_curve"}
ChartValidator.validate(graphs)  # raises on bad shape
```

### D2. Chart.js integration [P0 · M]

- [ ] `charts.js`: dark defaults (`color #9ca3af`), per-chart render fns, `destroy()` before re-render, fixed `h-64` containers.
- [ ] Bar (keyword density, rounded bars), doughnut (chapter share, `cutout 65%`), line (attention, `tension 0.4`, `fill`).
- [ ] Loading skeletons + "Analytics pending" empty state; `IntersectionObserver` lazy-init.

### D3. Advanced viz [P2 · L]

- [ ] Click bar → seek video to bucket; hover doughnut → highlight chapter; export PNG button.
- [ ] `GET /video/<id>/analytics` caching (`max-age=60`); client-side memo by `video_id`.

---

## 6. Cross-Module Dependency Board

| # | Dependency | Producer → Consumer | Status |
|---|------------|---------------------|--------|
| 1 | Transcript JSON shape | A1/A2 → B2, D1 | ⬜ |
| 2 | Video/Analytics schemas | B2 → A4, C2, D2 | ⬜ |
| 3 | LLM output contract | A5 → D1, C3 | ⬜ |
| 4 | API response examples | A4 → C1/C2/D2 (can mock from spec) | ⬜ |
| 5 | Atlas connection string | B1 → A3/A4 (local dev unblocked via mongomock) | ⬜ |

> **Standup rule:** If you're blocked on a dependency, switch to mock-driven development using the example payloads in `API_SPECIFICATION.md` — never idle.

---

## 7. Sprint Plan (2-Week Sprints)

**Sprint 1 (Wk 1–2):** A1, B1, C1-skeleton → demo: URL → transcript dump.
**Sprint 2 (Wk 3–4):** A3-sync, B2/B3, A4 → demo: dedupe + paginated list.
**Sprint 3 (Wk 5–6):** A5, D1, B4 → demo: chapters + flashcards JSON.
**Sprint 4 (Wk 7–8):** C2, C3, D2 → demo: full dashboard + charts.
**Sprint 5 (Wk 9–10):** A6, B5, C4 → beta freeze + load test.
**Sprint 6 (Wk 11–12):** Deploy, runbook, enterprise backlog grooming.

---

## 8. Definition of Done (Checklist)

```markdown
- [ ] Code follows repo style (ruff/black for Python, prettier for JS)
- [ ] Unit/integration tests added and passing (`pytest`, manual mobile check)
- [ ] Docs updated (this backlog checked off + spec amended if contract changed)
- [ ] PR has screenshots/GIF + test video_id + Chart.js screenshot (viz PRs)
- [ ] No secrets in diff; CI green (lint + test + pip-audit)
```

---

*Related: `PROJECT_ROADMAP.md` · `API_SPECIFICATION.md` · `DATABASE_DESIGN.md` · `FRONTEND_SPECIFICATION.md`*
