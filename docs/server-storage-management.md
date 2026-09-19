# Server storage health and archive maintenance

## Scope and UI

Settings → server storage and archive management. Requires the existing dashboard login; all mutations also require same-origin and request-key checks. No vehicle controls, cloud polling, raw snapshot downloads, credentials, VIN or location are added to this API.

The panel measures the filesystem containing the private data directory, including space used by other applications. It shows total/used/available bytes, percentage, inode use, logical data/archive/recycle sizes, last background check, delivery outcome and growth estimates. Units adapt from bytes to GiB. Directory sizes are logical sizes, not promises of reclaimable blocks. Read counts include cached or duplicate observations, not necessarily unique vehicle updates.

## Health and WeCom

- Existing collection owner runs a local check every 300 seconds, including while vehicle sampling is paused. No additional vehicle requests. No separate desktop automation required.
- Warning at disk use ≥80%, free ≤5 GiB, or inode use ≥80%; critical at ≥90%, ≤2 GiB, or ≥90%, respectively. Highest applicable severity wins, including when directory scanning is incomplete.
- Recovery hysteresis: critical retained until below 88%, above 2.5 GiB and below 88% inode; warning retained until below 78%, above 6 GiB and below 78% inode. Prevents threshold flapping.
- Existing WeCom sender, with persistent intent and outcome. Severity change/recovery notified; unchanged unhealthy status at most daily. Definitely failed deliveries retry after 15 minutes (one hour for permanent sender errors); ambiguous/interrupted attempts wait until the next daily reminder or severity change, not immediate retries.
- First healthy check sends no message. No real test notification is sent during acceptance.
- Monitor older than 15 minutes is marked stale. A stopped process, failed credentials/network, or completely full disk may prevent alerts: this is local best-effort monitoring, not an independent external watchdog.
- Growth uses at least 6 hours of measured samples, preferring the oldest sample within 24 hours; seven days of bounded samples are retained. Remaining days use whole-filesystem net growth and are estimates, not a guarantee. Data growth includes all files in the private directory, not only archives.

## Explicit maintenance only

Beijing calendar year grouping is preserved, internally using monthly SQLite files. Old years remain indefinitely; no automatic deletion.

Only an older month's complete snapshot archive can be moved into `snapshot-trash`. This is reversible and does **not** free space. Restore refuses to overwrite a newly created archive of the same month. Permanent deletion is available only from the recycle list, after another preview and typed confirmation. Current/future months, latest snapshots, credentials, trips, events and deployment backups are outside the deletion scope. Each archive contains all vehicles for that month: the preview states this explicitly.

Five-minute, session-bound, one-use preview tokens bind to file identity, size and timestamps. Restart invalidates tokens. Changed files require a new preview. Paths are strict IDs, never arbitrary paths. Symlinks, hardlinks, unsafe ownership/modes and SQLite sidecars are rejected. A shared archive lock serializes maintenance with writers. Durable private audit intent is required before mutation; completion is audited. If post-operation durability checks fail, the UI explicitly says the action executed and must not be blindly retried.

The estimated release size is allocated blocks of the selected file; open handles, filesystem snapshots, audit writes and independent backups can affect actual free space. This is not secure erasure of backups. Permanent deletion cannot be undone through this UI.

## Acceptance

`python3 -m unittest discover -s tests -q`; `tests/ui_storage.cjs` in Playwright. Tests use temporary synthetic data only. Covered: authentication/CSRF, session binding, protected month, traversal, links/sidecars, stale preview, audit failure, no overwrite, recycle/restore/purge, notification thresholds/restart/retry/ambiguity, paused sampling, responsive widths and confirmation preservation during ordinary UI render.
