# Dawarich daily recall implementation

Local implementation, 2026-10-03. No deployment, push, gateway request, source-event rewrite, notification replay, or production-data inspection. Existing unrelated worktree changes remain in place. The only adjustment to the already-modified `ui_trips.cjs` is its expected empty-state copy.

## Delivered behavior

1. Daily timeline combines saved trips, observed parking intervals and charging, ordered chronologically. Summary uses event end dates for distance and observed driving duration, bill dates for payments. Overlapping and cross-midnight records remain explicit. The desktop map sits first in the right column and survives record changes; mobile has a direct map jump.
2. Place interpretation is stored separately in the existing revisioned personal database under `place_corrections`. Confirm, assign a one-record name, associate an existing reusable named place, reject a candidate, remember that candidate rejection near its stable anchor, and undo are supported. Manual names win. Rejection preserves the underlying event or parking observations. Candidate changes do not blindly inherit an old rejection. The existing fixed-centre 150 m grouping and 25–150 m manual-name radius remain.
3. Place history supports a maximum 31-day range and 30-record pages with revision-bound cursors. Year review reuses month statistics, distinguishes coverage from activity, handles leap years, and links days and named parking observations back to the timeline. Observed parking fragments and trip arrivals are counted separately; cross-month arrivals are counted once. Dates, selected records, year, heatmap mode and queried state restore through URLs.
4. The benchmark uses synthetic local data and intercepted tile requests. No vector-tile subsystem was needed: measured operations satisfy the 2 s goal and map tasks stay below 200 ms. Full observations, gap boundaries and endpoint evidence are retained; no road snapping was added.

## Interfaces and compatibility

- `GET /api/timeline?date=YYYY-MM-DD`: scalar timeline, daily summary, coverage, known named places, source and correction revisions. Coordinates appear only with `positions=1`; the client sends this only after the existing location-display consent. Actual position sample timestamps are retained.
- `GET /api/place-corrections?date=YYYY-MM-DD`: the same interpretation view without coordinates. `POST /api/place-corrections`: revision-checked `preview`, `save`, or `undo`; save requires the preview token, current context and existing request-key protection. Optional `target_key` selects an existing scoped named place. `remember` applies only to candidate rejection.
- `GET /api/place-history?start=...&end=...&key=...&cursor=...`: scoped history, count, up to 30 records and next cursor. Expired cursors fail rather than mix revisions.
- `GET /api/year-review?year=YYYY`: daily and monthly scalars, annual totals, named parking fragments and trip-arrival counts. No yearly track payload.
- Storage change is additive: a new collection in the existing records schema, with existing undo and guards. Original events, coordinates, notification records and frozen bill event snapshots are untouched; old releases can ignore the new collection.
- Parking reads include one adjacent day on either side to retain ordinary overnight observation identities. The primary history range stays 31 days and archive input stays within its existing 33-day bound. Very long stationary periods or telemetry gaps remain partial observed fragments, never inferred continuous parking.
- Personal writes invalidate dependent frontend results. Open annual results reread saved data; stale history responses are discarded. No background vehicle refresh is introduced.

## Validation

- Full Python suite: 793 tests passed, 51.158 seconds, after the final service changes.
- `ui_daily_recall.cjs`: real local APIs over synthetic saved records; location opt-in and clearing, map DOM reuse, keyboard activation, correction previews, undo, existing-place reassignment backend contract, edit draft and focus preservation, place history, actual bill saving and return, yearly coverage, URL refresh/back, disclosure retention, 1440/390/320 px layouts and light/dark contrast.
- `ui_trips.cjs`: existing sampling quality, midnight, playback, polling, delayed response and layout regression checks passed.
- `ui_calendar_review.cjs` and `ui_calendar_energy.cjs`: existing day/month metrics, bill dates and zero values, partial energy, payment separation, URL state, and responsive themes passed.
- Authentication tests cover the new reads, script and writes; API tests cover request-key and context rejection. Unit contracts additionally cover unknown starts, valid zero metrics, scoped decisions, stale preview/cursor rejection, deleted/restored events, unchanged source facts, parked/charging sequencing, overnight identities, candidate rejection with later manual naming, reusable-name changes, and cross-month annual deduplication.
- JavaScript syntax checks, navigation-state tests and `git diff --check` passed. Impeccable mechanical detector returned an empty finding list for the main changed UI targets. Desktop and mobile previews were visually inspected.

Known pre-existing browser-test issue: `ui_usage_calendar.cjs:13` expects “有停车观测” from `innerText()` while that content is inside a closed disclosure. The same assertion fails with the same output in an isolated original-HEAD export using the user's existing test file. The old script was left unchanged; current calendar review, energy and the new recall suites pass. This is not a claim that every legacy browser script passes.

## Performance evidence

Final run after implementation and verification: Apple M4, macOS arm64, Chrome 151.0.7922.138, 1440 × 1080. Local HTTP responses; map tiles intercepted with synthetic images. API durations include HTTP transfer and JSON parsing, three reads per interface; table shows the slowest read. Map/selection measurements include a 100 ms settling wait. These are desktop synthetic measurements, not production network or physical phone benchmarks.

| Operation | Measured time | Payload / task |
| --- | ---: | --- |
| Daily timeline (126 records) | 128.2 ms | 160,810 bytes |
| 31-day place history (64 matches, page of 30) | 104.7 ms | 38,640 bytes |
| Year review (366 days / 366 trips) | 232.3 ms | 232,742 bytes |
| Map (4,181 observations) | 279.7 ms | longest main-thread task 75 ms |
| Select a charging record | 341.9 ms | no recorded long task |

All measured operations are under 2 seconds; map main-thread work is below 200 ms. Year reads load no coordinates or yearly route. Display simplification and vector tiles were unnecessary at this tested size. The repeatable benchmark records exact fixture sizes and timestamps in its JSON.

## Synthetic artifacts

All screenshots contain synthetic vehicle data and locally intercepted illustrative map tiles, not production locations or basemap availability evidence.

- [Desktop viewport](dawarich-recall-preview-2026-10-03/timeline-desktop-viewport.png)
- [Desktop full timeline](dawarich-recall-preview-2026-10-03/timeline-desktop.png)
- [Mobile timeline](dawarich-recall-preview-2026-10-03/timeline-mobile.png)
- [Annual review, light desktop](dawarich-recall-preview-2026-10-03/recall-light-1440.png)
- [Annual review, dark mobile](dawarich-recall-preview-2026-10-03/recall-dark-390.png)
- [Measured benchmark JSON](dawarich-recall-preview-2026-10-03/performance.json)

Repeat locally, using the existing bundled Playwright runtime and installed Chrome:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python3 -m unittest discover -s tests
NODE_PATH=/Users/xinyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules CHROMIUM_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' node tests/ui_daily_recall.cjs
NODE_PATH=/Users/xinyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules CHROMIUM_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' node tests/benchmark_daily_recall.cjs
PYTHONDONTWRITEBYTECODE=1 python3 tests/recall_fixture.py --port 50779
```

The final command starts a loopback-only synthetic preview with no gateway access. Use a free port; stop the process when finished. Deployment and push require explicit authorization and a fresh check of the active release baseline.
