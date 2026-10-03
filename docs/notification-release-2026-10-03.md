# Notification release — 2026-10-03

User authorized deployment. Application commit: `9e6cfde` (`feat: simplify vehicle reports and add tyre anomaly notifications`). No push requested or performed.

- Active release: `/opt/zeekr-control/releases/20261003-notifications`.
- Rollback: `/opt/zeekr-control/releases/20261003-charging-readability`.
- Code backup: `/opt/zeekr-control/backups/20261003-notifications`; consistent personal database backup in its root-only `private` directory (0700, database 0600).
- Production source matched the preceding Git HEAD before staging. Candidate copied from `current/.`; only 20 authorized source, test and design-document files overlaid. Unchanged production files and vehicle profile verified against the old release. Unrelated local UI tests and private files excluded.
- Trip reports omit routine vehicle-status inventory and include only fresh, verified exceptions. Charge-end reports retain a short core summary and relevant limitations. Previously delivered notification text is not manually rewritten or resent.
- Tyre alerts use default light-load 260 kPa and manual full-load 290 kPa references, approved continuous-observation thresholds, per-wheel escalation/recovery, grouped notifications and durable account/vehicle-scoped state. Bark and WeCom delivery are independent. Settings and recent delivery history appear under Settings → Custom reminders.
- Release metadata preserves the prior base and seven feature groups, updates affected hashes, and adds notification-brief and tyre-alerts. All nine groups match their running files.

## Verification

- Local full suite: 761 tests passed in 49.404 seconds. Focused notification/release tests: 29 passed. Tyre settings synthetic browser check and existing custom-reminder functional regression passed; desktop/mobile, light/dark, contrast and 200% zoom checked during implementation.
- Exact production candidate full suite passed as `zeekr-control`; discovery confirmed 760 candidate tests. Candidate excludes pre-existing local-only work. Service-user artwork/readability gate and candidate scope/hash checks passed.
- Atomic switch completed; both web and monitor restarted into the candidate. Web, monitor and nginx active; both application services NRestarts=0. Both process directories resolve to the active release.
- All 20 overlaid file hashes match. Root HTTP 200; state, tyre/rule APIs and custom-reminders script reject unauthenticated requests with 401.
- Natural monitor collection created the scoped durable tyre state. Read-only domain query succeeds, personal database integrity check passes and permissions remain 0600. Pre-release records, revisions and changes remain present and unchanged compared with the consistent backup.
- No manual vehicle refresh, history edit, notification resend or real-message test performed. Web login sessions reset. Production browser interaction was not repeated; synthetic UI checks, deployed hashes, HTTP access checks and durable domain checks provide the verification.
