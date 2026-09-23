# 极氪会话失效 Bark 告警发布记录

北京时间 2026-09-23 发布。代码提交 `c1a58a7`。

- 活动发布：`/opt/zeekr-control/releases/20260923-auth-bark-c1a58a7`。
- 回滚发布：`/opt/zeekr-control/releases/20260922-bark-time-trip-fit-b588ceb`。
- 停服备份：`/opt/zeekr-control/backups/20260923-auth-bark-c1a58a7`。

监控收到 GW2 `1509` 并阻断采集时，使用现有 Bark 配置发送一次短提醒。发送前将意图写入服务用户私有目录的 `auth-failure-alert.json`，避免进程重启或发送结果不确定时重复推送。只有下一次成功读取车辆状态才重置告警。其他阻断错误不会触发这条提醒；不调用企业微信兜底。

本地先运行失败的合成回归测试，再实现并验证；完整 Python 测试 652 项通过。线上候选从活动发布的 `current/.` 复制，仅覆盖监控运行时和相应测试文件，两个文件的 SHA-256 与本地一致。候选以 `zeekr-control` 用户运行 652 项测试通过，发布门禁 `RELEASE_CHECK_PASS`。

切换前通知正文 26 条、行程图片 3 条和 Bark 事件提醒 3 条均为 `sent`，无待发项。持发布锁停两项应用服务、备份私有数据后原子切换；上线后 `zeekr-control`、`zeekr-monitor`、`nginx` 均 active，应用进程 cwd 指向新发布，`NRestarts=0`。根页面 HTTP 200，匿名 `/api/state` HTTP 401。自然采集的 `last_success` 继续推进，错误为空；`stale` 仅表示车辆上报缓存未更新。验收时未生成告警状态文件，未主动请求车辆刷新，也未发送 Bark 或企业微信测试消息。

回滚时持发布锁停止两项应用服务，将 `current` 原子切回上述回滚发布，再启动并复核服务和采集。保留上线后业务数据，不用停服备份覆盖新采样。
