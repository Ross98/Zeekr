# Charging progress integration

Approved direction: power and SOC share one chart and a single Beijing-time axis. Power uses a zero-origin left axis, SOC a fixed 0–100% right axis. Blue power and green stepped SOC can be toggled independently. Existing session summary, electrical details, history and time picker stay available. No target or ETA is inferred from unavailable/unverified data.

1. Add browser regressions for shared time bounds with asymmetric missing values, zero, gaps, isolated samples, toggles, pointer/time-picker selection and keyboard focus.
2. Extend existing geometry with explicit shared time bounds; build the combined chart using that geometry. Preserve all supplied points and segment boundaries.
3. Update chart selection in place rather than replacing the range or hover target. Keep theme colors accessible, legends wrapping and narrow chart scrolling within its container.
4. Run focused UI/domain regressions and inspect synthetic desktop light/dark captures. Simplify common selection and geometry behavior.
5. Commit only named source/tests/docs. Snapshot current production, verify it matches the committed baseline, copy to a separate candidate, overlay only this change, run service-user checks/tests, retain rollback and state backup, switch atomically, verify hashes/services/access boundaries. Do not push.
