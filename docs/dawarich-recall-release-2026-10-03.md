# 每日回顾四阶段 · 发布记录

2026-10-03，用户明确授权部署。未授权 commit/push，本次均未执行。部署内容来自已验收工作区；18 个具名源码/测试文件逐文件 SHA-256 保存于候选 `recall-scope-manifest.json`，未打包其他未提交修改、私有资料或浏览器研究文件。实现与本地浏览器/性能证据见 [实现记录](dawarich-recall-2026-10-03.md)。

基线：Git HEAD `23d8d0c`，正式版本 `20261003-calendar-label`。切换前线上 117 个已跟踪应用文件全部匹配 HEAD。候选复制 `current/.`，覆盖 15 个应用文件及 3 个 Python 测试/合成夹具。既有发布功能清单按候选实际哈希重新生成；未覆盖的正式文件（包括私有车型配置）逐文件一致。

首次候选测试发现发布包漏了 `tests/recall_fixture.py`，两个测试报导入错误；当时未切换、旧版继续服务。补齐夹具后以实际 `zeekr-control` 服务用户重跑完整候选 Python 测试：792 项，83.213 秒，全通过。服务用户图片门禁在切换前后均 `RELEASE_CHECK_PASS`，1 个已配置车型图片，artwork_checked=true。候选测试数量按正式基线实际文件集记录，本地完整工作区此前为 793 项。

持 `/opt/zeekr-control/.deploy.lock` 发布锁；测试通过后停止 Web、备份数据、原子切换 current，仅启动 Web。没有重启 monitor，没有主动请求车辆、写入账本/地点纠错或发送通知。

- 活动版本：`/opt/zeekr-control/releases/20261003-dawarich-recall`
- 回滚版本：`/opt/zeekr-control/releases/20261003-calendar-label`
- 数据备份：`/opt/zeekr-control/backups/20261003-dawarich-recall/data`

切换后核对：活动链接、Web 进程工作目录、本次文件哈希、未覆盖基线文件全部通过。Web、monitor、nginx 均 active/running，NRestarts=0。根页 HTTP 200；`/api/timeline`、`/api/place-corrections`、`/api/place-history`、`/api/year-review` 及 `/daily-recall.js` 未认证请求均 401。实际服务账号图片门禁通过。

正式登录后的人工浏览器操作未另验；功能、纠错持久化/撤销、账本返回和布局由既有合成浏览器及候选测试验证。重启使原网页登录会话失效，需要重新登录。无数据库结构迁移，旧记录默认无纠错；回滚保留派生纠错存储而旧代码忽略该集合。
