# Charging detail parameter contract

## Scope

The charging page shows all 27 known charging/related energy parameters, grouped
into battery/range, voltage/current, state/connection, high-voltage supply,
charging lids/scheduling, discharge, and other energy observations. The top-level
`additionalVehicleStatus.chargeHvSts` is included, not just the electric subsection.
This is a read-only view of cached data, never vehicle control.

## Data boundaries

- `charging_details.PARAMETERS` is an explicit numeric-only whitelist. Raw objects,
  arbitrary keys, addresses, VIN, messages and credentials are not projected.
- `report_telemetry.normalize` saves these numeric observations in new snapshots.
  This additive data capture does not change the charging decoder or event IDs.
- Current Web data uses the same normalized snapshot and power calculation as
  monitoring. Power is same-observation U × I, not metered energy.
- Historical `charge_end` query results get a separate `charging_details`
  projection of saved start/end snapshots and an explicit statistics whitelist.
  Never expose the complete private `report_v2`, or fill historical gaps from the
  present vehicle. Earlier v2 snapshots can supply their saved numeric metrics;
  v1/malformed/unknown-version reports show an explicit unavailable state.
- Preserve unknown enum numbers with an unconfirmed label. Only verified lid
  values 1/2 are translated. Connection, schedule and high-voltage state codes
  are not independently interpreted. A temperature level is not pack temperature.
- Remaining charging time is shown only during confirmed charging with a valid
  0–2046 minute value. Sentinel 2047 is not a valid duration.
- Target SOC, stop reason, pack temperature, charging-pile billing and scheduling
  times remain unavailable until reliable API evidence exists. Do not turn a
  screenshot's one-time values into persistent vehicle settings.
- Partial record starts mean first observation, not physical charging start.
  Power statistics retain their existing sample/coverage gates and missing values
  are not replaced by zeros. SOC-based energy is not charging-pile billed energy.

## Verification

`tests/test_charging_details.py` and `tests/test_events.py` exercise whitelist,
missing/invalid data, legacy history and privacy. `tests/ui_energy.cjs` exercises
all 27 parameters, saved start/end comparison, missing history, disclosure and
selection persistence, and desktop/mobile overflow at widths down to 320 pixels.
