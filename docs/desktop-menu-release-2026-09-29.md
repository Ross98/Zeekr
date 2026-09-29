# 桌面菜单归位：发布记录

2026-09-29，按用户“测试没问题就可以 commit、部署了”指令发布。菜单改动提交为 `0b9611f`；合并线上行程与停车功能后的本地提交为 `f4e07a5`。

- 正式发布：`/opt/zeekr-control/releases/20260929-desktop-menu-f4e07a5`。
- 上一发布：`/opt/zeekr-control/releases/20260928-parking-timeout-4758032`。
- 候选从上一发布用 `cp -a` 复制，只覆盖 `app.js`、`insights.js`、`insights.css`。监控服务代码、私有车型资料、车辆数据未覆盖；监控服务未重启。
- 本地 Python 回归 684 项通过。JS 语法及 `git diff --check` 通过。合成数据浏览器验证充电曲线和行程标签入口可打开；合并前另以 Safari 做过桌面手工检查。Playwright 自动 UI 套件因本地缺少浏览器程序未执行。
- 候选三个文件的 SHA-256 与本地一致；服务用户运行车型图片发布检查通过。
- 原子切换 `current` 后重启 Web。Web、监控、Nginx 均为 active，Web 进程工作目录为新发布；根页面 200、未登录 `/api/state` 为 401，车型图片检查再次通过，Web 与监控 `NRestarts=0`。

本次为静态界面改动，无数据库迁移。尚未做登录后的线上桌面浏览器验收。若需回滚，持部署锁将 `current` 原子切回上一发布并重启 Web；保留当前车辆数据。
