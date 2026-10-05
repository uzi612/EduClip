# EduClip AI — Project Roadmap (Prototype → Enterprise)

> **Goal:** Ship a demoable prototype in 2 weeks, a hardened beta in 6 weeks, and an enterprise-ready platform in 12 weeks.
> **Method:** Phased milestones with explicit exit criteria. No phase starts until prior exit criteria are green.

---

## Timeline at a Glance

```text
Wk 1-2   Phase 0 ████████░░ Foundation + Data Ingestion (prototype vertical slice)
Wk 3-4   Phase 1 ██████████ Database Wiring (Atlas + models + indexes)
Wk 5-6   Phase 2 ██████████ LLM Analytics + Flashcards pipeline
Wk 7-8   Phase 3 ██████████ Frontend Dashboard Assembly
Wk 9-10  Phase 4 ██████████ Hardening (auth, rate-limit, observability)
Wk 11-12 Phase 5 ██████████ Production Deployment + Enterprise track
```

| Phase | Milestone | Exit Criteria |
|-------|-----------|---------------|
| 0 | Foundation & Ingestion | `POST /process-video` returns transcript for 5 test URLs |
| 1 | Database Wiring | Atlas CRUD + dedupe + cascade delete passing in CI |
| 2 | Analytics Engine | Chapters + flashcards + 3 Chart.js graphs for 20-video eval set |
| 3 | Dashboard Assembly | Lighthouse ≥90, manual QA on mobile + desktop |
| 4 | Hardening | Sentry clean 7d, p95 API <300ms, load test 100 rps |
| 5 | Production Launch | Zero-downtime deploy, backups verified, runbook published |

---

## Phase 0 — Foundation & Data Ingestion (Week 1–2)

**Objective:** End-to-end vertical slice: URL in → transcript out.

- [ ] Scaffold Django 5 project (`config/`, `apps/videos`, `apps/api_v1`), DRF, CORS, `.env.example`.
- [ ] Implement `extract_video_id()` + `youtube-transcript-api` fetcher with logging.
- [ ] Build `POST /api/v1/process-video` (sync prototype, no Celery yet) + `GET /video/<id>/`.
- [ ] Minimal Tailwind landing page with intake form + raw transcript `<pre>` dump.
- [ ] Docker Compose: `web` + `redis` (reserved for Phase 2).

**Deliverables:** Working demo on `localhost:8000` for 5 curated videos (short, long, no-captions, Shorts, non-English).

**Risks → Mitigations:** IP-blocked captions → implement T2/T3 fallback early as spike.

```bash
# Phase 0 demo check
curl -X POST localhost:8000/api/v1/process-video \
  -H 'Content-Type: application/json' \
  -d '{"youtube_url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

---

## Phase 1 — Database Wiring (Week 3–4)

**Objective:** Replace in-memory/file storage with MongoDB Atlas as system of record.

- [ ] Provision Atlas M0 (dev) + M10 (staging): VPC peering, `educlip-app` least-privilege user, TLS.
- [ ] Implement MongoEngine models (`Video`, `Chapter`, `Flashcard`, `Analytics`) per `DATABASE_DESIGN.md`.
- [ ] Create indexes (`youtube_id` unique, `status+created_at`) + JSON-schema validation.
- [ ] Add idempotency: same `youtube_id` → return existing `ready/processing` doc (no re-transcribe).
- [ ] Implement `DELETE /video/<id>/` transactional cascade + `GET /videos/` pagination.
- [ ] Seed script: `python manage.py seed_demo --count 10`.

**Exit test:**

```python
# tests/test_dedupe.py
def test_same_url_returns_same_video(client):
    r1 = client.post("/api/v1/process-video", {"youtube_url": URL})
    r2 = client.post("/api/v1/process-video", {"youtube_url": URL})
    assert r1.json()["video_id"] == r2.json()["video_id"]
```

---

## Phase 2 — LLM Analytics + Flashcards Pipeline (Week 5–6)

**Objective:** Transcript → chapters, summary, keywords, flashcards, Chart.js datasets.

- [ ] Build `services/llm_client.py` (OpenAI `gpt-4o-mini` JSON mode; Gemini adapter behind flag).
- [ ] Implement `chapterizer.normalize_chapters()` + keyword TF-IDF re-scoring.
- [ ] Precompute analytics graphs (`keyword_density`, `chapter_duration`, `engagement_curve`).
- [ ] Wire Celery: `transcribe` queue (concurrency 8) + `llm` queue (concurrency 2, rate-limited).
- [ ] Add `processing/analyzing/ready/failed` states + `progress` + `degraded` fallback path.
- [ ] Eval harness: 20-video golden set; manual rubric (chapter F1 ≥0.7, flashcard usefulness ≥4/5).

**Cost guard:** Cache LLM output by `sha256(full_text)`; truncate to 12k tokens; budget alert at $50/mo.

---

## Phase 3 — Frontend Dashboard Assembly (Week 7–8)

**Objective:** "$100k-grade" dark-mode dashboard per `FRONTEND_SPECIFICATION.md`.

- [ ] Landing: hero, intake form with progress bar, recent-videos grid.
- [ ] Dashboard: IFrame player + `syncChapter()` + chapter sidebar + summary/keywords.
- [ ] Flashcards: 3D flip CSS, keyboard support, shuffle, `data-seek` jump-to-timestamp.
- [ ] Analytics: 3 Chart.js canvases with dark defaults + empty/skeleton states.
- [ ] Polling client (`api.js`): submit → poll 3s → render; toast on error; timeout at 5 min.
- [ ] QA: Lighthouse ≥90 perf/a11y, `prefers-reduced-motion`, 360px mobile pass.

---

## Phase 4 — Hardening & Beta Readiness (Week 9–10)

**Objective:** Secure, observable, and load-tested for public beta.

- [ ] Auth v1.1 spike (JWT, per-user video ownership) — behind feature flag.
- [ ] Throttling (`10/hour` process-video), `Idempotency-Key`, optimisation via `X-Request-Id`.
- [ ] Sentry + Prometheus (`/metrics`) + structured JSON logs with `video_id`/`task_id`.
- [ ] `/api/v1/health` (Mongo + Redis + LLM checks); uptime monitor (BetterStack).
- [ ] Load test: `locust -f tests/load.py --users 100 --spawn-rate 10`; target p95 <300ms for GETs.
- [ ] Security pass: CSP (`frame-src youtube.com`), HSTS, dependency audit (`pip-audit`), secrets scan.

---

## Phase 5 — Production Deployment & Enterprise Track (Week 11–12+)

**Objective:** Zero-downtime launch + enterprise backlog.

### 5.1 Launch checklist

```text
[ ] Atlas M10+ autoscaling + PITR backups verified (restore drill)
[ ] Gunicorn (3 workers) + Nginx + WhiteNoise/S3 static; HTTPS + HSTS
[ ] Celery workers on separate hosts; Redis Cloud; Flower monitoring (internal only)
[ ] CI/CD: GitHub Actions → staging auto-deploy, prod manual approve
[ ] Runbook: transcript failure, LLM quota, Atlas failover, rollback procedure
[ ] Status page + support email; analytics (Plausible) on landing
```

```yaml
# docker-compose.prod.yml (simplified)
services:
  web:
    image: educlip/web:${TAG}
    command: gunicorn config.wsgi:application -w 3
    env_file: .env.prod
  worker-transcribe:
    image: educlip/web:${TAG}
    command: celery -A config worker -Q transcribe --concurrency=8
  worker-llm:
    image: educlip/web:${TAG}
    command: celery -A config worker -Q llm --concurrency=2
  beat:
    image: educlip/web:${TAG}
    command: celery -A config beat  # nightly purges, cache refresh
```

### 5.2 Enterprise backlog (post-launch)

| Quarter | Theme | Items |
|---------|-------|-------|
| Q1 | Collaboration | Workspaces, share links, comments on chapters |
| Q2 | Learning science | Spaced repetition (SM-2), quizzes, export to Anki/Notion |
| Q3 | Scale | K8s HPA, Atlas sharding, Whisper GPU pool, multi-language (12 langs) |
| Q4 | Compliance | SSO/SAML, audit logs, SOC 2 Type I, data-residency (EU cluster) |

---

## Milestone Dependency Graph

```text
Phase 0 (ingestion)
   └─→ Phase 1 (Atlas wiring) ──→ Phase 2 (LLM pipeline)
                                        └─→ Phase 3 (dashboard)
                                                 └─→ Phase 4 (hardening)
                                                          └─→ Phase 5 (launch)
```

**Rule:** Frontend (Phase 3) may mock API responses from `API_SPECIFICATION.md` examples and start in parallel with Phase 2 — but integration testing waits for Phase 2 exit.

---

## Success Metrics

| Metric | Prototype | Beta | Enterprise |
|--------|-----------|------|------------|
| Videos processed/day | 50 | 5,000 | 100,000 |
| Median process time | <90s | <60s | <30s |
| Dashboard p95 load | <3s | <2s | <1s |
| LLM cost / video | <$0.05 | <$0.02 | <$0.01 (cache 70%+) |
| Uptime | n/a | 99.5% | 99.95% |

---

*Related: `ARCHITECTURE.md` · `TASK_ASSIGNMENTS.md`*
