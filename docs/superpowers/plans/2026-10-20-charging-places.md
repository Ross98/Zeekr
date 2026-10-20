# Charging places implementation and acceptance ledger

User approved all five directions on 2026-10-20; implement in existing isolated worktree, then provide desktop acceptance. No production release in this step.

## Requirements

1. Resolve the whole charge interval using fresh historical location observations; reject drift/conflicts. Infer missing locations only with corroborated stationary continuity and adjoining trip endpoints. Preserve provenance and unknowns.
2. Inline edit name/location. Preview single-event versus same-place historical/future scope before saving. Keep manual corrections separate from raw events. Reuse existing place names as the base. Revision/context guarded, undo supported.
3. Separate venue and confirmed charging station. Explicit nearby candidate lookup through existing server geocoder; never confirm the nearest station automatically. Provider/config failure leaves manual editing available.
4. Map closed by default, loaded only on demand; show historical samples/evidence and support WGS84 correction. No current vehicle lookup.
5. Month-level place aggregation: charge count, known costs, estimated energy, paired bill price, unknown counts, independent AC/DC distribution; filter records by place.

## Design rulings

- Existing flow extension; no new independent service or database. Use additive `charging_places` PersonalStore collection for charge-specific single/region overrides. Existing `place_names` and commute regions remain the naming base; corrections do not silently rename trip history.
- Monthly API remains scalar/no coordinates. Authenticated detail API returns only selected charge location/evidence. Explicit candidate lookup is the only provider call; initial page loads remain offline historical reads.
- Same-place rules match observed position around a fixed source anchor, not venue-name equality; manual destination pin does not move the matching anchor. Single overrides take priority; never merge equally named distant venues.
- Preview/save are bound by HMAC over owner, vehicle, exact proposal, matching event IDs/evidence and revisions. Save rechecks the plan; stale previews fail. Reuse PersonalStore undo.
- Unknown prices stay unknown. Place price uses only charges with both actual amount and metered kWh; SOC energy is labelled separately. Unknown-place events are explicitly unlocated, not a confirmed shared venue.

## Execution

- [x] Test and implement conservative charge location model.
- [x] Test and implement scoped correction preview/save/undo and station candidates.
- [x] Integrate context-guarded APIs and scalar monthly place statistics.
- [x] Implement desktop place editor, optional map and place summary/filter.
- [x] Focused Python/API/browser checks; screenshots and manual visual review.
- [x] Read-only real-data replay; expose local acceptance preview and record limitations.

## Verified result — ready for user acceptance

- 17 charging-place model tests cover whole-session drift/conflicts, stale/cross-vehicle rejection, continuous parking fallback, retained references, explicit candidate-only coordinates, HMAC/revisions/expiry/guards, owner scope, region edits/shrinkage, single-to-region conversion, undo, independent equal-name sites, paired weighted/free/unknown prices.
- Focused Python regression command completed 151 tests in 19.366 s. Final streaming/reference metadata changes rechecked with the affected 34 model/review/lock tests (0.319 s). Initial final command used nonexistent `test_analysis_cancel`; corrected to `test_analysis_cancellation`, with actual passing result recorded. No unrelated Python full suite during implementation.
- New charging-place desktop browser flow passed after final changes: initially no map/detail/provider calls; evidence/drift counts; venue/station separation; explicit candidate choice; preview invalidation; cross-month impact; single/region corrections; click and drag map updates; numeric WGS84 entry; unknown-location refusal; undo; separate browser-context synchronization; 1024/1280/1440 light/dark and contrast. Screenshots in /tmp/zeekr-charging-places/.
- Existing charging-review, charging-intervals and trip-place-name browser regressions passed. 17 JS unit files, 32 syntax files passed. Manifest: 111 CJS files classified; diff check passed.
- Actual service-user read-only replay preserved bills/names/corrections and the prior 539 km / 103.2 kWh October interval result. September: 5 charges, 1 resolved location; October: 3 charges, 1 reference location, 2 retained candidate-only precharge positions. The latter differ from contemporaneous positions by about 85/169 m, so remain explicitly unconfirmed. No production file/database migration.
- Real existing geocoder configuration tested read-only: request succeeded, 0 charging POIs for the selected reference point. Positive candidate selection covered by deterministic synthetic provider; actual empty/failure states stay editable. Live map tile availability is not promised by synthetic browser checks.
- Real historical local acceptance copy: http://127.0.0.1:18766/?p=energy&energyTab=summary&month=2026-10. Private input file lives only in .git/local-work-audit; original VIN/session credentials are never required by the preview, and cloud vehicle access is disabled. All interactive writes are confined to a temporary SQLite copy. Health check: 3 charges, bills total 108.22 yuan, interval distance 539 km, 1 automatic reference plus 2 explicit candidates.
- Full synthetic interaction example: http://127.0.0.1:18767/?p=energy&energyTab=summary&month=2026-09. Station candidates and map-test tiles are synthetic in automated screenshots.
- Main worktree/shared index: 240 prior protection hashes unchanged. This isolated branch remains at c4c8a91; new feature changes uncommitted/undeployed/unpushed. User acceptance remains pending. Production remains previous approved release.
