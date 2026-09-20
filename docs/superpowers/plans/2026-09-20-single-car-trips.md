# Single-Car Trips Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the bounded backend task; execute UI integration locally. The user approved the single-car design in this conversation.

**Goal:** Connect each local trip to its own sampled route, with readable status, gaps and playback.

**Architecture:** Existing SQLite events and observations remain the source. Add a read-only current-vehicle trip projection and time-window track queries. Isolate local trip UI in `static/trips.js`, retaining the shared Leaflet map and independent cloud history module.

**Tech Stack:** Python standard library/SQLite, vanilla JavaScript, Leaflet, unittest, Playwright.

- [x] Inspect repository, approve design, isolate workspace; read skills and existing tests.
- [ ] Backend tests first: add synthetic trip/time-range tests and HTTP privacy/current-vehicle tests; run new tests and observe missing functionality.
- [ ] Backend: add trip listing/active summary, safe range resolution, cross-midnight routes, gap/quality metadata; preserve day API compatibility. Files: `zeekr_control/trips.py`, `tracks.py`, `web.py`, backend tests. Verify with `python3 -m unittest discover -s tests -p 'test*trips*.py' -v` plus tracks/web tests.
- [ ] UI tests first: `tests/ui_trips.cjs` covers one-trip selection, consent, quality, refresh preservation, late responses, playback and mobile layouts. Run against old UI and observe failure.
- [ ] UI: add `static/trips.js` and `trips.css`, include in `index.html`; replace local track view/actions in `app.js`. API contract and data fields are fixed by the design spec. Keep `#playback`, `#playback-label`, date/position actions compatible with smoke tests.
- [ ] Review specification coverage, then code quality; simplify shared rendering/request-state logic. Resolve findings before final verification.
- [ ] Run full Python suite, relevant browser suites (trip/history/smoke/theme/energy), JavaScript syntax and `git diff --check`; inspect synthetic desktop/mobile screenshots. Record exact results and update usage docs.
- [ ] Commit only feature files in the isolated branch. Keep real vehicle records, credentials and unrelated files out of this change. Deliver verified local result with deployment status explicit.
