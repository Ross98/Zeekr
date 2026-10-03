# Trip notification state details — 2026-10-03

User requested that routine vehicle states appear in trip pushes only when abnormal. Local implementation; no commit, deployment or notification send performed for this change.

- Trip report retains route/endpoints, time, distance, SOC and valid energy metrics, existing history reference and evidence/completeness notes.
- Removes routine parking-state inventory, temperature/tyre inventory and normal subsequent lock/closure confirmations from trip notification text. Stored report evidence and dashboard detail remain intact.
- Adds a short attention section only for fresh, verified attention items. Unknown and pending capabilities are not treated as abnormal. An open DC cover only needs attention when the same parking observation confirms charging is false; active/unknown charging suppresses that status item.
- Existing stale-observation and partial-record notes remain explicit; no claim that omitted states are normal. No temperature/tyre thresholds or unverified reverse enums introduced.
- Bounded-message fallback retains verified attention items; removes its old blanket lock/door/window/boot inventory sentence.
- Charge reports retain their existing states. Bark trip brief and route PNG already contain core data and need no change. Frozen delivered messages are not rewritten or resent.
- Tests cover normal suppression, verified exceptions, normal follow-up suppression, unknown states, stale states, charging cover context, byte-budget fallback and unchanged charge reports.
