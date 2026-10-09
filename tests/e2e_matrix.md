# EduClip AI — E2E Manual Checklist (DEPLOY-01 companion)

Automated matrix: `python tests/test_e2e_pipeline.py` (report: `tests/e2e_report.json`).
Live probe: `EDUCLIP_E2E_LIVE=1 EDUCLIP_E2E_URL=https://youtu.be/<id> python tests/test_e2e_pipeline.py`
Reference video: https://youtu.be/IecCQPX-QsI (Hindi captions, 399s).

## Browser runs (record: date, browser, result)

- [ ] Chrome desktop: paste URL → progress → chapters/flashcards/charts render, no console errors
- [ ] Safari desktop: same flow (YouTube IFrame quirks live here)
- [ ] Chapter click seeks + highlights (`aria-current`); toast appears
- [ ] Flashcard click flips; `data-seek` jump button seeks; keyboard Enter/Space flips, arrows move deck
- [ ] Chart bar/doughnut clicks seek the player
- [ ] Failed video shows error panel with working Retry; timeout modal after 5 min

## Responsive + a11y

- [ ] 360px mobile: sticky player, horizontal chapter chips, stacked charts, no horizontal scroll
- [ ] Keyboard-only full flow (Tab order sane, visible focus rings)
- [ ] `prefers-reduced-motion`: flip/shimmer disabled
- [ ] Lighthouse perf/a11y ≥ 90 on `/` and `/watch/<id>/`

## Sign-off

Zero open P0s. P1s filed as sub-issues with owner + ETA. Paste this table + the
automated matrix summary into the DEPLOY-01 verification comment before release.
