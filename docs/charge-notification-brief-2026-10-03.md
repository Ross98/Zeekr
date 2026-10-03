# Brief charge-end notification — 2026-10-03

User approved the proposed short charge-end template. Local change; not committed or deployed. Earlier approved trip notification changes remain in place.

- Bark start/end alerts retain the existing short templates. Enterprise WeChat charge-end text keeps location, recorded time range and observed duration, SOC change, valid estimated charging energy and range increase, AC/DC type, peak sampled power and observed average power.
- Removes routine vehicle/temperature/tyre state inventory, stop voltage/current, tail power drop and historical comparison. Unknown target/stop reason/connector inventory is removed; title still says charging stopped, never full or unplugged.
- Unknown energy/average power remains explicit. Partial records and insufficient power coverage remain explained. Unknown actual start time gets one short note; uses recorded range wording rather than claiming an exact start event. Normal observation count/full timing evidence no longer expands the charge-end push.
- Reuses fresh verified attention rendering; unknown/pending capability items do not become alarms. An open cover after a charging stop does not independently establish an abnormal state, so charge-end pushes omit that status item. Verified warning/critical attention items survive byte-budget fallback.
- Stored report data, analytics and historical frozen notifications remain intact. No real notification or telemetry request sent.
- Regression covers normal/partial/unknown/zero, message size and warning retention, read-only rendering, AC provenance, cross-midnight charge/restart/stop/resume, unchanged Bark, and earlier trip exception-only behavior.
