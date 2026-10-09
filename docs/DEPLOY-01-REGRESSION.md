# DEPLOY-01 — Regression Run Record

> Issue #43 · Branch: `feat/deploy-01-e2e-testing` · Date: 2026-10-09
> Env: Windows, Python 3.13, Node 24, Django 5.2, mongomock (no Atlas/Redis needed)

## Automated runs (all green)

| Suite | Command | Result |
|---|---|---|
| Backend (all apps) | `python -m pytest apps -q` | **57 passed** (50 baseline + 7 new e2e) |
| E2E lifecycle | `python -m pytest apps/api_v1/tests/test_e2e_lifecycle.py -q` | **7 passed** |
| JS (api/modal/charts) | `npm run test:js` | **49 passed** (13 + 5 + 31) |
| Django check | `python manage.py check` | 0 issues |
| Page renders | `GET /` → 200, `GET /watch/<id>/` → 200 | pass |
| Tailwind build | `npm run build:css` | pass (18.5KB) |

CI (`.github/workflows/ci.yml`) repeats backend + JS + CSS build on every
push/PR to `main`. Test-only deps live in `requirements-test.txt`.

## Bugs found by this run — fixed

1. **View envelopes missed `request_id`/`retryable`** (`views.py`,
   `views_retrieval.py`): the BACKEND-06 envelope contract was only applied
   by the exception handler, while hand-built 400/404/422/503 bodies omitted
   the fields the frontend retry logic reads. Added `request_id_of()` and the
   missing keys (additive, full suite still green).
2. **`crypto.randomUUID` crash on non-secure contexts** (`api.js`): added a
   UUID-v4 fallback + unit test.
3. **Throttle-rate overrides don't work in tests** (not an app bug): DRF
   freezes `THROTTLE_RATES` at import, so `override_settings` can't change
   rates. E2E throttle test patches the class attr + clears the cache key
   (same pattern as `test_error_handling.py`).

## Still manual (needs staging creds)

- [ ] 20-video eval set, median process time <90s (`docs/PROJECT_ROADMAP.md` Phase 2)
- [ ] Safari + Chrome pass, 360px device check, keyboard-only + reduced-motion pass
- [ ] Lighthouse ≥90 on `/` and `/watch/<id>/`

## P0 status

Zero open P0s in automated scope: full submit→poll→render contract,
failure envelopes (400/404/422/429/503), JSON 404 routes, and all frontend
state machines are covered by the suites above.
