# 充电账本入口与刷新滚动修复发布

2026-10-02，用户授权「部署」。

活动发布：`/opt/zeekr-control/releases/20261002-ledger-edit-scroll`。
原发布及回滚目标：`/opt/zeekr-control/releases/20260930-compact-record-layout`。
发布备份：`/opt/zeekr-control/backups/20261002-ledger-edit-scroll`。

从线上 current/. 复制候选，仅覆盖四份前端文件：app.js、field-reviews.js、charge-ledger.js、insights.css；三份浏览器测试：ui_energy.cjs、ui_charge_ledger.cjs、ui_refresh_scroll.cjs。验收另修 test_commute_tags.py 的固定月份时间夹具：旧线上同项测试也因十月系统时间失败；只固定第二次规则保存的测试时钟，业务代码不变。共八份文件，逐项哈希校验，其他 package/tests 文件与原发布一致。

验证：服务用户车型/图片门禁通过；候选完整 Python 704 项通过（71.464 秒）；候选充电账本、充电页面、参数核实四套相关浏览器验收（含全站 38 项桌面/手机刷新滚动检查）通过。参数核实使用当前工作区已兼容新导航的浏览器测试，未将该测试额外发布。

持部署锁复制发布备份，原子切换 current，仅重启 Web。zeekr-control、zeekr-monitor、nginx 均 active/running；两应用 NRestarts=0。运行 Web 进程 cwd 与新发布一致，八份部署文件哈希通过。首页 200；未登录 state、账本 API 和 app.js 均 401。

线上未执行真实账单写入，未额外查询车辆。无数据库迁移；未操作业务数据。未执行 Git commit/push。Web 重启清除登录会话，使用时需重新登录。正常登录后的实车浏览器页面未复验；功能行为由同基线合成候选测试验证。
