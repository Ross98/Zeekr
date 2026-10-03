# Dashboard actions and travel insights release — 2026-10-03

User authorized commit and deployment, then restored SSH access after one authentication failure. No deployment occurred before access was restored. No push authorized or performed.

- Application commit: `d8235d5` (`feat: add dashboard action notices and travel insights`).
- Verified production source baseline: `851c51828d15` (all tracked application source hashes matched). Existing vehicle profile and AppleDouble metadata files were preserved.
- Active release: `/opt/zeekr-control/releases/20261003-dashboard-d8235d5`.
- Rollback: `/opt/zeekr-control/releases/20261002-trip-map-jump`.
- Code backup: `/opt/zeekr-control/backups/20261003-dashboard-d8235d5`.
- Candidate copied from `current/.`; 29 authorized application/test files overlaid. Untouched production application files retained and hashes checked. Private business data remains in place.
- Deployment manifest records the actual base commit and six feature groups: homepage exceptions, pending charge ledger, naming radius/preview, route comparison and weekly review, URL navigation, release summary. All six hash checks match.
- Scope includes earlier homepage/pending-ledger work and the remaining five dashboard features. Manual facts remain distinct from estimates; unknown observations and amounts remain explicit. Naming preview is read-only; save requires matching evidence/revision. No telemetry request or external notification was triggered during release.

## Verification

- Exact staged Git tree: 732 Python tests passed; navigation whitelist, remaining dashboard, overview attention, pending ledger, and place-name browser suites passed. Earlier refresh regression covered 42 desktop/mobile cases.
- Production-baseline candidate: 731 Python tests passed as service user in 72.252 seconds. This discovery reflects preserved production baseline tests. Service-user artwork/readability gate passed before cutover.
- Candidate and active-release live domain queries verified routes and weekly reviews for September and October; direction counts, pending counts and absence of raw coordinates/VIN/raw payload checked. Naming preview checked without saving. Personal collection revisions remained unchanged throughout these queries; account and vehicle scope rechecked.
- Atomic symlink switch, only web service restarted. Web, monitor and nginx active; application services NRestarts=0. Running web process directory matches the active release.
- All 29 overlaid file hashes match. Root HTTP 200; unauthenticated state, ledger, route, weekly review and new static scripts HTTP 401.
- Active deployment manifest: six matched feature groups. Production authenticated browser interaction was not repeated; UI behavior verified with synthetic fixtures and deployed hashes, live business queries verified as service user.
- Web login sessions reset. No historical event edits, private name changes, charging bill writes, vehicle refresh, monitor restart or notification resend performed.
- Unrelated local changes remain outside the commits and release.
