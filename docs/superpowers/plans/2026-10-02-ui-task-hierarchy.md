# UI task hierarchy — approved implementation

User approved implementing all five findings from the Impeccable critique together on 2026-10-02. Preserve the current Zeekr visual identity, cached-data semantics, one-vehicle scope and manual charging facts. The implementation approval covered local changes. Subsequent user instruction “部署了看看” authorized production deployment; see docs/ui-task-hierarchy-release-2026-10-02.md. No push performed.

## Scope and implementation

1. Add persistent secondary task controls to energy, vehicle and settings sections. Open ledger, comparison, life ledger, reminders and diagnostics as focused child content. Energy also has a charging-record task. Reuse existing module instances and DOM to preserve drafts and accepted data during polling.
2. Compact mobile overview: hide the large car artwork below 620 px, retain lock/charging state and cache age, place battery and range together within the first 390 × 844 viewport, and expose offline collection diagnosis.
3. Research empty state: show no archived reads explicitly, keep parameter catalog collapsed, offer a 30-day draft range and diagnosis. Date expansion requires the existing manual query action. Ledger totals label their recorded-bill denominator and separately identify unassociated records whose costs remain unknown.
4. Give affected text links, door disclosure, overview explanation summaries, settings summaries and task buttons at least 44 px hit height.
5. Settings separate enabled collection configuration, process online status and latest successful new observation. Detailed notification rules and storage/archive management have keyed disclosure sections. Keep collection pause consequences visible.

## Verification

16 browser suites passed: ui_task_layout, ui_charge_ledger, ui_overview, ui_energy, ui_research_manual_query, ui_automatic_insights, ui_refresh_scroll, ui_vehicle_research, ui_charge_comparison, ui_vehicle_life, ui_custom_reminders, ui_data_quality, ui_insights_navigation, ui_tool_navigation, ui_date_keyboard and ui_charge_management.

The scroll suite covers 40 desktop/mobile page/tool refresh cases. Relevant suites also verify drafts, account isolation, error retention, native date editing, themes, 320/390/1440 px layouts, 200% zoom, contrast and record recycle/restore.

Manual synthetic-fixture review checked mobile overview and ledger, desktop ledger/settings, archive management mount and research empty state. Screenshots are in `/tmp/zeekr-ui-refresh-20261002/`; overview-mobile.jpg and ledger-desktop.jpg are the reviewable previews. Fixture server and temporary browser tab were stopped after inspection.

One final Impeccable detector pass was run over the changed JS rendering surfaces and index.html. It reports the same four static fallback-color combinations as the initial critique and one advisory chart-stripe pattern. Runtime light/dark contrast suites pass. Detector output: `/tmp/zeekr-ui-detector-20261002.json`. No findings were waived in source and no unrelated palette changes were made.

JS syntax checks and git diff --check pass. The workspace already contains unrelated changes; no blanket staging, commit or push was performed. Subsequent scoped production deployment is recorded separately.
