# Mac mini 资源巡检与 Bark

独立用户任务 `local.zeekr.resources` 每约 60 秒读一次本机指标，运行入口 `python3 -m zeekr_control.resource_monitor`。它与 Web、车辆采集、报表任务分开，复用服务 HOME 与既有私有 `bark.json`。不读取车辆接口，不控制车辆，不自动停止进程或删除数据。任务以 Nice 10 运行；它提供持续超限软预算告警，不是 Linux cgroup 硬限额。

## 采样与判定

| 指标 | 提醒 | 严重 |
|---|---:|---:|
| 主机 CPU（全机合计 0–100%） | 85% | 95% |
| Zeekr 三任务及所有后代进程 CPU（100%=一核） | 100% | 200% |
| Zeekr 进程树 RSS 合计 | 512 MiB | 1024 MiB |
| macOS 内存压力 | warning | critical |
| 三个既有服务任务 | — | 连续无法取得运行任务 |

CPU 指标来自 top 的相邻采样窗口和 ps 累计 CPU 时间差；包括通知、分析和图片子进程，不只统计三个父 PID。新进程、PID 重用、采样长中断会标记 CPU 窗口不完整；部分进程的 CPU 总和只作为下界，能证明超限，不能证明恢复。RSS 是进程 RSS 相加，可能包含共享页重复统计，不当作 Python 堆或全机物理内存占用。

内存使用 [Apple XNU 导出的 dispatch 压力值](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_memorystatus_notify.c)：sysctl `kern.memorystatus_vm_pressure_level` 的 1/2/4 分别映射正常/提醒/严重，不混用内核内部枚举。剩余内存少不单独触发告警，避免把缓存误判为压力。

连续 3 个有效巡检点确认等级变化与恢复，通常约 2–3 分钟；调用过快、休眠或长时间中断不能虚增连续次数。提醒线恢复有 10% 回差。初始正常、初始 CPU 窗口预热保持安静；采集失败保留“指标不可用”，持续失败会告警，不编造 0。

## 持久状态与投递

`resource-health.json` 保存在私有应用数据目录（目录 700、文件 600），记录最近样本、采样进程 PID、连续计数、确认等级、投递状态及重试时间。独占 `resource-monitor.lock` 防止重复实例。

- 确认异常或恢复时发 Bark；同级异常且上次已确认成功，最多每天提醒一次。
- 发送前必须先持久化 sending 意图；状态写失败不发消息。
- 明确失败按 15 分钟重试，永久错误按 1 小时重试；过时异常不在观察恢复时重发。
- 不确定结果或重启时留下的 sending 变为 uncertain，不自动重发。同级日提醒也不重发 uncertain；后续新等级变化另行记录。
- 状态变化保存的发送结果只表示 Bark 服务端响应；不证明手机实际展示。测试使用合成样本与替身发送器，不发真实测试消息。

## 检查与发布

以实际服务 HOME 运行；若从普通开发终端查看线上状态，显式指定 `--root` 为 `ZeekrServer/state/Library/Application Support/ZeekrControl`。

```sh
python3 -m zeekr_control.resource_monitor --root '<实际应用数据目录>' --inspect
python3 -m zeekr_control.resource_monitor --sample
```

`--inspect` 只读已保存状态，`--sample` 只读本机指标；均不写状态、不发通知。资源任务日志在运行根目录 `logs/resources.stdout.log` 与 `logs/resources.stderr.log`。

固定发布工具的 `macos stage --resource-monitor` 会先在候选检查模块，然后在切换时安装资源 LaunchAgent。既有三个任务的配置全部备份，资源任务列入后续发布的配置指纹、停服、进程目录及心跳检查。首次安装失败回滚会移除新增资源任务；旧版已有资源任务时恢复其原配置。业务数据始终保留最新状态。只生成候选不安装任务，不跳过最终候选服务用户全量测试。

资源任务同样需要用户登录后才启动；机器关机、休眠、掉网或无法写盘时，本机 Bark 不是独立外部可用性监控。存储巡检仍由既有投递后台每 5 分钟执行，现有磁盘告警门槛和事件去重保持不变。

## 本次磁盘调查

磁盘高占用属实，不通过放宽告警门槛掩盖。只读目录统计发现 iCloud 本地副本约 86 GiB、系统开发工具约 18 GiB、用户开发工具约 3.3 GiB；Zeekr 私有数据约 155 MiB，含版本与备份的服务目录约 1.2 GiB。这些是调查时快照与目录分配量，不能相加作为磁盘精确归因，也不代表可直接释放的空间。

未删除缓存、开发工具、iCloud 文件或备份；未操作 iCloud 下载状态。释放 iCloud 本地副本、卸载 SDK 等会影响离线可用性或开发环境，需另行确定范围。存储仍会按真实占用持续告警。
