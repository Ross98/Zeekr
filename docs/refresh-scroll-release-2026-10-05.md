# 全页刷新位置修复发布 — 2026-10-05

用户授权 commit、部署。实现提交 `8007f8ec40abf9ea8177f74ee422e09506ce603f`，26 个指定文件：23 个 static 脚本、2 个回归测试、1 份检查记录。未 push；原有 14 个测试修改和私人、研究、预览文件未暂存、未部署。

## 实际发布

- 当前：`/opt/zeekr-control/releases/20261005-refresh-scroll-8007f8e`。
- 回滚：`/opt/zeekr-control/releases/20261005-remembered-login-d9ce7ab`。
- 停服备份：`/opt/zeekr-control/backups/20261005-refresh-scroll-8007f8e`。
- 上线前生产 121 个应用文件与提交前 Git 基线逐项匹配。候选从 `current/.` 复制，覆盖这次提交内 26 文件；其他应用文件哈希、属主、权限保留。
- 持发布锁，候选通过服务用户门禁和测试；停 Web/monitor 后备份 `/var/lib/zeekr-control/.`，逐文件内容/权限/属主核对，再原子切换 current，启动 Web/monitor。未修改 Nginx、systemd、密码配置或业务库；保留回滚代码与备份。

## 验证

- 用 Git 暂存树生成独立副本，仅含将提交内容：824 个 Python 测试，61.933 秒，OK；104 项 1440/390px 全页刷新回归、共享重绘/异步用户动作守卫、总览请求合并/账号隔离回归通过。25 个 JS/CJS 语法检查和 diff 检查通过。
- 生产匹配候选由实际服务用户跑 823 个测试，107.786 秒，OK。部署副本来自现有生产基线，测试数与本地 Git 树不同；未把无关测试补入生产。
- 候选、切换前、切换后图片门禁均通过：configured_images=1、artwork_checked=true；12 个功能摘要 matched，基础版本是实现提交。
- 上线 26 文件及未覆盖应用文件哈希匹配，current 和两个应用进程目录都对应本次版本。Web、monitor、nginx active/running，NRestarts=0。
- 有界 readiness 等待后：根页、公开样式/登录资源 200；充电、位置、报告、日历保护接口以及 app.js/navigation-state.js/overview-dashboard.js/图片匿名 401。
- 上线源码核对：总重绘接入 RefreshView，同账号记录更新保留加载结果，总览临时布局高度保留，历史查询恢复用用户动作守卫。
- 记住登录私有 SQLite 的服务用户属主、文件 600、父目录 700、表结构及 quick_check 正常。认证源码未改；未打印或修改凭证。
- 89 条停服备份中原有已发送监控事件，与上线业务库逐项一致。新 Web 日志无 traceback；未主动刷新车辆、发送测试通知或回填历史。

## 范围与后续

本次浏览器功能验收用合成车辆和归档。未做已登录生产浏览器、Safari 或真实手机交互；生产哈希、源码契约与服务检查不等同这三项验收。6 个旧浏览器套件在未修改基线也失败，细节见 `refresh-scroll-audit-2026-10-05.md`，未将其计为通过。

普通会话随 Web 重启失效，可能需重新登录；此前选择 7/30 天的持久凭证按原逻辑保留。已打开页面需重新载入取得新脚本。

发布脚本、基线哈希、提交归档在 `/tmp/zeekr-refresh-scroll-release/`，只绑定本次基线。回滚只切代码，不用停服备份覆盖后续业务数据。
