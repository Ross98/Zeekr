# Charging chart readability release — 2026-10-03

User authorized commit and deployment. No push authorized or performed.

- Application commit: `168ca7e` (`fix: align charging chart dates and show energy values`).
- Active release: `/opt/zeekr-control/releases/20261003-charging-readability`.
- Rollback: `/opt/zeekr-control/releases/20261003-dashboard-d8235d5`.
- Code backup: `/opt/zeekr-control/backups/20261003-charging-readability`.
- Verified baseline source matches Git `e2a55ca` (documentation commit on application commit `d8235d5`). Candidate copied from current production; six authorized source/test paths overlaid. Untouched source and vehicle profile retained and hashes verified.
- Dates now have fixed month/day rows, aligned bar baselines, readable day numbers and higher-contrast month/legend text. Horizontal scrolling preserves date legibility on narrow screens.
- Known daily estimated charging energy appears above the filled bar, with kWh stated in the heading. A recorded valid zero stays zero; a recorded unknown estimate remains unknown; dates without records do not gain a zero label. No analytics calculations or stored event values changed.
- Deployment manifest preserves the previous base and feature groups, refreshes changed hashes and adds charging-readability. Seven feature groups match their running files.

## Verification

- Exact staged source: charging date/value browser regression passed (30-day/month boundary, zero/unknown/empty distinction, light/dark, desktop/390/320 widths, contrast and 200% zoom). Refresh regression: 42 desktop/mobile cases passed. Release metadata focused tests: three passed.
- Candidate full suite as service user: 732 tests passed in 72.056 seconds; artwork/readability gate passed.
- Live candidate and active-release domain checks verified 7/30-day charging counts and energy aggregates without exposing private values. Existing routes/reviews and naming preview checks also passed; personal record revisions unchanged during these queries.
- Atomic current switch, only web service restarted. Web, monitor and nginx active; application services NRestarts=0; web process directory equals active release.
- All six overlaid file hashes match. Root 200; unauthenticated state, charging statistics, route/review/ledger and protected scripts 401. Seven matched deployment features.
- No real charging bill/name write, historical event edit, telemetry refresh, notification resend or monitor restart performed. Web login sessions reset.
- Production authenticated browser interaction was not repeated; UI verified using synthetic fixtures and deployed hashes, data semantics verified via live read-only domain queries.
- Unrelated local work remains uncommitted and outside the deployment.
