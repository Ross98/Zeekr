# Charging progress integration release — 2026-10-04

User approved the synthetic preview, then explicitly authorized integrating it into the actual charging page, testing and deployment. No push performed.

Application commit: `047d7e1` (`feat: combine charging power and SOC on shared time chart`). The default process view now combines blue power and green stepped SOC on one shared Beijing-time axis. Power uses a zero-origin left axis; SOC a fixed 0–100% right axis. Independent checkboxes control visibility. Pointer selection and the existing keyboard-accessible time picker update the same saved observation in place without replacing the focused range. Electrical details remain available.

Different missing-value ranges cannot shift either series horizontally. Missing samples and segment boundaries break paths; isolated valid points and valid zero remain visible. Missing/unverified target and ETA stay unavailable. No analytics calculations, telemetry queries, notification policy, personal records or historical events were changed.

## Validation

- New browser regression was written first and failed against the previous separate-chart layout. Final committed-source tests passed for shared axes, asymmetric missing values, zero, gaps, isolated samples, independent/all-hidden toggles, pointer/range selection, keyboard focus, empty data, single samples, light/dark themes, 1440/390/320 widths and visible-text contrast. Synthetic chart captures were inspected.
- Actual chart geometry test passed, including shared-bound alignment with missing endpoint values and zero-origin power.
- Existing energy browser regression passed on the exact committed tree: current/history selection, loading/errors, account/race protection, electrical details, keyboard, refresh and target widths.
- Eight scoped energy-page desktop/mobile background-refresh checks passed. The old full-site refresh script still references a removed map-navigation control and times out there; no unrelated navigation/test change was included.
- JS syntax and diff checks passed; Impeccable detector found no findings.
- Production baseline `7851990`: 120 application files matched their committed source (private vehicle profile and macOS metadata preserved separately). Only six committed source/test/plan files were overlaid on an independent copy of `current/.`.
- Candidate service-user full Python suite: 800 tests passed in 82.916 seconds. Service-user artwork gate passed; all 12 prior feature groups remained matched.

## Deployment

Active release: `/opt/zeekr-control/releases/20261004-charging-progress-047d7e1`.
Rollback: `/opt/zeekr-control/releases/20261004-all-pending-7851990`.
Stopped-state backup: `/opt/zeekr-control/backups/20261004-charging-progress-047d7e1`.

Preparation and cutover held the deployment lock and rechecked the baseline. Both application services stopped for a content/permission/ownership-verified state backup, then the release symlink switched atomically. Both application processes run from the new release; web, monitor and nginx are active/running with `NRestarts=0`.

All six deployed-file hashes match the commit; untouched baseline hashes remain identical. Active release summary reports `047d7e1` and 12 matched features. Root and public theme CSS return 200; unauthenticated charging process/statistics, private scripts, location/map, report and calendar return 401. Artwork gate passed again; no new Web traceback was found.

Web login sessions reset. Authenticated production browser interaction was not repeated; UI evidence comes from the committed-source synthetic tests, with deployed hashes/services/access boundaries verified separately. No manual vehicle refresh or notification send was performed. Unrelated local modifications/private files remain outside the commit and release.
