# Bark 通知发布记录 · 2026-09-21

## 版本与回滚

- 代码提交：`5299e3b`（`feat(notifications): add Bark status alerts`）。
- 活动发布：`/opt/zeekr-control/releases/20260921-bark-5299e3b`。
- 停服备份：`/opt/zeekr-control/backups/20260921-bark-5299e3b`。
- 上一发布：`/opt/zeekr-control/releases/20260921-web-heartbeat-466d7d0`。

候选从上一活动发布的 `current/.` 完整复制后叠加 Git 提交，保留车型配置和私有资产。Bark 配置单独安装到服务数据目录，属主组为 `zeekr-control:zeekr-control`，权限 `600`；设备 Key 未进入 Git、发布包、命令参数或日志。

## 验证

- 本地完整 Python：639 项通过，46.965 秒。
- 本地 Chromium：自定义提醒、存储管理、桌面概览三套场景通过。
- Python 编译、三份修改后的 JavaScript 语法、`git diff --check` 通过。
- 新 `BarkSender` 使用正式 Bark 服务完成本地 HTTPS 集成测试，服务端返回成功。
- 候选图片门禁通过；服务器 `zeekr-control` 用户完整 Python：639 项通过，66.136 秒。
- 2026-09-21 14:51:46 CST 原子切换。`zeekr-control`、`zeekr-monitor`、`nginx` 均 active，两个应用服务 `NRestarts=0`。
- 上线后图片门禁通过；根页 HTTP 200，未认证 `/api/state` HTTP 401。
- `monitor_event_alerts` 已建立，发布时为 0 行，因此没有为历史事件补发 Bark 通知。
- 正式服务器以 `zeekr-control` 用户读取私密 Bark 配置并发送部署测试，服务端返回成功。用户设备是否展示该条通知仍以用户确认结果为准。
- 验收窗口日志无 error 或 traceback；未主动刷新车辆、未重发历史企业微信通知。

## 回滚

回滚时停止 Web 与 monitor，持 `/opt/zeekr-control/.deploy.lock` 将 `current` 原子切回上一发布，再启动并复验服务。保留上线后业务数据；不要用停服备份覆盖新事件。旧版忽略新增 `monitor_event_alerts` 表和 `bark.json`，无需数据库降级。
