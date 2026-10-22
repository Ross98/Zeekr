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
  0–2045 minute value. Values 2046 and 2047 are not used as durations.
  In this vehicle's history, 2046 occurs around charging startup before ordinary
  estimates appear; its exact protocol meaning is unconfirmed. Show the estimate
  as unavailable, retain the raw code, and do not infer charging state from it.
  The same filter applies to overview, parameters, saved details, session summaries
  and notification rendering, including previously saved derived estimates.
- `dcChargeIAct` is battery-side current: positive means discharge, negative
  means charging or regenerative energy recovery, based on this vehicle’s history.
  Startup transition frames may contain unsynchronized battery/pile readings;
  use subsequent samples, external current and SOC changes together. The note
  does not change raw signs, charging detection or power calculations.
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

## 2026-10-22 研究结论采用范围

- 本车起充附近返回的2046与既有2047不进入分钟估计、预计结束时间或历史摘要；有效0分钟保留。原始参数仍保存，不改采集数据或充电状态判定。
- 无边框车门微降/回升为车主确认的本车行为；四窗说明纳入该背景，位置码8/12不标成已校准百分比，不从非零窗位反推门开。
- 小计B归零可延后于旧值返回，取消将观测间隔写成精确停车阈值；模式2→13不能代替清零检测，接口A/B与仪表行程对应继续待核。
- 安全带标记不能单独推定乘员；香氛激活不保证实际喷香；PM等级0不保证当前空气优；mode2不专属于充电。
- 湿度刻度、HV冷热方向、灯光完整枚举及充电结束原因未升级为已确认映射。本次只修展示保护和说明，不添加未经验证的解码规则。

依据：本车4735个去重历史状态的有界时序复核、日期分段反例及车主明确确认；非厂家协议。研究原始材料留在本机研究目录，不随代码发布，不包含个人轨迹或凭据。
