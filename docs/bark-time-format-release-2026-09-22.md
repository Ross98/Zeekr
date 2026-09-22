# Bark 时间格式发布记录 · 2026-09-22

## 变更

- Bark 的行程、充电和自定义提醒时间统一显示为 `YYYY年MM月DD日 HH:MM`。
- Bark 不再显示秒和“北京时间”后缀；转换仍固定使用北京时间。
- 企业微信详细报告继续显示 `YYYY-MM-DD HH:MM:SS（北京时间）`。
- 自定义提醒在 Bark 明确失败后转发企业微信时，企业微信仍收到原始完整时间，避免通道格式互相污染。

## 发布与验证

- 代码提交：`0fab242`（`fix(notifications): simplify Bark timestamps`）。
- 活动发布：`/opt/zeekr-control/releases/20260922-bark-time-0fab242`。
- 停服备份：`/opt/zeekr-control/backups/20260922-bark-time-0fab242`。
- 上一发布：`/opt/zeekr-control/releases/20260921-trip-map-ef14833`。
- 本地完整 Python：648 项通过，47.435 秒。
- 候选图片门禁通过；服务器服务用户完整 Python：648 项通过，75.321 秒。
- 上线后 Web、monitor、Nginx 均 active，两个应用服务 `NRestarts=0`；根页 HTTP 200，未认证 API HTTP 401。
- 正式服务器使用新代码生成并发送“Bark 时间展示测试”；Bark 服务端接受，生成正文无秒字段。
- 验收未请求车辆刷新、未创建车辆事件、未重发历史通知。

## 回滚

停止 Web 与 monitor，持 `/opt/zeekr-control/.deploy.lock` 将 `current` 原子切回上一发布，再启动并复验。此变更无数据库迁移；保留上线后业务数据，不使用停服备份覆盖新记录。
