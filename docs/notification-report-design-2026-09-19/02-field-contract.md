# 02 · 字段证据与数据契约

此文件规定数据能说什么。所有“已核对”仅限当前本车规则，且仍来自云端缓存。新增参数先解析成结构化值，再供报告使用；不要把网页展示字符串当统计输入。

## 1. 证据来源

| 代码/资料 | 用途与局限 |
|---|---|
| `zeekr_control/vehicle_state.py:9–59` | 当前动力、充电、SOC、里程、速度规则 |
| `zeekr_control/web_model.py:97–164,199–264` | 本车闭合、锁车、口盖、温度、轮胎、剩余时间的展示依据 |
| `zeekr_control/summary.py:73–74` | 左前/右前/左后/右后后缀映射 |
| `zeekr_control/profiles.py:10–40` | 容量与额定续航配置校验；不是实时BMS测量 |
| `docs/vehicle-parameter-dictionary-2026-09-18.md` | 字段名称、单位和待核实说明；不是所有枚举已知 |
| `docs/parameter-applicability-2023-we86.md` | 本车配置边界；配置不等于运行状态 |
| `docs/parameter-review.md`、`zeekr_control/field_reviews.py` | 人工记录只作注释，不直接驱动生产解码 |
| `docs/dc-charge-limit-reached-2026-09-17-181012.json` | 未跟踪现场证据：停止但仍插枪，连接字段为0；不能单凭0判断拔枪 |
| `docs/dc-unplugged-drive-selected-2026-09-17-181209.json` | 未跟踪现场证据：已拔枪，连接字段仍0；电压残留不能判断连接 |
| `docs/dc-charging-near-completion-2026-09-17-180826.md:5` | 之前车机目标90%，当次接口未取目标；禁止硬编码或跨事件复用 |

行号基于 `1fad4c6`，接手时重新定位。上述未跟踪文件仅是本地核验参考，不要求提交原始快照；实施测试使用脱敏合成样本。旧资料中按末级字段名添加的注释可能误套到低压电池 `chargeLevel`，应以完整路径与代码含义复核，不照抄注释。

## 2. 通用参数契约

以下是建议逻辑契约，不要求照搬类名；语义必须保留。

| 项 | 含义 |
|---|---|
| `value` | 已规范化的有限数值或明确状态；未知为null，禁止0占位 |
| `unit` | `% / km / km/h / kPa / °C / V / A / kW / min` 等固定单位 |
| `source_paths` | 实际完整字段路径数组；组合状态列出全部输入 |
| `origin` | `vehicle`车辆返回、`derived`观测计算、`estimated`容量/插值估算、`profile`静态档案 |
| `capability` | `enabled`已有可信规则、`pending_evidence`待核验、`not_applicable`本车不适用 |
| `validity` | `valid / missing / invalid / unverified / conflict / stale`；规则不匹配不等于反状态 |
| `state_time` | 该参数所在整车缓存的时间，Unix毫秒 |
| `field_time` | 确有独立字段时间才填；缺失为null，不伪造 |
| `observed_at` | 本机取到数据的时间；与车辆采集时间区分 |
| `time_basis` | `field_time`或`envelope_time`；没有独立时间必须可追溯 |
| `decoder_version` | 本车规则版本；历史比较排除不兼容口径 |
| `reason` | 不可用或降级原因的内部枚举，用于可解释文案 |

要求：拒绝 bool 冒充数值、NaN、Infinity、溢出、数组/对象注入；沿用现有数值范围，若收紧先写行为差异测试。容许API已有数字字符串；不能把空串、非法字符串转成0。判断属性存在与判断值为0分开。

当前可用字段若过期仍可在“结束点旧状态”块展示其最后值和原时间，但 validity=stale，不触发提示、不参与当前状态汇总。实时性质的充电剩余时间另按03抑制。

## 3. 行程、能源、速度字段

| 参数 | 完整路径/来源 | 单位与规则 |
|---|---|---|
| 状态时间 | `updateTime` | Unix毫秒；不是每个子字段的采集时刻 |
| 动力电池SOC | `additionalVehicleStatus.electricVehicleStatus.chargeLevel` | 0–100%；与低压电池字段严格区分 |
| 电池续航 | `additionalVehicleStatus.electricVehicleStatus.distanceToEmptyOnBatteryOnly` | 非负km；文案叫云端续航，不声称与当时仪表显示完全一致 |
| 总里程 | `additionalVehicleStatus.maintenanceStatus.odometer` | 非负km；倒退时差值无效 |
| 车速 | `basicVehicleStatus.speed` | 0–400 km/h；还需下行有效位 |
| 车速有效性 | `basicVehicleStatus.speedValidity` | 只认JSON true或现有字符串`true`；不认数字1、非空串 |
| 电池标称容量 | 事件保存的档案 `battery_capacity_kwh` | 有限正kWh；用于估算，不叫实时可用容量 |
| 额定续航/标准 | 事件冻结档案 `range_km / range_standard` | 配套保存；标准限定现支持的CLTC/WLTP/NEDC/EPA |

禁止替代：

- `additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.chargeLevel` 是低压电池，不可当动力SOC。
- `basicVehicleStatus.distanceToEmpty` 是通用字段，不回退代替电池续航。
- `additionalVehicleStatus.electricVehicleStatus.averPowerConsumption` 的统计区间未核验，不当本次能耗。
- `additionalVehicleStatus.electricVehicleStatus.indPowerConsumption` 的语义/单位未完整核验，不当瞬时充电功率。
- `additionalVehicleStatus.runningStatus.avgSpeed` 的统计口径未核验，不当本次平均速度。
- 额定续航达成率沿用现有 `energy.py` 的计算概念，但使用事件冻结额定配置；与“云端续航差”分开命名。

## 4. 门窗锁、动力、充电口盖

后缀契约：`Driver=左前`、`Passenger=右前`、`DriverRear=左后`、`PassengerRear=右后`。表中 `{Side}` 必须逐一替换这四个后缀，不得替换成轮序数字或缩写。

| 状态 | 完整路径 | 可用规则；反向边界 |
|---|---|---|
| 下电 | `basicVehicleStatus.engineStatus` + `additionalVehicleStatus.electricVehicleStatus.ptReady` | engine_off且0 → 下电；engine_on/engine_running或1 → 非下电；其余未知 |
| 已锁车 | `additionalVehicleStatus.drivingSafetyStatus.centralLockingStatus` + `additionalVehicleStatus.drivingSafetyStatus.doorLockStatus{Side}` | 中控2且四门全1 → 已锁车；缺失/不匹配未知，不等于未锁 |
| 四门关闭 | `additionalVehicleStatus.drivingSafetyStatus.doorOpenStatus{Side}` | 每门仅0 → 关闭；其余未知 |
| 四窗关闭 | `additionalVehicleStatus.climateStatus.winPos{Side}` | 每窗仅0 → 关闭；其余未知，不当开度百分比 |
| 尾门关闭 | `additionalVehicleStatus.drivingSafetyStatus.trunkOpenStatus` | 仅0 → 关闭；其余未知 |
| 交流口盖 | `additionalVehicleStatus.electricVehicleStatus.chargeLidAcStatus` | 仅2 → 关闭；其余未知 |
| 直流口盖 | `additionalVehicleStatus.electricVehicleStatus.chargeLidDcAcStatus` | 1 → 打开；2 → 关闭；其余未知 |
| 前舱盖 | `additionalVehicleStatus.drivingSafetyStatus.engineHoodOpenStatus` | 尚无可靠开闭规则，候选门控 |
| 尾门锁 | `additionalVehicleStatus.drivingSafetyStatus.trunkLockStatus` | 尚无可靠独立锁状态，候选门控 |
| 电子驻车 | `additionalVehicleStatus.drivingSafetyStatus.electricParkBrakeStatus` | 0/1仅是本车行驶/停车充电场景样本；不能输出“驻车制动已拉起” |
| 挡位 | `additionalVehicleStatus.drivingBehaviourStatus.gearAutoStatus` | 3在挂D样本出现；0不可解释为P，默认不进停车结论 |

四门、四窗和尾门是独立维度。已锁车不能替代已关窗、尾门关闭，动力下电不能替代P挡或驻车制动。门锁组合中有字段缺失时，不能保留上一条“已锁”作为此时状态。

`winStatus{Side}` 和 `winPos{Side}` 不同；不能凭字段名称认为编码等价。车窗在climateStatus里，不代表它适用温度的独立更新时间。

## 5. 温度、胎压、胎温

| 参数 | 完整路径 | 范围/时间 |
|---|---|---|
| 车内温度 | `additionalVehicleStatus.climateStatus.interiorTemp` | -80–100°C，优先用温度独立时间 |
| 车外温度 | `additionalVehicleStatus.climateStatus.exteriorTemp` | -80–100°C，同上 |
| 温度时间 | `additionalVehicleStatus.climateStatus.temperatureUpdateTime` | 校验为毫秒时间；只用于温度 |
| 四轮胎压 | `additionalVehicleStatus.maintenanceStatus.tyreStatus{Side}` | kPa，现代码接受非负值；数值0需标“零值待确认”，不推爆胎 |
| 四轮胎温 | `additionalVehicleStatus.maintenanceStatus.tyreTemp{Side}` | -80–150°C；只有整车缓存时间，无独立轮胎时间 |

温度独立时间的端点有效条件：`state_time−field_time`在[-30秒,180秒]内。超前超过30秒为invalid，不用其数值作当前温度或温差；落后超过180秒为stale，可保留单值及原时间。缺独立时间：可显示“时间未单独提供”的单值，但不出起止温差或当前异常判断。不因整车updateTime变新而刷新温度。

起止温差/胎压差先满足03的时间和有效性条件。单位转换只做展示；内部统一kPa。报告默认不使用自设高低胎压或温度危险阈值，也不以左右轮差值诊断漏气、制动或传感器故障。

## 6. 已有条件证据的充电参数

| 参数 | 完整路径 | 规则 |
|---|---|---|
| 通用充电状态 | `additionalVehicleStatus.electricVehicleStatus.chargeSts` | 不单独解释任意数字；跟随当前decode组合 |
| 充电器状态 | `additionalVehicleStatus.electricVehicleStatus.chargerState` | 活动24/停止26须配套其他条件 |
| 直流状态 | `additionalVehicleStatus.electricVehicleStatus.dcChargeSts` | 活动12/停止10须配套其他条件 |
| 桩侧电压 | `additionalVehicleStatus.electricVehicleStatus.dcChargePileUAct` | 0–1500 V；非零电压不等于正在充电/插枪 |
| 桩侧电流 | `additionalVehicleStatus.electricVehicleStatus.dcChargePileIAct` | -2000–2000 A；功率仅取可靠正向充电样本 |
| 剩余时间 | `additionalVehicleStatus.electricVehicleStatus.timeToFullyCharged` | 0–2046分钟，且charging=true；2047是无有效估计；不保证到100% |
| 枪连接字段 | `additionalVehicleStatus.electricVehicleStatus.statusOfChargerConnection` | 本车0横跨插枪和拔枪，连接语义未核验 |

当前直流活动组合：直流口盖1、chargerState24、dcChargeSts12、合法桩侧电压>0且电流>0。与有效非零车速/动力就绪冲突时，活动判断未知。

当前直流停止组合：直流口盖1、chargerState26、dcChargeSts10、合法桩侧电流0、无非法直流字段、无有效行驶或动力运行冲突。沿用 `vehicle_state.decode()`；不在模板再写一份较宽松判断。它证明匹配本车停止样本，不证明停止原因、目标达成或拔枪。

`chargeSts/chargerState/statusOfChargerConnection`三项全0或已配置文字/状态码仍需经过现有冲突与直流证据排除。报告不新增充电启停判定。交流类型未校准；“不满足直流”不等于交流。

功率为 `U×I/1000` 的观测计算值，非独立传感器功率。两值来自同一接受快照，但整车封装不保证子字段严格同步；保留此限制。`chargeUAct/chargeIAct/dcChargeIAct`不可混搭桩侧值，未经核验不作回退。

## 7. 候选能力：方案完整，证据不足先禁用

以下 logical key 是未来内部契约，**不是声称接口已有这些字段**。

| 能力/逻辑键 | 默认呈现 | 启用所需证据 | 通过后的规则 |
|---|---|---|---|
| 目标SOC `target_soc` | 暂未取得 | 明确字段路径、0–100单位、当前会话适用性、独立时间/目标变更规则；与车机对照 | 冻结开始/结束目标；变化写70%→80%，不沿用过去事件目标 |
| 目标达成 `target_reached` | 不给达成结论 | 同一次充电结束观测的有效目标与SOC、分辨率 | end_soc≥当时target才写达到；不使用显示取整后值，不猜误差容忍 |
| 枪连接 `connector_state` | 未确认 | 插枪未充电/充电/停充仍插枪/拔枪四组反例，独立可靠组合 | connected/disconnected/unknown；与口盖、功率、充电状态分开 |
| 停止原因 `stop_reason` | 未确认 | 明确原因字段/组合，至少区分目标达成、人工停止、车辆/桩中断和未知；实测事件时序 | 只翻译核验过的原因；SOC相等、电流0不提供因果 |
| 动力电池温度 `pack_temperature` | 省略 | BMS/电池对象、传感器位置/统计含义、°C比例及更新时间对照 | 明确叫平均/最高/最低或指定位置温度，不统称一个含混电池温度 |
| 交流充电模式 `charging_mode=ac` | 模式未确认或省略 | 本车交流口盖打开码、电气参数、连接/启停组合和冲突样本 | 通过共享decode识别；后续按同侧U/I口径统计 |
| 门/窗打开及未锁 | 对应项未确认 | 每项已开/已闭/通风位/解锁样本，缺失及冲突样本，编码方向确认 | 才能启用未关/未锁提示；未知→已锁只能说“后续确认已锁” |
| 前舱盖/尾门锁 | 未确认或省略 | 对应开闭/锁解锁独立场景 | 不从中控锁推导 |
| 车辆胎压报警 `tyre_alert` | 省略 | 明确报警字段、轮位、激活/解除映射及时间；现四轮数值不是报警位 | 显示“车辆上报的…提示”；不扩展为诊断 |
| 驻车制动/P挡 | 省略 | 本车明确开关/挡位对照，不止场景相关值 | 独立呈现，不代替下电 |

`additionalVehicleStatus.electricVehicleStatus.hvTempLevel`只知温度等级，不能转换为°C。`additionalVehicleStatus.drivingSafetyStatus.vehicleAlarm.alrmSt/alrmTrgSrc`未核验，不能当胎压报警。旧的`theftNotification.time`不用于宣告当前防盗事件。

本车资料已明确若干未选装项：空气悬架、方向盘/后排加热、电动遮阳帘、EC天幕、自动开合门。参数存在不证明功能存在；本轮不把这些舒适项铺进报告。固定玻璃天幕和电吸门也不能据此说不存在。

## 8. 能力核验流程

1. 建立本车能力登记：logical key、真实路径、单位、规则版本、适用车型/车辆摘要、证据说明和合成fixture。
2. 从已授权的只读样本提炼正例、反例、缺失、矛盾、旧值；本轮不为了核验主动操控车辆或发送消息。
3. 独立核验每个枚举方向；确认某个值不代表整个字段所有编码已知。
4. 测试通过后才把指定规则标为enabled；不能从网页人工备注、自由文本公式、资料名或字段名自动启用。
5. 没有证据则保持pending_evidence，整套报告仍可运行；在交付清单明确列出待采样项目。

复用方向：把web_model中已确认的语义提炼到共享纯解析层，使网页和报告引用同一规则。迁移须维持原网页行为；不可直接调用 `fields_for()` 再解析中文文案，也不可加载整个原始raw到通知公共模型。
