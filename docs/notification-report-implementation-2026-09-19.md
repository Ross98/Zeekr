# 详细通知报告实施与离线验收

基线：`1fad4c6`。范围严格取自 `notification-report-design-2026-09-19/`。本次只改本地代码、文档和合成测试；没有请求真实车辆、发送企业微信、部署、提交或 push。

## 已实施

- P0：`monitoring` 顶层和事件均用显式公共字段；私有 `summary/message/report_v2/signals/地址/坐标/车辆标识` 不进入 Web 状态。无认证、未选择车辆时公共事件为空；`EventStore` 继续按当前车辆和原白名单输出。
- P1：新增 `report_v2`、版本化规范字段、`report_observations` 和 `report_metric_index`。迁移只加表/索引。v1 完成事件不回填；v1 活动会话标记中途升级；未来未知报告版本不套 v1 模板或自动发送。
- P2：三类中文模板、地址一次解析、正文事务冻结、SHA-256、UTF-8 实测预算、语义块降级及离线 `report-preview` 已实现。重试逐字节复用正文。
- P3：行程端点冻结；停车后快照、已知变化、陈旧标记；距离、时长、SOC/续航、容量估算、百公里估算、额定续航达成率、平均/采样最高速度、温度和固定轮位胎压胎温已实现。
- P4：同侧同观测直流 U/I 功率、时间加权均值、峰值、功率与活动时间覆盖、末段停止不外推、前后 20% 降速门槛已实现。
- P5：同车、同 kind、90 天、最多 500 候选、最近 20、至少 5、版本/完整性筛选及中位数比较已实现并在结算时冻结。未核验未锁/打开编码不会产生提醒；未知、普通状态和停车变化分开。
- P6：能力登记存在；目标 SOC、枪连接、停止原因、动力电池温度、未锁/打开等保持 `pending_evidence`。自由文本注释不参与解码。
- P7：升级、正文冻结、未知版本、公共出口、消息长度、离线预览、既有状态机和发送退避均有合成回归。

## 合成预览

| 场景 | fixture | UTF-8 字节 |
|---|---|---:|
| 正常行程 | `tests/fixtures/report-trip-normal.json` | 665 |
| 中途开始充电 | `tests/fixtures/report-charge-start-partial.json` | 767 |
| 完整充电停止 | `tests/fixtures/report-charge-end-full.json` | 736 |
| 旧缓存停车状态 | `tests/fixtures/report-trip-old-cache.json` | 622 |
| 强制低预算降级 | 正常行程，`--target-bytes 400` | 306 |

运行示例：

```sh
python3 -m zeekr_control report-preview --fixture tests/fixtures/report-trip-normal.json
python3 -m zeekr_control report-preview --fixture tests/fixtures/report-trip-normal.json --target-bytes 400
```

该命令不创建车辆客户端、不读取 Webhook、不调用发送器。

## 验收证据映射

- B01–B06、T01–T05、C07：`tests/test_monitor.py` 的停车确认、端点冻结、短停恢复、途中/停车后充电及重复缓存测试。
- F01–F11：`tests/test_summary.py`、`tests/test_web_model.py`、`tests/test_reports.py` 的动力电池路径、非法数值、门窗锁、固定轮位、温度时间、充电冲突和候选门控测试。
- T06、M01–M12：`tests/test_reports.py` 的未取整公式、零时长保护、时间加权功率、双时间连续性、末活动至停止排除及覆盖门槛；既有 monitor 测试覆盖 SOC 污染。
- H01–H06：`tests/test_reports.py` 的五样本门槛、当前事件排除、版本/完整性筛选；历史读取失败在 `Monitor._event` 降级为基础报告。
- A01–A04：`report_attention.py` 只生成已确认普通状态与未知说明；反向枚举全部保持 pending，停车恢复变化不置顶。
- L01–L05：`tests/test_reports.py` 与 `tests/test_monitor_runtime.py` 覆盖真实换行、UTF-8、控制字符、预算降级和 2048 字节发送器硬限制。
- C01–C09：`tests/test_monitor.py` 覆盖 v1 活动升级、v2 观测去重、正文冻结、未知版本、崩溃后 uncertain、退避和事务失败外抛；加法表由 `Monitor.__init__` 幂等建立。
- S01–S05：`tests/test_monitor_runtime.py`、`tests/test_web_server.py`、`tests/test_events.py` 覆盖公共出口、车辆隔离、顶层白名单、离线预览和人工注释不驱动解码。

## 回滚与恢复

可运行回滚版本必须保留 P0 公共投影和 v2 正文冻结兼容。不能直接回到原始 `1fad4c6` 并继续开放旧 Web，因为旧版会透传完整 summary。合成回滚检查至少重跑：公共出口私密哨兵、另一车/无选车隔离、冻结正文逐字节复用、未来版本不发送。没有兼容版本时，停止会读取或发送事件的 Web/monitor 服务，保留整个数据库，不删表、不清 delivery、不移动数据库规避兼容问题。

## 存储估算

用 1,000 条合成规范化观测实测 JSON 平均约 4,150 字节。若车辆在活动期间始终以 60 秒采样，理论上限约 5.98 MB/日，实际仅在行程或充电活动/转换时写入。设计要求默认长期保留，本实现不暗删；若长期实测增长不可接受，应另行设计保留策略，不能在本轮自动清历史。

## 仍待实车证据

目标 SOC、枪连接四场景、停止原因、动力电池温度、门窗打开/未锁、胎压原车报警、交流充电组合仍未启用。这是设计规定的完成状态：实现门控、回退和测试，但不得声称字段已实车验证。后续只有用户另行授权才做只读实车核验、测试群消息或部署。

## 最终离线验证

- `python3 -m unittest discover -s tests -v`：205 项通过。
- Python 全模块 AST 解析：通过。
- `node --check zeekr_control/static/app.js`：通过。
- `git diff --check`：通过。
- 四类合成预览及低预算降级预览：通过，最大 767 UTF-8 字节；未调用车辆客户端或发送器。
