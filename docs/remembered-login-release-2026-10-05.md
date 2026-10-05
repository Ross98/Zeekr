# 记住设备登录发布

2026-10-05。用户已批准方案及 commit、部署；未授权 push，本次未 push。

实现提交 `d9ce7abfe8c84beffafddef1d60f8d5c4a86d47e`，仅 12 个指定文件。既有 14 个测试修改及私人、研究、预览文件未暂存、未部署。发布前线上 121 个应用文件与提交前 Git 基线一致。

登录默认不记住，沿用 12 小时普通会话。选 7/30 天时，Cookie 随机凭证、浏览器 User-Agent 与服务端可确认 IP 绑定，期限固定，不因访问延长。持久库只保存哈希和到期时间；退出或重新登录替换旧凭证，改密码记录后旧凭证失效。普通会话和记住凭证各上限 32。

## 实际发布

- 当前：`/opt/zeekr-control/releases/20261005-remembered-login-d9ce7ab`。
- 回滚：`/opt/zeekr-control/releases/20261004-overview-performance-cabf880`。
- 停服备份：`/opt/zeekr-control/backups/20261005-remembered-login-d9ce7ab`。
- 候选从 `current/.` 复制，覆盖提交内 12 个文件，其他应用文件逐项哈希保持一致，复制文件权限与属主恢复。
- 持发布锁；候选图片门禁通过。停 Web、monitor 做内容、权限、属主核对的私有数据备份，再原子切换，启动两项应用服务。未改线上 Nginx、systemd 或密码文件。
- 当前无 `ZEEKR_PUBLIC_ORIGIN`，为 SSH 隧道入口；绑定服务器看到的隧道出口 IP，不声称识别客户端原始公网 IP 或物理主机。公网配置仍需按部署说明核对可信代理并启用 `ZEEKR_TRUST_PROXY_IP=1`。

## 验证

- 本地全量 824 项通过；真实浏览器合成环境覆盖 7/30 天 Cookie、实际测试服务器重启保留、另一浏览器匿名、浏览器标识不同拒绝、持久退出撤销、普通会话重启失效和错误恢复。日间/夜间、1440/390/320px 布局及文本对比度通过。
- 生产匹配候选由实际服务用户跑 823 项，107.476 秒，OK。本地额外 1 项来自既有未跟踪测试，未加入发布。
- 上线代码再由服务用户跑 `test_remembered_auth`、`test_remembered_auth_http` 两组隔离测试，命令退出 0。隔离库验证固定到期、跨认证实例恢复、退出持久撤销、密码记录变更、上下文绑定、可信代理和存储失败关闭访问；不写生产认证凭证。
- 上线 12 个文件及未覆盖应用文件哈希核对通过，12 个功能摘要 matched，发布基础版本为实现提交。
- Web、monitor、nginx active/running，均 `NRestarts=0`；两项应用进程目录对应当前发布。根页面和公开登录资源 200；保护 API、脚本、车型图片匿名 401。
- 实际 Web 创建持久库于 `/var/lib/zeekr-control/Library/Application Support/ZeekrControl/web-remembered.sqlite3`，属主为服务用户、文件 600、目录 700；表结构和 SQLite quick_check 通过。
- 上线图片门禁通过，configured_images=1、artwork_checked=true；新 Web 日志无 traceback。停服备份中 89 条原有已发送事件逐项与上线库一致。未主动刷新车辆或发送测试通知。

## 未完成的真实账号验收

本机 `Key.md` 仅在本机读取，经已有 SSH 隧道进行一次正常网页登录；线上返回 401。未打印、提交或上传该私有文件，未重设密码、未伪造会话、未绕过认证。真实账号浏览器中的“记住后重启仍免密”未验证；生产服务并未为此再次重启。隔离测试和实际持久库检查不能替代此项账号验收。

旧普通会话因本次 Web 重启失效，首次仍须输入当前访问密码，再选择记住期限。回滚旧代码也会使新记住凭证无法使用；保留后续业务数据，不用停服备份覆盖数据。

发布脚本、基线哈希、提交归档和脱敏浏览器结果在本机 `/tmp/zeekr-remembered-login-release/`，绑定本轮基线，不原样复用。
