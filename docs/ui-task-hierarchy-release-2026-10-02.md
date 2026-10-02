# UI task hierarchy release — 2026-10-02

User explicitly authorized deployment with “部署了看看”.

- Active release: `/opt/zeekr-control/releases/20261002-ui-task-hierarchy`.
- Previous release and rollback: `/opt/zeekr-control/releases/20261002-ledger-edit-scroll`.
- Backup: `/opt/zeekr-control/backups/20261002-ui-task-hierarchy`.
- Scope: six UI source files and six browser regression files, copied over current production contents. Candidate scope comparison confirmed exactly 12 changed files.
- Service-user artwork gate passed. Full candidate unittest command returned exit 0; service-user discovery confirms 704 cases.
- Seven candidate browser suites passed: task layout, 40 refresh/scroll checks, tool navigation, draft/account isolation, ledger writes, charge comparison and quality diagnostics. The implementation had separately passed 16 local browser suites.
- Atomic cutover and restart of web service only. Both web and monitor active/running, NRestarts=0; nginx active.
- All 12 deployed file hashes match; running web process directory matches active release.
- Root HTTP 200; unauthenticated /api/state, /static/app.js and /api/insights/ledger return 401.
- Web login sessions reset on restart. Vehicle sessions and historical data retained; no telemetry refresh, event edits, notification resend, database migration or monitor restart was requested.
- Local Git remains on codex/notification-reference-location, HEAD bc5596d36388bdfe3ff13345b4cb94e6fcbf3a43. UI release consists of scoped uncommitted working files. No commit or push performed.

## Deployed manifest

- `zeekr_control/static/app.js`: `be12c9d2f99ab8d773b3c518d373974e0e8d165a76a66a2ea66cc4b3588d7144`
- `zeekr_control/static/app.css`: `64d1f827bb0ac9c63f7a65f706ae10bad1e1d4af3ca08ea5f1e978d257700f08`
- `zeekr_control/static/insights.js`: `9288c3215e50c0cb812e61e8ee4b8e1b33708baff7fe6227929971ee7c65b7e3`
- `zeekr_control/static/insights.css`: `b4044eca991c8b013114c442b65e69c2b078954f713fff48d5558da2742ee056`
- `zeekr_control/static/charge-ledger.js`: `41bd690a9bc001cb130e7a36404fb001f1c2c4a5ba610923ddee7cbc3a785ae9`
- `zeekr_control/static/vehicle-research.js`: `103472a6469c660e58cc5aafccb29bc11b982ff7e13ed4c79de4cdbf3b27699a`
- `tests/ui_task_layout.cjs`: `bf045178800528d4a0261f61f2d93fb10f08b562e8b0c6ee8e416eb1c15dccba`
- `tests/ui_refresh_scroll.cjs`: `e1738f5dcd1a942a6edbde912524f045925235793ecf525efef6d7395bd2b313`
- `tests/ui_charge_comparison.cjs`: `44c5975724e3bd6a2b140b914783acc83f2d16975b1c5a8a979f013bd47fc51d`
- `tests/ui_data_quality.cjs`: `ccc6ab8c3f8722938aed562cedbca85738ed5350d590427f3764231c0e1b6eac`
- `tests/ui_insights_navigation.cjs`: `429c4bacbcc079df3c34c9d88c97066f4de3790e16a5de28be89d43707c08133`
- `tests/ui_tool_navigation.cjs`: `1ee3c308166aeb600b25fc558507cb56900d8e5059d9c81e59d9ce5da668bafe`
