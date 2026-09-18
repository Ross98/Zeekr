# 本车车辆参数全量中文词典

编制日期：2026-09-18。整车缓存时间：2026-09-18 12:12:02（北京时间）。

本次通过已有账号成功读取 GW2 缓存状态和车辆列表，共 **200 个状态叶子字段、37 个车辆档案叶子字段**。状态字段中 **19 个为 null**；非空不等于有效测量。本机随后读取完整结构时命中 60 秒缓存，未再次向车辆状态接口发起请求。与 docs 内 5 份实车历史快照取字段并集核对，未发现额外状态路径。数量不含 CLI 的车辆序号包装字段，也不含容器对象。

这是当前账号、当前读取端点可取得的完整字段清单，不是车辆所有 ECU/CAN 信号清单。没有获取到动力电池 SOH、单体电芯电压／温度、完整故障码、全部硬件配置；不能从空值、通用兼容字段或网上其他车型参数补造本车数据。精确位置、VIN、卡号及设备标识的值已隐藏，字段名保留。未查询历史行程接口。

## 阅读规则

- 每行保留完整字段路径、原始 JSON 类型、中文术语、单位、解释依据及注意事项。带引号的是字符串；null 表示空值。
- “已返回”只表示接口给出了值，不代表所有单位和枚举均经官方确认。“本车已核对／场景观察”沿用本项目已有实车记录，不是本次重新操作车辆验证。
- “推测”主要依据英文名称和通用汽车术语；中文名称置信度与状态码置信度分开。未获取官方完整枚举表，不能统一按 0=关、1=开翻译。
- Driver／Passenger 对应本车左前／右前；DriverRear／PassengerRear 对应左后／右后；drv/pass/rl/rr 对应主驾／副驾／左后／右后。
- Sts/Status 为状态；Act 为实际值或激活（须结合词组）；U/I 通常为电压／电流；HV 为高压；PT 为动力系统；Detail 可能为档位或细分状态。

## 本次主要读数

| 参数 | 缓存值 | 说明 |
|---|---|---|
| 动力电池 SOC | 86% | 动力电池专用 chargeLevel |
| 预计剩余续航 | 417 km | 仪表／云端估算，不是实际可行驶保证 |
| 累计里程 | 44,681 km | odometer |
| 平均电耗 | 18.6 | kWh/100 km 来自社区实现；统计窗口待核实 |
| 低压辅助电池电压 | 13.150 V | 不属于高压动力电池 |
| 低压辅助电池电量 | 98.7 | % 为社区单位解释 |
| 车内／车外温度 | 27.7 / 31.0 °C | 缓存读数 |
| 左前／右前胎压 | 281.465 / 281.465 kPa | 单位和轮位沿用本车核对结果 |
| 左后／右后胎压 | 284.211 / 282.838 kPa | 约 2.84 / 2.83 bar |
| 左前／右前／左后／右后胎温 | 34 / 33 / 34 / 33 °C | 缓存读数 |
| 车速 | 原值 0.0，标记无效 | 不报告为有效实时车速 |

## 网络资料及证据边界

- **S1：[RexzeLu/zeekr_ha 传感器定义](https://github.com/RexzeLu/zeekr_ha/blob/316ce6e7ea718b3d5ba4597bf87627904add5330/custom_components/zeekr_ev/sensor.py)**，固定提交 316ce6e7ea718b3d5ba4597bf87627904add5330：支持电量、续航、温度、胎压、充电电压电流、分钟、低压电池及平均电耗等社区单位解释。其规范化字段不等于本账号原始字段的官方协议。
- **S2：[HELLA 自适应前照灯技术](https://www.hella.com/techworld/us/technical/automotive-lighting/adaptive-headlights/)**：支持 AFS 与 Highway light 的通用术语；将本车 afs/hwl 对应到这些术语仍属推测。
- **S3：[HELLA 弯道照明技术](https://www.hella.com/techworld/us/technical/automotive-lighting/bend-lighting/)**：区分动态弯道照明与静态转角灯；用于 dbl/cornrgLi 候选中文术语。
- **S4：[Volvo 官方主动远光及转向照明说明](https://www.volvocars.com/en-sa/support/car/s60/13w46/article/74259aa7e21a5a62c0a801e800c6d3d7/08667bc53248ec06c0a801e800a0d50f/89dfc16ac4f86befc0a801e801b559a3/)**：支持主动远光功能描述；不是极氪 ahbc 的枚举定义。
- **S5：[evcc 的同类网关数据结构](https://github.com/evcc-io/evcc/blob/master/vehicle/smart/hello/types.go)**：可佐证相似原始路径及通用兼容字段存在；这是 smart 实现，不移植其平台／充电枚举到本车。
- 本车既有证据：[接口记录](api-notes.md)、[快充实车快照](dc-charging-parameters-2026-09-17.md)、[充电结束附近快照](dc-charging-near-completion-2026-09-17-180826.md)，以及当前项目 web_model.py 中已核对规则。

## 容易误读的字段

- mainBatteryStatus 实际用于低压辅助电池；其中 stateOfHealth=0 不能当成动力电池健康度为 0%。temStatus.backupBattery 又是通信模块备用电池。
- dcChargePileUAct 当前仍有 397.2 V，电流为 0；保留电压不是充电进行中的充分证据。
- 直流充电时，chargeSts、statusOfChargerConnection、chargeUAct、chargeIAct 曾同时为零；应联合直流专用字段判断。
- 2047 按现有项目规则作为无有效时间估计；101 可能为天窗／遮阳帘未配置或无效值，尚不能确定。
- ahl 有“自动大灯调平”和“自适应前照灯”两种候选；cdsClimateActive、eg.blocked.status、fuelEnCnsFild 无可靠细分释义，保留歧义。



## 状态：basicVehicleStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `basicVehicleStatus.usageMode` | 使用模式 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `basicVehicleStatus.engineStatus` | 动力状态 | `"engine_off"` | — | 本车场景观察 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：动力关闭。 | 本次接口返回＋字段命名 |

## 状态：basicVehicleStatus.position

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `basicVehicleStatus.position.altitude` | 海拔高度 | `"15"` | m（推测） | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `basicVehicleStatus.position.posCanBeTrusted` | 定位可信标记 | `"true"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `basicVehicleStatus.position.latitude` | 纬度 | `"[已隐藏]"` | 原始坐标（缩放及坐标系须依解码规则） | 字段直译／缩写推测；枚举未核实 | 精确位置隐藏；坐标换算与可信性应结合 position 内其他标记。 | 本次接口返回＋字段命名 |
| `basicVehicleStatus.position.carLocatorStatUploadEn` | 车辆定位状态上传使能 | `"true"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `basicVehicleStatus.position.marsCoordinates` | 火星坐标系标记（GCJ-02 相关） | `"false"` | — | 字段直译／缩写推测；枚举未核实 | 字段名通常指 GCJ-02 标记；false 与坐标系的对应关系尚无官方协议证据。 | 本次接口返回＋字段命名 |
| `basicVehicleStatus.position.longitude` | 经度 | `"[已隐藏]"` | 原始坐标（缩放及坐标系须依解码规则） | 字段直译／缩写推测；枚举未核实 | 精确位置隐藏；坐标换算与可信性应结合 position 内其他标记。 | 本次接口返回＋字段命名 |

## 状态：basicVehicleStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `basicVehicleStatus.distanceToEmpty` | 通用续航 | `"0"` | km（通用） | 字段直译／缩写推测；枚举未核实 | 本车该通用字段为 0；续航使用 distanceToEmptyOnBatteryOnly。 | 本次接口返回＋字段命名 |
| `basicVehicleStatus.carMode` | 车辆模式 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `basicVehicleStatus.speed` | 车速 | `"0.0"` | km/h；需 speedValidity 有效 | 字段直译／缩写推测；枚举未核实 | 当前 speedValidity=false；0.0 不能作为有效瞬时车速或独立停车证据。 | 本次接口返回＋字段命名 |
| `basicVehicleStatus.speedValidity` | 车速有效性 | `"false"` | — | 已返回 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：无效。 | 本次接口返回＋字段命名 |
| `basicVehicleStatus.direction` | 车辆航向角（推测） | `"0"` | °（推测） | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：notification

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `notification.notifForEmgyCallStatus` | 紧急呼叫通知状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：eg.blocked

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `eg.blocked.status` | EG 阻止／禁用状态（具体功能未知） | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：parkTime

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `parkTime.status` | 停车时间戳（推测） | `"1789704235402"` | Unix 毫秒（推测） | 字段直译／缩写推测；枚举未核实 | 2026-09-18 12:03:55 北京时间；停车触发语义待核实。 | 本次接口返回＋字段命名 |

## 状态：theftNotification

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `theftNotification.time` | 防盗通知时间 | `"1754654998"` | Unix 秒（推测） | 字段直译／缩写推测；枚举未核实 | 2025-08-08 20:09:58 北京时间（按量级换算）；不证明当前发生防盗事件。 | 本次接口返回＋字段命名 |
| `theftNotification.activated` | 防盗通知激活状态 | `"3"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：configuration

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `configuration.propulsionType` | 动力配置编码 | `"4"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `configuration.fuelType` | 能源配置编码 | `"4"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `configuration.vin` | 车辆识别代号（VIN） | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：根字段

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `updateTime` | 整车缓存状态更新时间 | `"1789704722583"` | Unix 毫秒 | 字段直译／缩写推测；枚举未核实 | 2026-09-18 12:12:02 北京时间；整车时间不保证所有子字段同步。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.maintenanceStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.maintenanceStatus.daysToService` | 保养剩余天数指标 | `"330"` | 天（社区） | 社区术语／单位；本车统计口径待核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | S1（社区实现，非官方协议） |
| `additionalVehicleStatus.maintenanceStatus.engineHrsToService` | 保养运行小时指标 | `"0"` | h（推测） | 字段直译／缩写推测；枚举未核实 | 通用平台兼容字段；纯电车上的零值不代表存在对应燃油部件或有效测量。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.odometer` | 总里程 | `"44681.000"` | km | 已返回 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：44681 km。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.brakeFluidLevelStatus` | 制动液液位状态 | `"3"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.tyreTempDriverRear` | 左后胎温 | `"34.000"` | °C | 本车已核对 | 轮位按本车左舵布局。 本次展示解释：34°C。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.maintenanceStatus.mainBatteryStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.stateOfCharge` | 低压辅助电池荷电状态码 | `"1"` | — | 字段直译／缩写推测；枚举未核实 | 属于低压辅助电池；不是动力电池 SOH。0 不证明电池健康度为 0%。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.chargeLevel` | 低压辅助电池电量 | `"98.7"` | %（社区） | 字段直译／缩写推测；枚举未核实 | 属于低压辅助电池；不是动力电池 SOH。0 不证明电池健康度为 0%。 | 本次接口＋S1 |
| `additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.energyLevel` | 低压辅助电池能量等级 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 属于低压辅助电池；不是动力电池 SOH。0 不证明电池健康度为 0%。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.stateOfHealth` | 低压辅助电池健康状态指标 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 属于低压辅助电池；不是动力电池 SOH。0 不证明电池健康度为 0%。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.powerLevel` | 低压辅助电池功率等级 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 属于低压辅助电池；不是动力电池 SOH。0 不证明电池健康度为 0%。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.voltage` | 低压辅助电池电压 | `"13.150"` | V | 字段直译／缩写推测；枚举未核实 | 属于低压辅助电池；不是动力电池 SOH。0 不证明电池健康度为 0%。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.maintenanceStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.maintenanceStatus.tyreTempDriver` | 左前胎温 | `"34.000"` | °C | 本车已核对 | 轮位按本车左舵布局。 本次展示解释：34°C。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.tyreTempPassengerRear` | 右后胎温 | `"33.000"` | °C | 本车已核对 | 轮位按本车左舵布局。 本次展示解释：33°C。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.distanceToService` | 保养剩余里程指标 | `"18455"` | km（社区） | 社区术语／单位；本车统计口径待核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | S1（社区实现，非官方协议） |
| `additionalVehicleStatus.maintenanceStatus.tyreStatusPassengerRear` | 右后胎压 | `"282.838"` | kPa | 本车已核对 | 原值÷100 得 bar；轮位按本车左舵布局。 本次展示解释：282.838 kPa。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.tyreStatusPassenger` | 右前胎压 | `"281.465"` | kPa | 本车已核对 | 原值÷100 得 bar；轮位按本车左舵布局。 本次展示解释：281.465 kPa。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.tyreStatusDriverRear` | 左后胎压 | `"284.211"` | kPa | 本车已核对 | 原值÷100 得 bar；轮位按本车左舵布局。 本次展示解释：284.211 kPa。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.serviceWarningStatus` | 保养提醒状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.tyreStatusDriver` | 左前胎压 | `"281.465"` | kPa | 本车已核对 | 原值÷100 得 bar；轮位按本车左舵布局。 本次展示解释：281.465 kPa。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.tyreTempPassenger` | 右前胎温 | `"33.000"` | °C | 本车已核对 | 轮位按本车左舵布局。 本次展示解释：33°C。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.maintenanceStatus.washerFluidLevelStatus` | 玻璃水液位状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.electricVehicleStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.electricVehicleStatus.disChargeUAct` | 放电电压 | `"0.0"` | V | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.disChargeSts` | 对外放电状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.chargeLidAcStatus` | 交流慢充口盖 | `"2"` | — | 本车场景观察 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.distanceToEmptyOnBatteryOnly` | 电池续航 | `"417"` | km | 已返回 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：417 km。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.chargeSts` | 充电状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 本车直流快充样本中也可为 0；不能单独据此判定未充电／未插枪。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.averPowerConsumption` | 平均电耗 | `"18.6"` | kWh/100 km（社区） | 社区术语／单位；本车统计口径待核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | S1（社区实现，非官方协议） |
| `additionalVehicleStatus.electricVehicleStatus.chargerState` | 充电器工作状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.timeToTargetDisCharged` | 放电剩余时间 | `"2047"` | 分钟（放电项待核实）；2047 为无有效估计候选 | 社区解释 | 2047 按项目现有规则视为无有效估计；不能显示为 2047 分钟。放电字段分钟单位尚未实车核实。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.disChargeConnectStatus` | 放电连接状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.chargeLidDcAcStatus` | 直流快充口盖 | `"2"` | — | 本车场景观察 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.dcChargeSts` | 直流充电状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.ptReady` | 动力系统就绪状态（PT Ready） | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.chargeLevel` | 动力电池荷电量（SOC） | `"86"` | % | 已返回 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：86%。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.statusOfChargerConnection` | 充电枪连接状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 本车直流快充样本中也可为 0；不能单独据此判定未充电／未插枪。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.dcDcActvd` | DC/DC 激活状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.indPowerConsumption` | 瞬时电能消耗指标（功率或电耗待核实） | `"0"` | 未知，不能直接写 kW | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.hvTempLevel` | 高压系统温度等级（对象待核实） | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.dcDcConnectStatus` | DC/DC 连接状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.disChargeIAct` | 放电电流 | `"0.0"` | A | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.dcChargeIAct` | 直流充电电流 | `"0.0"` | A | 字段直译／缩写推测；枚举未核实 | 快充样本曾为负值，可能采用流入为负的符号约定；不可直接当成对外放电。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.chargeUAct` | 充电电压 | `"0.0"` | V | 字段直译／缩写推测；枚举未核实 | 本车直流快充样本中也可为 0；不能单独据此判定未充电／未插枪。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.bookChargeSts` | 预约充电状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.dcChargePileIAct` | 桩侧电流 | `"0.0"` | A | 本车已核对 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：0 A。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.chargeIAct` | 充电电流 | `"0.000"` | A | 字段直译／缩写推测；枚举未核实 | 本车直流快充样本中也可为 0；不能单独据此判定未充电／未插枪。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.timeToFullyCharged` | 预计充电剩余时间 | `"2047"` | 分钟（放电项待核实）；2047 为无有效估计候选 | 社区解释 | 2047 按项目现有规则视为无有效估计；不能显示为 2047 分钟。放电字段分钟单位尚未实车核实。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.electricVehicleStatus.dcChargePileUAct` | 桩侧电压 | `"397.2"` | V | 本车已核对 | 本车快充时已核对为 V；非零可能为保留读数，不能单独证明仍在充电。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.chargeHvSts` | 高压充电相关状态 | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.drivingBehaviourStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.drivingBehaviourStatus.gearAutoStatus` | 自动挡位状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingBehaviourStatus.gearManualStatus` | 手动挡位状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingBehaviourStatus.engineSpeed` | 转速字段 | `"0.000"` | r/min（通用；非已验证电机转速） | 字段直译／缩写推测；枚举未核实 | 燃油车兼容字段；未证明能读取本车驱动电机转速。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.runningStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.runningStatus.ahbc` | 自动远光控制（推测） | `"1"` | — | 术语映射推测；极氪字段未证实 | 不能从当前 0/1 判定功能关闭/开启、装备情况或故障。 | S4，仅支持通用功能术语 |
| `additionalVehicleStatus.runningStatus.goodbye` | 告别照明 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.homeSafe` | 伴我回家 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.cornrgLi` | 转角辅助照明（推测） | `"0"` | — | 术语映射推测；极氪字段未证实 | 不能从当前 0/1 判定功能关闭/开启、装备情况或故障。 | S3，仅支持通用功能术语 |
| `additionalVehicleStatus.runningStatus.frntFog` | 前雾灯 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.stopLi` | 刹车灯 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.tripMeter1` | 小计里程 1 | `"6172.4"` | km（推测） | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.approach` | 接近照明 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.tripMeter2` | 小计里程 2 | `"9.6"` | km（推测） | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.indFuelConsumption` | 瞬时油耗通用字段 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 通用平台兼容字段；纯电车上的零值不代表存在对应燃油部件或有效测量。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.hiBeam` | 远光灯 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.engineCoolantLevelStatus` | 冷却液通用字段 | `"3"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.fuelEnLevel` | 燃油能量等级 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 通用平台兼容字段；纯电车上的零值不代表存在对应燃油部件或有效测量。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.loBeam` | 近光灯 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.ltgShow` | 灯光秀 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.welcome` | 迎宾灯 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.drl` | 日行灯 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.fuelLevelPct` | 燃油比例通用字段 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 通用平台兼容字段；纯电车上的零值不代表存在对应燃油部件或有效测量。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.ahl` | 自动大灯调平／自适应前照灯（两种候选） | `"0"` | — | 术语映射推测；极氪字段未证实 | 不能从当前 0/1 判定功能关闭/开启、装备情况或故障。 | 字段缩写存在歧义，无直接协议证据 |
| `additionalVehicleStatus.runningStatus.fuelEnCns` | 燃油消耗通用字段 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 通用平台兼容字段；纯电车上的零值不代表存在对应燃油部件或有效测量。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.trunIndrLe` | 左转向灯 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.trunIndrRi` | 右转向灯 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.afs` | 自适应前照灯系统（推测） | `"0"` | — | 术语映射推测；极氪字段未证实 | 不能从当前 0/1 判定功能关闭/开启、装备情况或故障。 | S2，仅支持通用功能术语 |
| `additionalVehicleStatus.runningStatus.dbl` | 动态弯道照明／随动转向照明（推测） | `"0"` | — | 术语映射推测；极氪字段未证实 | 不能从当前 0/1 判定功能关闭/开启、装备情况或故障。 | S3，仅支持通用功能术语 |
| `additionalVehicleStatus.runningStatus.avgSpeed` | 平均速度指标 | `"26"` | km/h（推测；统计窗口未知） | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.reverseLi` | 倒车灯 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.hwl` | 高速公路照明模式（推测） | `"0"` | — | 术语映射推测；极氪字段未证实 | 不能从当前 0/1 判定功能关闭/开启、装备情况或故障。 | S2，仅支持通用功能术语 |
| `additionalVehicleStatus.runningStatus.reFog` | 后雾灯 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.flash` | 闪灯字段 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.runningStatus.fuelEnCnsFild` | 燃油消耗扩展字段 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 通用平台兼容字段；纯电车上的零值不代表存在对应燃油部件或有效测量。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.trailerStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.trailerStatus.trailerTurningLampSts` | 挂车转向灯状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.trailerStatus.trailerFogLampSts` | 挂车雾灯状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.trailerStatus.trailerBreakLampSts` | 挂车制动灯状态（原字段拼作 Break） | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.trailerStatus.trailerReversingLampSts` | 挂车倒车灯状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.trailerStatus.trailerPosLampSts` | 挂车位置灯状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.climateStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.climateStatus.drvHeatSts` | 主驾加热状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.temperatureUpdateTime` | 温度更新时间 | `"1789704722583"` | Unix 毫秒 | 已返回 | 2026-09-18 12:12:02 北京时间；整车时间不保证所有子字段同步。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.winPosDriver` | 左前车窗位置 | `"0"` | — | 本车已核对 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.rrVentDetail` | 右后通风档位／细分状态（推测） | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 可能是档位或细分状态；不能将 2 直接解释为二挡。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.cabinTempReductionStatus` | 座舱降温状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.rlVentSts` | 左后通风状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.passVentSts` | 副驾通风状态 | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.interiorTemp` | 车内温度 | `"27.7"` | °C | 已返回 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：27.7°C。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.passVentDetail` | 副驾通风档位／细分状态（推测） | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 可能是档位或细分状态；不能将 2 直接解释为二挡。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.sunroofPos` | 天窗位置 | `"101"` | — | 字段直译／缩写推测；枚举未核实 | 101 超出普通 0–100% 范围，疑为无效／未配置哨兵；未证实，不解释为 101% 开度。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.cdsClimateActive` | CDS 空调激活标记（CDS 含义未知） | `"false"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.sunroofOpenStatus` | 天窗状态 | `"1"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.rrHeatingDetail` | 右后加热档位／细分状态（推测） | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 可能是档位或细分状态；不能将 2 直接解释为二挡。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.winStatusPassenger` | 右前车窗状态 | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.fragActive` | 香氛激活标记（推测） | `false` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.winStatusDriver` | 左前车窗状态 | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.drvVentSts` | 主驾通风状态 | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.winStatusPassengerRear` | 右后车窗状态 | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.sunCurtainRearOpenStatus` | 后遮阳帘状态 | `"1"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.preClimateActive` | 预调温标记 | `false` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.rlHeatingDetail` | 左后加热档位／细分状态（推测） | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 可能是档位或细分状态；不能将 2 直接解释为二挡。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.winPosPassengerRear` | 右后车窗位置 | `"0"` | — | 本车已核对 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.curtainPos` | 遮阳帘位置 | `"101"` | — | 字段直译／缩写推测；枚举未核实 | 101 超出普通 0–100% 范围，疑为无效／未配置哨兵；未证实，不解释为 101% 开度。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.rlVentDetail` | 左后通风档位／细分状态（推测） | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 可能是档位或细分状态；不能将 2 直接解释为二挡。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.curtainOpenStatus` | 遮阳帘状态 | `"1"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.climateOverHeatProActive` | 过热保护相关标记 | `"true"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.rrVentSts` | 右后通风状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.rrHeatingSts` | 右后加热状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.winPosPassenger` | 右前车窗位置 | `"0"` | — | 本车已核对 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.steerWhlHeatingSts` | 方向盘加热 | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.drvVentDetail` | 主驾通风档位／细分状态（推测） | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 可能是档位或细分状态；不能将 2 直接解释为二挡。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.winPosDriverRear` | 左后车窗位置 | `"0"` | — | 本车已核对 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.exteriorTemp` | 车外温度 | `"31.0"` | °C | 已返回 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：31°C。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.rlHeatingSts` | 左后加热状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.winStatusDriverRear` | 左后车窗状态 | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.defrost` | 除霜标记 | `"false"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.drvHeatDetail` | 主驾加热档位／细分状态（推测） | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 可能是档位或细分状态；不能将 2 直接解释为二挡。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.passHeatingDetail` | 副驾加热档位／细分状态（推测） | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 可能是档位或细分状态；不能将 2 直接解释为二挡。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.airBlowerActive` | 鼓风机标记 | `"false"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.sunCurtainRearPos` | 后遮阳帘位置 | `"101"` | — | 字段直译／缩写推测；枚举未核实 | 101 超出普通 0–100% 范围，疑为无效／未配置哨兵；未证实，不解释为 101% 开度。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.climateStatus.passHeatingSts` | 副驾加热状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.drivingSafetyStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.drivingSafetyStatus.doorLockStatusDriverRear` | 左后门锁 | `"1"` | — | 本车已核对（组合） | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：已锁。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.srsCrashStatus` | 碰撞系统状态 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.doorOpenStatusPassengerRear` | 右后车门开闭 | `"0"` | — | 本车已核对 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.doorPosPassengerRear` | 右后车门位置 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.doorOpenStatusDriver` | 左前车门开闭 | `"0"` | — | 本车已核对 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.seatBeltStatusPassenger` | 右前安全带标记 | `"false"` | — | 字段直译／缩写推测；枚举未核实 | 布尔标记方向及座位占用条件未核实；第三排字段不代表本车具有第三排座椅。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.doorPosDriver` | 左前车门位置 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.seatBeltStatusThPassengerRear` | 第三排右侧通用安全带标记 | `"false"` | — | 字段直译／缩写推测；枚举未核实 | 布尔标记方向及座位占用条件未核实；第三排字段不代表本车具有第三排座椅。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.electricParkBrakeStatus` | 电子驻车 | `"1"` | — | 本车场景观察 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：停车／充电样本值 1。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.doorLockStatusDriver` | 左前门锁 | `"1"` | — | 本车已核对（组合） | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：已锁。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.seatBeltStatusThDriverRear` | 第三排左侧通用安全带标记 | `"false"` | — | 字段直译／缩写推测；枚举未核实 | 布尔标记方向及座位占用条件未核实；第三排字段不代表本车具有第三排座椅。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.tankFlapStatus` | 油箱盖通用字段 | `"2"` | — | 字段直译／缩写推测；枚举未核实 | 通用平台兼容字段；纯电车上的零值不代表存在对应燃油部件或有效测量。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.seatBeltStatusPassengerRear` | 右后安全带标记 | `"false"` | — | 字段直译／缩写推测；枚举未核实 | 布尔标记方向及座位占用条件未核实；第三排字段不代表本车具有第三排座椅。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.doorOpenStatusPassenger` | 右前车门开闭 | `"0"` | — | 本车已核对 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.doorPosPassenger` | 右前车门位置 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.drivingSafetyStatus.vehicleAlarm

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.drivingSafetyStatus.vehicleAlarm.alrmSt` | 报警状态 | `"1"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.vehicleAlarm.alrmTrgSrc` | 报警来源 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.drivingSafetyStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.drivingSafetyStatus.doorPosDriverRear` | 左后车门位置 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.centralLockingStatus` | 中控锁 | `"2"` | — | 本车已核对（组合） | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：已锁车。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.seatBeltStatusDriver` | 左前安全带标记 | `"false"` | — | 字段直译／缩写推测；枚举未核实 | 布尔标记方向及座位占用条件未核实；第三排字段不代表本车具有第三排座椅。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.doorLockStatusPassenger` | 右前门锁 | `"1"` | — | 本车已核对（组合） | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：已锁。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.seatBeltStatusMidRear` | 后排中间安全带标记 | `"true"` | — | 字段直译／缩写推测；枚举未核实 | 布尔标记方向及座位占用条件未核实；第三排字段不代表本车具有第三排座椅。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.trunkLockStatus` | 尾门锁 | `"1"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.seatBeltStatusDriverRear` | 左后安全带标记 | `"false"` | — | 字段直译／缩写推测；枚举未核实 | 布尔标记方向及座位占用条件未核实；第三排字段不代表本车具有第三排座椅。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.engineHoodOpenStatus` | 前舱盖 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.doorOpenStatusDriverRear` | 左后车门开闭 | `"0"` | — | 本车已核对 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.doorLockStatusPassengerRear` | 右后门锁 | `"1"` | — | 本车已核对（组合） | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：已锁。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.drivingSafetyStatus.trunkOpenStatus` | 尾门开闭 | `"0"` | — | 本车已核对 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 本次展示解释：关闭。 | 本次接口返回＋字段命名 |

## 状态：additionalVehicleStatus.pollutionStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `additionalVehicleStatus.pollutionStatus.interiorPM25` | 车内 PM2.5 指标 | `"29"` | μg/m³（推测） | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.pollutionStatus.interiorPM25Level` | 车内 PM2.5 等级 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.pollutionStatus.relHumSts` | 相对湿度指标（推测） | `"48"` | %RH（推测） | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |
| `additionalVehicleStatus.pollutionStatus.exteriorPM25Level` | 车外 PM2.5 等级 | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 | 本次接口返回＋字段命名 |

## 状态：temStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `temStatus.swVersion` | 车载通信模块软件版本 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.serialNumber` | 通信模块序列号 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.powerSource` | 通信模块供电来源 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |

## 状态：temStatus.networkAccessStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `temStatus.networkAccessStatus.mobileNetwork` | 移动网络信息 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |

## 状态：temStatus.networkAccessStatus.simInfo

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `temStatus.networkAccessStatus.simInfo.iccId` | SIM 卡集成电路卡识别码（ICCID） | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.networkAccessStatus.simInfo.imsi` | 国际移动用户识别码（IMSI） | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.networkAccessStatus.simInfo.msisdn` | 移动用户号码（MSISDN） | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |

## 状态：temStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `temStatus.mcuVersion` | 微控制器固件版本 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.mpuVersion` | 微处理器软件版本 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |

## 状态：temStatus.backupBattery

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `temStatus.backupBattery.stateOfCharge` | 通信模块备用电池荷电状态 | `null` | — | 字段直译／缩写推测；枚举未核实 | 属于通信模块备用电池，不能与低压辅助电池或动力电池混用。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.backupBattery.stateOfHealth` | 通信模块备用电池健康状态 | `null` | — | 字段直译／缩写推测；枚举未核实 | 属于通信模块备用电池，不能与低压辅助电池或动力电池混用。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.backupBattery.voltage` | 通信模块备用电池电压 | `null` | V | 字段直译／缩写推测；枚举未核实 | 属于通信模块备用电池，不能与低压辅助电池或动力电池混用。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |

## 状态：temStatus

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `temStatus.hwVersion` | 通信模块硬件版本 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.powerMode` | 通信模块电源模式 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.healthStatus` | 通信模块健康状态 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.sleepCycleNextWakeupTime` | 休眠周期下次唤醒时间 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.imei` | 移动设备识别码（IMEI） | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.state` | 通信模块运行状态 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |
| `temStatus.connectivityStatus` | 通信模块连接状态 | `null` | — | 字段直译／缩写推测；枚举未核实 | 数值码不直接等于开／关；字段存在不代表本车装配该功能。 当前 null，未提供有效值。 | 本次接口返回＋字段命名 |

## 档案：根字段

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `factoryCode` | 工厂代码 | `""` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 当前为空字符串。 | 本次接口返回＋字段命名 |
| `colorName` | 车身颜色名称 | `""` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 当前为空字符串。 | 本次接口返回＋字段命名 |
| `isIHUConfirm` | 车机确认标记（推测） | `false` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `temId` | 车载通信模块标识 | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `ihuPlatform` | 车机平台 | `""` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 当前为空字符串。 | 本次接口返回＋字段命名 |
| `ihuId` | 车机标识 | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `carProveStatus` | 车辆认证状态（推测） | `"N"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `fuelTankCapacity` | 油箱容量（通用字段） | `"0"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `seriesCodeVs` | 车系版本编码（推测） | `"DC1E"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `iccid` | SIM 卡识别码 | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `current` | 当前车辆标记（推测） | `false` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `modelCode` | 车型编码 | `"DC1E-006"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `vehicleOwnerLastTime` | 车主关联时间字段（具体业务未知） | `"[hidden]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `vin` | 车辆识别代号（VIN） | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `fccode` | 内部配置／车型代码（推测） | `""` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 当前为空字符串。 | 本次接口返回＋字段命名 |
| `id` | 车辆记录标识 | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `msisdn` | 移动用户号码（MSISDN） | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `vehicleType` | 车辆类型编码 | `0` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `engineNo` | 发动机／动力总成编号（通用字段） | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `temType` | 车载通信模块类型 | `""` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 当前为空字符串。 | 本次接口返回＋字段命名 |
| `tboxPlatform` | T-Box 平台 | `"tsp"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `plateNo` | 车牌号码 | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `seriesName` | 车系名称／内部车系代号 | `"DC1E"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `updateTime` | 整车缓存状态更新时间 | `"1711639479458"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `vehiclePhotoSmall` | 车辆缩略图地址 | `""` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 当前为空字符串。 | 本次接口返回＋字段命名 |
| `modelName` | 车型名称／内部配置名称 | `"WE版-006"` | — | 字段直译／缩写推测；枚举未核实 | 接口内部车型名称，不能单凭此项确定完整年款、驱动形式或电池容量。 | 本次接口返回＋字段命名 |
| `proprietaryPlatform` | 所属平台编码（推测） | `1` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `recordTime` | 档案记录时间 | `"1695103292350"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `createTime` | 档案创建时间 | `"1695103292350"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `simActivited` | 车载 SIM 激活标记 | `1` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `vehiclePhotoBig` | 车辆大图地址 | `""` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 当前为空字符串。 | 本次接口返回＋字段命名 |

## 档案：loginInfo

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `loginInfo.isLogined` | 车机账号登录标记（推测） | `0` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `loginInfo.loginUid` | 登录用户标识 | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |

## 档案：根字段

| 完整字段路径 | 中文术语 | 当前原值 | 单位 | 解释依据 | 说明 | 来源 |
|---|---|---|---|---|---|---|
| `colorCode` | 车身颜色编码 | `""` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 当前为空字符串。 | 本次接口返回＋字段命名 |
| `defaultVehicle` | 默认车辆标记 | `false` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `matCode` | 物料／配置编码（推测） | `"[已隐藏]"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
| `shareStatus` | 车辆分享状态 | `"Y"` | — | 字段直译／缩写推测；枚举未核实 | 车辆档案返回项；编码或布尔标记的业务枚举未独立核实。 | 本次接口返回＋字段命名 |
