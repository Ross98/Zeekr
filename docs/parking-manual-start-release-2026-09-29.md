# 停车分析手动开始：发布记录

2026-09-29，提交 `ffe8cf1` 将停车分析改为手动开始。首次打开只显示日期范围与“分析停车观测”按钮；修改日期不请求分析；从日历进入只预选日期。点击按钮后才请求分析。

- 正式发布：`/opt/zeekr-control/releases/20260929-parking-manual-ffe8cf1`。
- 上一发布：`/opt/zeekr-control/releases/20260929-desktop-menu-f4e07a5`。
- 从上一发布用 `cp -a` 建候选，仅覆盖 `zeekr_control/static/parking.js`。未覆盖车辆数据、私有车型资料或监控代码；监控服务未重启。无数据库迁移。
- 回归测试先复现打开即发请求，再验证首次打开、改日期、日历跳转均不发请求，点击按钮才使用所选范围。Python 684 项通过；JS 语法与 `git diff --check` 通过。Safari 合成页面手工确认点击前无结果、点击后出现结果。
- 候选文件 SHA-256 与本地一致；候选及上线后的车型图片门禁均通过。切换后 Web、监控、Nginx 为 active；Web 进程工作目录为新发布。根页面 200，未登录 `/api/state` 为 401，两个应用服务 `NRestarts=0`。

尚未进行登录后的线上浏览器验收。若需回滚，持部署锁将 `current` 原子切回上一发布，重启 Web，并保留车辆数据。
