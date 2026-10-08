# 当前实现入口

产品口径见 [PRODUCT.md](PRODUCT.md)，开发命令见 [开发验证](docs/development.md)，上线操作见 [发布流程](docs/release-workflow.md)。本文件描述代码结构，不声明当前生产版本。

## 数据流

`monitor_runtime` 的采集锁保证一个采集者。采集者读取车辆缓存，发布快照并写入事件／提醒队列；受监督的 `delivery_runtime` 子进程持有通知锁，读取持久队列并投递。父进程退出通过控制管道通知子进程退出；通知锁防止新旧执行者同时发送。独立周期报告仍由 reports 服务调度。

图片状态区分 `pending → preparing → ready → sending → sent`。准备中断可重新准备；已进入发送的中断保留 `uncertain/unknown`，避免重复。定期报告使用旁表保存投递元数据，保持旧 reports 表结构可读写。

## 只读分析

Web 在短锁内捕获账号、车辆及界面 context，耗时读取移出应用锁。历史查询槽位限制并发；结束时复核身份和费用、地点、行程、充电记录版本。数据变化重试一次，再变化返回 409；繁忙返回 429。

桌面长范围查询用 `Prefer: respond-async` 领取 202 任务地址，短轮询取得最终结果，避免一条 HTTP 连接占满代理超时。最多两个执行中任务、总共四张未领取任务票；满额拒绝新查询，不提前淘汰有效结果。完成结果最多 8 MiB、保留 120 秒并只取一次。任务按账号／车辆／context 隔离，不写业务数据，服务重启后重新查询。页面总等待上限十分钟。

归档按 `(observed_at,id)` 键集分页，每次 512 行；冻结每个分片的最大 ID，后续追加留到下一次查询。分片替换或移除拒绝本次结果。月历、月报和停车不再被通用 50000 条限制截断。

精确去重与停车分析使用私有临时 SQLite 投影，只保留必要标量和位置投影，内存缓存 1 MiB、文件上限 256 MiB，退出即清理。空间不足返回 503，不输出“完整”的部分统计。历史采样含义保持 parking calculation_version 6。

## 费用与界面

`PersonalStore.read_many` 在一个读取事务中取 charges 与 expenses；`CostsSummary` 给两处费用展示同一口径。金额为整数分，空缺使用 null，免费使用 0。

`insights.js` 管理工具依赖与懒加载，同脚本共用 Promise，失败允许重试，账号 context 限制迟到操作。`static_assets.py` 从文件内容生成版本号，HTML 与动态工具使用同一映射。只有正确版本的 JS/CSS 使用 private immutable 缓存；HTML/API 保持 no-store，鉴权先于缓存响应。

## 边界

私有配置、凭据、数据库和本地 handoff 不进仓库。桌面只用合成数据做自动 UI 验证。生产 CPU／内存配额、候选版本的服务用户测试及实际通知送达，必须在获准发布时另行核实。
