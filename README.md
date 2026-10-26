# Zeekr Control

面向中国区极氪车辆的**只读数据仪表盘与命令行工具**。把车辆云端状态、行程、充电和费用整理成可回顾的用车记录，支持图形化周月报、地点与标签管理，以及 Bark／企业微信通知。

项目目前在 Mac mini 上以 **launchd + Tailscale Serve HTTPS** 常驻运行，面向桌面浏览器。Python 运行期使用标准库，兼容 Python 3.9.6；浏览器测试另用 npm 锁定依赖。

已在一个老款 001 副账号上验证短信登录、分享车辆列表及 GW2 状态读取。其他车型和账号需单独核验。项目不提供远程车控；云端缓存可能延迟，不能当作实时车辆状态。

## 能做什么

| 功能 | 内容 |
| --- | --- |
| 车辆总览 | 电量、预估续航、门锁门窗、最近活动、行程和充电；已知与未知状态分别展示 |
| 行程与轨迹 | 自动记录行程、已观测里程和电量变化；查看出行链、停车观测、常走路线和轨迹缺口，地图按需加载 |
| 能源与充电 | AC／DC 充电记录、单次曲线、充电回顾、两次充电间的电耗与参考电费；保留测量、估算和缺失的区别 |
| 用车账本 | 充电费用、停车费、日常支出和保养待办；支持补账、编辑、删除恢复，分类环图可切换明细 |
| 用车日历与周月报 | 按日期回看用车记录；图形化对比上个周期，突出里程、耗电、充电与实付费用的变化 |
| 地点与标签 | 人工校正地点、管理区域、逐趟备注与标签；自动标注规则支持预览影响和排除单趟 |
| 自动通知 | Bark 发送状态与异常提醒；企业微信发送分段行程／充电报告、路线图片及启用的周期报告 |
| 参数核实 | 字段字典、原值与参考依据、人工核实记录；待确认含义不直接升级为已验证能力 |
| 连接与运维 | 副账号短信重连、可选 macOS 钥匙串续期、独立网页登录、采样设置、存储管理及服务巡检 |

更细的页面和操作说明见 [Web 使用说明](docs/web-usage.md)，产品范围见 [当前产品约定](PRODUCT.md)。当前只维护、验证桌面界面。

## 运行方式

| 方式 | 适用场景 | 入口与数据 |
| --- | --- | --- |
| Mac mini 常驻服务 | 日常采集、通知和私网访问 | launchd 管理服务；本机端口 `18765`，远程走自己的 Tailscale HTTPS 域名；使用独立 `state/` |
| 本机 CLI／开发模式 | 试用、调试、离线验证 | `python3 -m zeekr_control …`；临时网页默认端口 `8765`，数据默认在当前用户的 `ZeekrControl` 目录 |
| Linux 部署模板 | 其他服务器环境 | 保留 systemd／Nginx 配置，见 [Linux 部署说明](docs/server-deployment.md)；不要在 Mac mini 上套用 |

开发模式与常驻服务的 HOME、会话和数据库可能不同。在开发终端登录成功，不代表常驻服务已连接；已有实例应使用它自己的管理入口和数据目录。

## Mac mini 常驻部署

当前部署方式使用登录用户的 LaunchAgents，分别负责网页、采集与通知、周期报告、服务巡检：

| 任务 | 职责 |
| --- | --- |
| `local.zeekr.web` | 桌面 Web 与网页认证 |
| `local.zeekr.monitor` | 车辆采集、事件记录与通知投递 |
| `local.zeekr.reports` | 独立调度周期报告 |
| `local.zeekr.resources` | 极氪服务可用性与资源状态巡检 |

### 目录

```text
~/Library/Application Support/ZeekrServer/
├── current -> releases/<版本>/
├── releases/     # 当前与保留的历史代码版本
├── state/        # 服务 HOME、账号配置及业务数据库
├── logs/         # 后台任务日志
└── backups/      # 发布前停服备份
```

应用数据实际位于 `state/Library/Application Support/ZeekrControl/`，网页认证配置位于 `state/web-auth.json`；LaunchAgent 配置在 `~/Library/LaunchAgents/`。

代码、账号、数据库、日志与备份留在内置盘。管理快捷入口可另放外置盘，它不是服务的运行目录；Git 工作树也不等于 `current`。

### 访问与管理

已有实例在项目目录运行以下只读检查，可看到当前版本、任务状态和实际访问地址：

```bash
python3 scripts/release/client.py macos inspect
```

- 本机打开 `http://127.0.0.1:18765/`，或双击仓库根目录的 `启动极氪网页.command`。
- 其他设备先连接同一 Tailscale 网络，再访问本实例配置的 HTTPS 域名。个人服务使用私有 Serve，不启用公网 Funnel。
- 网页密码与车辆副账号是两套登录。更改网页密码使用本机交互入口 `scripts/change-web-password.command`。
- 状态、健康检查、日志、启停、备份与回退入口见 [管理工具说明](scripts/macos-management/使用说明.md)。

首次搭建需配置运行目录、LaunchAgents、网页认证和 Tailscale Serve；固定发布工具以已有部署为基础，不是一键安装器。完整流程见 [macOS 开发与发布](docs/macos-development.md)。

LaunchAgents 在**用户登录后**启动。机器关机、休眠、登录钥匙串未解锁或网络不可用，都可能影响采集；不能把“已配置自启”当作登录前也可用。

### 连接车辆与自动续期

使用已接受车辆分享的极氪副账号。手机号和短信验证码只在运行服务的 Mac mini 终端隐藏输入，不放聊天、日志或 Git。

选择 macOS 钥匙串方案时，在项目目录运行：

```bash
./scripts/connect-vehicle-keychain.command
```

该入口使用 `/usr/bin/python3`，写入常驻服务的实际会话目录。它完成登录与钥匙串读取检查；**不会仅凭登录就自动启用续期**。

refreshToken 仅存本机用户钥匙串，钥匙串不可用时不降级为明文；兼容读路径的 accessToken 仍保存在权限为 `600` 的会话文件。自动续期默认关闭，需受控真实刷新、目标车辆实际读取验证及明确启用；结果不确定的刷新不得自动重放。一次成功不保证永久有效。

`1509` 不直接等同永久失效或官方维护。系统先按策略退避探测，符合资格时再尝试续期；需人工处理时给出网关实际原因。接口恢复与车辆新状态出现分别记录，恢复后不补造中断样本。详情见 [钥匙串连接与续期](docs/macos-keychain-refresh.md)。

## 本机试用与开发

没有常驻实例时，可先在 Mac 终端试用：

```bash
git clone https://github.com/Ross98/Zeekr.git
cd Zeekr
python3 -m zeekr_control login
python3 -m zeekr_control vehicles
python3 -m zeekr_control status
python3 -m zeekr_control web
```

打开 `http://127.0.0.1:8765/`。临时网页默认仅监听回环地址；终端按 Ctrl+C 退出。不要把未配置网页认证的开发服务公开到网络。已有常驻实例不要再启动第二套生产采集。

常用命令：

```bash
python3 -m zeekr_control --help
python3 -m zeekr_control status --vehicle 1  # 多车按 vehicles 返回序号选择
python3 -m zeekr_control status --json       # 默认脱敏的状态
python3 -m zeekr_control monitor-status     # 当前数据目录的监控状态
python3 -m zeekr_control logout             # 删除活动会话，不删除历史数据库
```

`vehicles`、`status` 会涉及真实车辆接口，不能当作无副作用的离线测试。`logout` 不撤销云端令牌，也不物理擦除旧钥匙串项目、缓存或轨迹。新登录可能影响同一副账号的其他会话。

车型名称、图片、电池容量与标称续航按自己的车辆配置，模板见 `zeekr_control/vehicle_profiles.example.json`。个人 `vehicle_profiles.json` 已被 Git 忽略；缺少容量或参考续航时，不补造能耗和达成率。

## 数据与通知规则

### 采集与记录

- 默认每 30 秒检查车辆云端缓存，设置可改为 10–60 秒；停车、行驶、充电沿用所选间隔。页面读取本地状态，不因轮询额外请求车辆。
- CLI、Web 和后台共用数据目录内的跨进程查询保护。失败也计入间隔，HTTP 429 遵守共享冷却；更快查询不保证车辆更快上传。
- 分别保存车辆状态时间与本机读取时间。重复缓存不增加轨迹点，也不冒充中间时段有观测覆盖。
- 缺失、未知、异常值与真实零值分别处理。中断时优先保全已观测的里程、电量等行驶数据，轨迹允许断裂；未采集时段不会自动从厂商历史接口补齐。
- 充电停止不等于拔枪、充满或已知停止原因。SOC × 容量得到的 kWh 明确标估算，不当作充电桩计费电量。
- 实际费用只汇总已填金额，未知不按免费处理，估算不混入实付；按北京时间和对应日期口径统计，未来日期不提前计入实际总额。
- 地点校正不改原始 GPS，也不把不可信定位升级成可信定位。普通停车行程需下电后确认；连续可信状态确认原地开始充电时可提前结算到站行程。

### 通知分工

| 通道 | 内容与边界 |
| --- | --- |
| Bark | 行程、充电、车辆提醒、采集、服务、存储六类分组；1509 区分持续重试与需人工核对，不从代码猜维护原因 |
| 企业微信 | 行程／充电分段报告与路线图片；保留核心数据、有效停车状态、已确认异常、部分记录与估算说明；启用后发送周期图形报告 |
| 服务巡检 | 极氪任务、网页与巡检失效等服务异常；整机 CPU、RSS 和内存压力只展示，不触发极氪 Bark，所在磁盘的数据安全告警另有说明 |

整机告警若由独立 Server Monitor 负责，应使用独立配置、来源与分组；它不是本仓库四个后台任务之一。具体通道配置见 [自动监控说明](docs/monitor-usage.md)、[Bark 分组与文案](docs/bark-notification-layout.md)及 [服务巡检说明](docs/macos-resource-monitor.md)。

文字、Bark、图片与周期报告各自保存投递状态。图片准备失败不阻止文字；外部发送结果不确定时保留待确认，不自动重发。Bark 明确失败时，自定义提醒可由企业微信兜底；结果不确定时不兜底。服务端接收成功不等于手机实际展示。

暂停采集会停止新查询和常规通知领取；已开始的请求与发送仍保存结果，存储巡检继续。周期报告有独立开关。关闭浏览器不会停止常驻服务。

### 私有数据

本机 CLI 默认使用 `~/Library/Application Support/ZeekrControl/`；Mac mini 常驻服务使用上文的独立 `state/`。私有目录权限为 `700`，私有文件为 `600`。

| 文件 | 用途 |
| --- | --- |
| `session.json` | 兼容读会话及钥匙串引用；不存 refreshToken 明文 |
| `queries.sqlite3` | 查询缓存与共享冷却，可能含车辆身份及位置 |
| `tracks.sqlite3`、`snapshots.sqlite3` | 行程、轨迹、快照与归档 |
| `personal.sqlite3`、`field-reviews.sqlite3` | 账单、支出、标签、地点及参数核实 |
| `system-notifications.sqlite3`、`collection-incidents.sqlite3` | 采集告警投递、中断与恢复事件 |
| `periodic-reports.sqlite3` | 周期报告投递记录 |
| `wecom-webhook.json`、`bark.json`、`amap-geocoding.json` | 私有通知及可选地图配置 |

文件权限不是加密保险箱。仓库不存真实凭据、车型私有配置、实车快照和数据库；发布备份也不把钥匙串 Token 导出成普通文件。机器迁移或钥匙串丢失需按本机认证流程恢复。

地图和地址解析为可选功能，使用前需配置对应服务；开启后会向地图服务请求相应区域或位置数据。见 [隐私边界](docs/privacy.md)与 [第三方资源声明](THIRD_PARTY_NOTICES.md)。

## 更新与回退

Git 提交、push、合并与运行版本是不同状态。更新源码不会自动发布；改 Python 后端需经固定流程切换并重启相应服务。

1. 提交指定文件并 push，核对最终 SHA 的 CI。
2. 使用 `scripts/release/client.py macos prepare` 构建生产匹配候选。
3. `macos stage` 完成候选检查；后端和发布工具改动由实际服务用户运行全量。
4. `macos deploy` 取得发布锁，重查门禁，停服备份、原子切换并验收；失败按既定流程回退代码。

回退保留最新业务数据，不用旧备份覆盖后续行程、账单或发送记录。备份含私有数据，需受限保存；保留上一版本作为回退目标。详细命令、路径列表和验证边界见 [固定发布流程](docs/release-workflow.md)与 [macOS 开发与发布](docs/macos-development.md)。

## 故障处理

| 现象 | 先检查 |
| --- | --- |
| 网页提示“请先登录” | 网页访问会话；它与极氪副账号认证独立 |
| `1509`、采集暂缓 | 网关实际说明、退避与续期状态、中断事件；需要人工认证时在服务机器重连，不反复登录或刷新 |
| 请求成功但车辆时间没变 | 车辆是否仍返回同一云端缓存；不据此声称拿到新状态 |
| 行程／里程不完整 | 采集覆盖、已观测端点与服务运行时间；已有缺口不补造 |
| HTTP 429 | 等待共享冷却，不连续刷新绕过限制 |
| 存储告警与系统显示不同 | 区分 macOS 估算可用空间、文件系统即时空闲，以及极氪目录自身占用 |
| 轨迹或路线图缺失 | 是否开启地图、是否有可信采样、地图配置与图片独立投递状态 |
| 重启后无服务 | 用户是否已登录、LaunchAgents 是否加载、钥匙串和 Tailscale 是否可用 |

已有 Mac mini 实例先用“查看状态／健康检查”，不要另开第二套采集进程。日志、原始状态和通知历史可能含私有位置；分享前检查 Token、VIN、手机号和坐标。

## 开发与 CI

浏览器依赖仅用于开发测试，不是 Python 服务的运行依赖：

```bash
npm ci
npm run browser:install
npm run check:desktop-manifest
npm run check:js
npm run test:unit
npm run test:desktop
```

测试使用合成账号和临时数据库，不请求真实车辆、不发送真实通知。只维护桌面覆盖；按改动选择相关检查，发布时验证最终候选，见 [开发验证](docs/development.md)。

GitHub 保留四项必要检查：`Python tests`、`Desktop tests`、`macOS native tests`、`Workflow checks`。桌面浏览器文件分两片并行，汇总门禁逐项核对当前 SHA／run／attempt 与完整覆盖。GitHub 查询临时失败可有限重试；CI 未绿、任务缺失或持续不可读仍阻止发布，不寻找旧绿灯。

## 界面样例

以下为隔离合成数据的桌面截图，不含实车账号、轨迹或账目；布局以当前运行版本为准。更多样例与重拍方法见 [截图说明](docs/images/README.md)。

![行程与轨迹：连续出行链与出行节奏，合成数据](docs/images/local-trips.png)

![能源与充电：月度回顾与费用分析，合成数据](docs/images/charging-review.png)

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [产品约定](PRODUCT.md)／[实现入口](DESIGN.md) | 桌面范围、费用与数据口径、架构 |
| [Web 使用说明](docs/web-usage.md) | 页面、账本、地点、采样与报告 |
| [macOS 开发与发布](docs/macos-development.md) | Mac mini 布局、访问、候选与切换 |
| [管理工具](scripts/macos-management/使用说明.md) | 日常状态、健康检查、启停与回退 |
| [钥匙串与续期](docs/macos-keychain-refresh.md) | 会话存储、真实验证与禁重放规则 |
| [固定发布流程](docs/release-workflow.md)／[开发验证](docs/development.md) | 测试、CI、备份与发布门禁 |
| [监控配置](docs/monitor-usage.md)／[Bark 通知](docs/bark-notification-layout.md) | 通知配置、通道分工与状态保护 |
| [服务巡检](docs/macos-resource-monitor.md) | 极氪服务监控与整机指标边界 |
| [参数字典](docs/vehicle-parameter-dictionary-2026-09-18.md) | 字段、单位、依据与适用范围 |
| [隐私边界](docs/privacy.md)／[第三方声明](THIRD_PARTY_NOTICES.md) | 私有数据与外部资源 |
| [Linux 部署](docs/server-deployment.md)／[API 调研](docs/api-notes.md) | 其他部署模板与协议来源 |
