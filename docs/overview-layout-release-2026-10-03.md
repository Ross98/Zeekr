# Overview layout release — 2026-10-03

Approved synthetic layout promoted into the existing dashboard. Vehicle hero, lock/charging/closure state, cached timestamps, image, odometer, temperature, tyres, activity, location privacy, explanations, and existing tools remain available. Temperature appears immediately below vehicle status. Today observed distance, current-month actual charge amounts, scoped recent records and action links, and trailing 7/30-day distance were added. Missing distance is a gap; valid partial distance and explicit zero amounts are retained. Actual amounts exclude independent estimates. Pending work includes unlinked ended charges and current-month bills without actual amounts.

- Application commit: `f7aba65cc63d`.
- Active release: `/opt/zeekr-control/releases/20261003-overview-layout`.
- Production source baseline verified against `9e6cfde`: `/opt/zeekr-control/releases/20261003-notifications`.
- Rollback: `/opt/zeekr-control/releases/20261003-notifications`.
- Code backup: `/opt/zeekr-control/backups/20261003-overview-layout`.
- Current worktree also contained committed calendar review `9a7eb92`, absent from production. Its six shared source files were reconciled as a complete dependency set; calendar review browser coverage passed. Deployment metadata explicitly includes calendar review and overview layout.
- Candidate copied with `cp -a current/.`; 16 named application/test/plan files overlaid. Private vehicle profile and unrelated production files preserved. Named source files retain baseline ownership and readable mode. Entire tracked application source matches the exact staged/committed tree; all 11 release feature groups match.
- Only Web restarted. Existing monitor PID unchanged; no vehicle refresh, notification resend, or historical/personal record edits performed. Web login sessions reset. No push requested or performed.

## Verification

- Exact staged tree: 765 Python tests passed in 49.046 seconds. Production-baseline candidate: 764 tests passed as service user in 75.031 seconds; production test baseline retained with scoped changed tests.
- Overview unit coverage: trailing periods crossing months, valid fragments, missing vs zero distance, actual-only zero expense, unlinked and unknown-amount pending work.
- Overview browser coverage: real existing trip/charge detail paths; return preserves record filter and scroll; 7/30-day switch; account/vehicle context mismatch rejection; 1440/1279/390/320 widths in light/dark; no script errors or external requests. Synthetic fixture only.
- Existing overview, attention, pending ledger, charge ledger editing, calendar review, URL navigation, and 42 desktop/mobile refresh checks passed.
- Service-user artwork gate passed before switch. Read-only live report/ledger/calendar checks passed before and after switch: valid distance sums and actual expense sums agree with their inputs; personal revisions and account/vehicle scope unchanged. No private values printed.
- All 16 overlay hashes and all tracked application source hashes match active release. Web process working directory matches active symlink. Web/monitor/nginx active; application services NRestarts=0; monitor process not restarted; no Web traceback in final window.
- Root HTTP 200; unauthenticated state/report/ledger/charging/routes/review APIs and new/static scripts HTTP 401. Existing production authenticated browser login was not repeated after session reset.
