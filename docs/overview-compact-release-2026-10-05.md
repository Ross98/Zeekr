# 总览紧凑布局发布 — 2026-10-05

用户批准最终预览，并授权 commit、发布。

- 实现提交：`c691fb64742a1f17372a2be7f7efc0370ea3094c`；仅 `zeekr_control/static/app.css`。
- 总览轮胎图改为桌面380px、手机320px，收紧底部间距；定位地图图片本身12px圆角，保持比例和完整图面。其他卡片顺序、车辆详情布局与数据逻辑不变。
- 当前生产：`/opt/zeekr-control/releases/20261005-overview-compact-c691fb6`。
- 回滚：`/opt/zeekr-control/releases/20261005-release-workflow-5c86dd7`。
- 停服备份：`/opt/zeekr-control/backups/20261005-overview-compact-c691fb6`。
- 固定工具 `scripts/release/client.py`；生产匹配副本的地图、总览、图片专项及104项桌面/手机刷新检查通过。纯前端快路径整份候选输入哈希通过，未重复Python全量。此前本地1440/850/390/320宽度无横向溢出，最终截图与批准预览一致。
- 候选stage0.421秒；切换1.534秒；线上验证0.886秒。线上1个变更文件与未覆盖输入哈希通过；图片门禁、功能清单、三服务NRestarts=0、根页200、保护API及CSS/脚本/图片401通过。
- 已发送93条事件、38条图片记录逐项保留；持久登录库与道路库检查通过。
- 本地证据：`/tmp/zeekr-compact-release-20261005/prepared/`；服务端 `.release-timings.jsonl`。
- 未push、未刷新车辆、未发通知、未改密码。普通会话重启可能需重新登录；未验真实已登录Safari或手机。重新载入网页取得样式。
- 既有14个测试修改和私人文件保留。回滚用固定工具 `client.py rollback`，只切代码、不覆盖后续业务数据。
