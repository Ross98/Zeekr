# Trip place names release — 2026-10-02

User authorized deployment with “部署吧”.

- Active release: `/opt/zeekr-control/releases/20261002-trip-place-names`.
- Previous release / rollback: `/opt/zeekr-control/releases/20261002-ui-task-hierarchy`.
- Backup: `/opt/zeekr-control/backups/20261002-trip-place-names` (previous code; private business data retained in place).
- Candidate copied from current production. Seventeen scoped paths uploaded, fourteen actual file changes; all other candidate source/test files match the baseline.
- Trusted departure/arrival observations grouped within 150 m around fixed anchors; missing endpoints remain unknown. Monthly counts/routes and explicit map reveal added. Existing home/work settings remain independent.
- Owner/vehicle-scoped manual names, current home/work settings and trustworthy cached address naming supported. Ten user-approved names had already been synchronized separately; private names/coordinates are excluded from this document and release contents.
- Focused local Python: 55 passed. Candidate full service-user unittest discovery command exited 0; candidate discovery contains 724 tests. Artwork gate passed before and after cutover.
- Browser checks against a production-baseline-derived candidate passed: UI_TRIP_PLACE_NAMES, UI_TRIP_PLACES, UI_TRIP_TAGS, UI_REFRESH_SCROLL (40 cases). Covers naming drafts, revision failures, map privacy, monthly/account state, themes, responsive layouts and scroll retention.
- Candidate and live feature verification: ten stored names applied to ten groups; September and October monthly queries verified with 150 m radius.
- Atomic current symlink switch; only web service restarted. Web, monitor and nginx active/running; application NRestarts=0. Running web process directory matches active release.
- All seventeen uploaded file hashes match. Root HTTP 200; unauthenticated state, script and ledger routes HTTP 401.
- Web login sessions reset. No telemetry refresh, historical event edits, notification resend, monitor restart or schema version change performed during deployment.
- Git remains on codex/notification-reference-location, HEAD bc5596d36388bdfe3ff13345b4cb94e6fcbf3a43. Scoped uncommitted files deployed; no commit or push requested or performed. Unrelated worktree changes retained.
- Production authenticated browser interaction was not repeated; live names verified through the service-user domain query and UI behavior through synthetic browser fixtures.

## Manifest

- `zeekr_control/trip_endpoints.py`: `1e07ec57e99620f4cd4496ed6e7076208f025f42d117eaaa8f778f4f14a3a72f`
- `zeekr_control/trip_place_geometry.py`: `02afb8c7759b85e0dc93ae19c7eaf4ca6b6b543ee455b0709df6bdedc97a2524`
- `zeekr_control/trip_places.py`: `2f93a22a567ebfd64abe2bba84fbf2f0e1222a13285336e5b05ea85aab12e112`
- `zeekr_control/trip_place_names.py`: `4158c48094adabd856f870635a53bbbc18a481ece673393e215cfbb86883255b`
- `zeekr_control/commute_tags.py`: `b216885c3f7900a7f4cd03d24384ff38ae8f2d74fd277bd7f2f3c3e1a17c82fd`
- `zeekr_control/personal_store.py`: `72a7ea0b17baf6bde53a83cca5de7ed3f120d328ae77539aba7e888c708e55e0`
- `zeekr_control/trip_tags.py`: `e6baeaf088dd72a52eabf953310039f5d6fd8f5570675b7b11f03c4df166f0fb`
- `zeekr_control/static/trip-tags.js`: `9a2cf84aa734763c455d85682b2723aa7b56292725eabb44c6ed20fa1cab1e68`
- `zeekr_control/static/insights.css`: `2c76d1f0eab3018a8303e7441426907e9df5a953ec020fe98f5c3000bf2686ad`
- `tests/test_trip_places.py`: `69aa0f495dd78fa88091c01906d40877031ec60db2c54ef9c8e8e74e8daa85cb`
- `tests/test_trip_place_names.py`: `39f545ba2ff31a6546a1bf4570cdbed7a6387075f7b71cfda14838371a4b5a26`
- `tests/test_commute_tags.py`: `51d3a40817621237aa3f116c62465c03298f1e0cc88ac86591d945ef4fb58f4f`
- `tests/test_insights_api.py`: `e7f031bb21a1f3f8ad550ddfa072027bab70cecc03e6c75a9df2f31455747283`
- `tests/insights_fixture.py`: `4cdeb1f2f27b4455cef6cb6ec1b071e2dc8505c245b5cc961b738eab5831d27a`
- `tests/ui_trip_places.cjs`: `59963844fb60971d608f01e5ce7b2790d1e71e58dff7b1691d3b9bf6696bff0b`
- `tests/ui_trip_place_names.cjs`: `229859f371ed4de608d377c01260da8459571ecadc70fb46953412d7a69f53b9`
- `tests/ui_trip_tags.cjs`: `1cf1de917a1f1f4853d905d8b8f34841a35293d0d2f9f0ce178082c0cb82cefb`
