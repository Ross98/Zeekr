# 固定发布工具上线 — 2026-10-05

用户授权 commit、部署；未 push。

- 实现提交 `5c86dd7a03fa2f1c69c13cff700fac88e27f2750`；11 个指定文件：AGENTS、发布流程文档、8 个固定 Python 工具、1 个测试文件。
- 生产 `/opt/zeekr-control/releases/20261005-release-workflow-5c86dd7`。
- 回滚 `/opt/zeekr-control/releases/20261005-overview-images-48a964e`；停服备份 `/opt/zeekr-control/backups/20261005-release-workflow-5c86dd7`。
- 固定入口 `scripts/release/client.py`，替代每次造临时发布脚本。纯前端使用专项浏览器验证和整份候选公开输入哈希；后端/认证/发布工具用最终候选的服务用户全量一次。失败不复用，变化作废；候选切换前核对文件集合和所有部署文件哈希，包括文档。
- 本机 13 项发布工具检查通过，含候选 staging 模拟、前端全量 0 次/后端 1 次、私有配置不导出/不覆盖、漂移拦截、失败回滚和失败耗时保存。此前 release_check 6 项、release_info 5 项通过。
- 本次属于发布工具变更：服务器真实服务用户候选全量退出 0，115.841 秒，只跑一次；没有额外本机全量或提交后全量。
- 实测源码快照传输 24.655 秒；候选 stage 116.346 秒（复制 0.048 秒、图片门禁 0.081 秒、全量 115.841 秒）；切换 1.507 秒；上线 verify 0.879 秒。deploy 往返 2.518 秒。不是从用户授权到结束的总墙钟，也不是纯前端发布实测。
- 11 个部署文件及未覆盖公开输入哈希、325 个候选绑定文件、已安装的 6 个服务器工具与发布目录内源码一致；12 功能摘要 matched。Web/monitor/nginx active/running，NRestarts=0；两个应用进程目录指向新 release。
- 根页/公开登录资源 200；位置、报告、日历、应用脚本/样式/车型图片匿名 401。候选与线上图片门禁通过。
- 记住登录库属主/权限/结构/quick_check、道路库属主/权限/quick_check及与停服备份哈希一致通过。93 条已发送事件、38 条已发送图片记录逐项保留。新 Web 日志无 traceback。
- 自动失败回滚接线已安装；本次上线全部通过，未主动做生产故障注入或真实回滚。回滚只切代码，不覆盖后续业务数据。
- 本机证据 `/tmp/zeekr-release-workflow-20261005/`；服务器 `/opt/zeekr-control/.release-timings.jsonl`、`.release-server-validation.json`。后续用固定客户端生成新包，别原样复用本次包。
- 原 14 个浏览器测试修改、后来出现的 app.css 修改、私有/研究文件保留，未收进提交/部署；main/origin/main 未移动。未刷新车辆、发通知、改密码或 push。
- 本次未验已登录生产浏览器、Safari或真实手机。普通会话因重启可能需重登；持久凭证保留。
