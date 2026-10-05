# 轻量路网匹配发布 — 2026-10-05

用户授权提交、部署。已上线，未 push。

- 实现提交：`92dfee2b8771975acb77a97b76422b53a0b02103`，13个指定文件；其他14个已有浏览器测试修改未纳入。
- 当前生产：`/opt/zeekr-control/releases/20261005-road-matching-92dfee2`。
- 回滚代码：`/opt/zeekr-control/releases/20261005-overview-order-d201b8a`。
- 停服一致性备份：`/opt/zeekr-control/backups/20261005-road-matching-92dfee2`。业务库不做迁移或历史回填。
- 新增4个只读区域道路库，约9.9MiB，独立于Git源码，安装在 `/var/lib/zeekr-control/Library/Application Support/ZeekrControl/road-networks`。目录700、数据库600，均归服务用户；hash与quick_check通过。区域快照不等于全国完整路网，缺路网仍回退原连线。
- 算法最近道路＋最短路径，标准库实现。原始观测、可信片段、缺口、回放保留；道路推断不作实走确认。Linux单worker：256MB地址空间、CPU6秒、墙钟8秒、nice10；每次1500有效点和10公里单起点搜索上限。无需新增常驻路由服务。

## 验证

- 工作区835个Python测试通过；暂存的生产副本834个测试通过（62.527秒），前端显示/稀疏质量及真实API合成浏览器检查通过。
- 真实服务用户候选834个测试通过（108.147秒）；图片门禁、12个原有功能摘要全匹配。
- 候选及上线各用服务用户只读跑6条真实历史路线，匹配可运行、原始观测/缺口原样保留，匹配跨度不越原片段，不越180秒缺口。六路线返回匹配源点373；未知观测也保留。缓存复读一致。
- 上线13个文件hash、未覆盖基线文件hash、实际进程目录与活动symlink一致。两个应用服务及nginx active/running，NRestarts=0；根页200；轨迹API、匹配相关JS和其他保护资源无认证401。
- 原93条已发送事件逐项保留；记住登录数据库权限/属主/结构/quick_check通过。新Web日志未出现Traceback。
- 没有手动车辆刷新、测试通知、密码变更或登录绕过。普通会话可能因重启失效，持久登录凭证按原逻辑保留。尚未验用户真实Safari/手机/已登录生产页面；浏览器证据为合成输入。

## 证据与回滚

本次脚本和本地证据：`/tmp/zeekr-road-matching-release/`；绑定本次基线、commit与道路hash，不能原样复用到下一次发布。服务器保留对应 `.road-matching-*` 记录。

已准备服务器 `/opt/zeekr-control/.road-matching-rollback.py`：持部署锁、验证当前候选、停两个应用服务、原子切回上一代码、启动服务。回滚只切代码，不用备份覆盖后续业务数据；新增只读路网可保留，旧代码不会使用它。
