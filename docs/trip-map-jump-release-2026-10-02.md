# Trip map navigation release — 2026-10-02

User explicitly authorized deployment with “部署”.

- Active release: `/opt/zeekr-control/releases/20261002-trip-map-jump`.
- Previous release / rollback: `/opt/zeekr-control/releases/20261002-trip-place-names`.
- Scope: trip-tags.js, insights.css and ui_trip_places.cjs. Candidate copied from current production; exactly three changed files, all other source and test contents preserved.
- Place markers use bundled divIcon numbers instead of missing default images. Labels appear on hover or selection. Table, route and event endpoint names open and center the map; popups expose an explicit new-tab map website link. Show-all restores overview; owner/month resets keep map consent isolated. No backend grouping or name writes included.
- Browser marker/jump/privacy/layout/context regression passed against the production-baseline-derived candidate. Same 10 stored names matched, 150 m grouping and September/October domain queries verified before switching.
- Git remains codex/notification-reference-location at bc5596d36388bdfe3ff13345b4cb94e6fcbf3a43; scoped uncommitted UI changes. No commit or push authorized or performed. Unrelated worktree changes retained.

## Manifest

- `zeekr_control/static/trip-tags.js`: `beefc0054afa31fc8c966a6bde19436ea192702c367c2293e6e545d6f2029035`
- `zeekr_control/static/insights.css`: `ff6ccc5b3316833646ace7f99e479f95dff44869f926baf95153dba8aa8f8725`
- `tests/ui_trip_places.cjs`: `de6f501174aafeb4f6e3f4df408e6dedc07236560db55b05361efbd1f2cf8e4b`

## Verified deployment

- Full candidate suite as zeekr-control: 724 tests passed in 72.731 seconds. Service-user artwork gate passed.
- Browser UI_TRIP_PLACES and UI_REFRESH_SCROLL (40 cases) passed against the scoped candidate; the implementation had also passed UI_TRIP_PLACE_NAMES and UI_TRIP_TAGS.
- Backup: `/opt/zeekr-control/backups/20261002-trip-map-jump`. Current atomically switched; web service restarted, monitor retained. Web/monitor/nginx active, application NRestarts=0.
- All three deployed hashes match; running web process directory is the active release. Root 200, protected state/static/ledger/trip-tags routes 401.
- Live service-user queries again matched ten stored names, radius 150 m and two months. No private name changes, event edits, geocoding requests, telemetry refresh, notification resend or database migration performed.
- Web login sessions reset. Production authenticated browser interaction was not repeated; frontend behavior verified using synthetic browser fixtures and deployed file hashes.
