# Linux 隔离部署模板

通过 SSH 隧道访问，服务仅监听回环地址。以下为通用部署模板；实际服务器地址、账号和既有服务信息仅保存在本机。

## 隔离与目录

- systemd 服务：`zeekr-control`，独立无登录用户同名。
- 版本目录：`/opt/zeekr-control/releases/<版本>`；`current` 指向当前版本。
- 数据目录：`/var/lib/zeekr-control/Library/Application Support/ZeekrControl`，保持现有程序路径规则。会话及位置数据为明文，仅服务用户和管理员可读。
- 只监听 `127.0.0.1:18765`。不开放安全组或系统防火墙端口。
- CPU 上限 25%（一个 CPU 的四分之一），内存上限 256 MiB，禁用服务交换空间，最多 64 个任务，单文件上限 512 MiB，日志限速。单文件限制并非整个目录配额，需定期检查磁盘。
- 服务开机启动、异常自动重启。采集始终需要手动开启；重启或读取失败后不会自动恢复。

## 访问

在 Mac 终端运行并保持连接：

```bash
ssh -o ExitOnForwardFailure=yes -N -L 127.0.0.1:18765:127.0.0.1:18765 YOUR_SSH_USER@YOUR_SERVER_HOST
```

浏览器打开 http://127.0.0.1:18765 。本机和远端必须使用相同端口，以满足现有 Host/Origin 校验。本机如有旧服务占用 18765，先明确停止旧服务。SSH 验证方式以自己的服务器配置为准。

## 管理

以下命令在服务器执行：

```bash
sudo systemctl status zeekr-control --no-pager
sudo journalctl -u zeekr-control -n 50 --no-pager
sudo systemctl restart zeekr-control
sudo du -sh /var/lib/zeekr-control
```

首次需建立极氪会话。可安全迁移已有会话或在服务器交互登录，禁止把 Token、短信验证码写入文档、命令参数或日志。项目代码包不包含任何账号凭据或本地轨迹数据库。

## 回滚

首次部署回滚只停止新服务，保留数据便于恢复，不删除目录：

```bash
sudo systemctl disable --now zeekr-control
```

恢复服务：

```bash
sudo systemctl enable --now zeekr-control
```

后续升级须保留旧版本和旧 unit，停服务后备份数据（权限 700/600）；切换 `current` 后启动、验收，失败切回旧版本。若升级修改数据库结构，必须匹配备份恢复，不能仅回滚代码。本次是首次部署，停用服务即撤销运行影响。

## 验证边界

部署检查包括本机与服务器单元测试、服务资源限制、回环监听、网页与状态接口、停止/恢复演练，以及部署前后既有服务状态和配置校验。单元测试使用合成车辆响应，不证明真实车辆查询成功。真实账号查询及采集应另行记录实测结果。

## 登录保护

服务通过 `ZEEKR_AUTH_FILE` 指定权限 600、归服务用户所有的 JSON 密码哈希文件，字段为 salt 和 digest，使用 PBKDF2-HMAC-SHA256（600000 次）。配置缺失或格式错误时启动失败，不降级为免登录。未设置此环境变量的本地开发服务仍是原来的本机模式，不得公开。

登录会话最长 12 小时，重启全部失效；每五分钟最多五次失败登录，单账户全局限速，可被恶意请求暂时锁定。最多 32 个有效会话；Cookie 使用 HttpOnly、SameSite=Strict，HTTPS 域名入口额外使用 Secure。退出立即撤销当前会话。密码更改需替换哈希文件并重启服务，会注销全部会话。

公开域名须设置 `ZEEKR_PUBLIC_ORIGIN=https://<专用域名>`，不能信任任意 Host 或转发头。Nginx 示例位于 deploy/nginx-zeekr.conf.example，必须先有 DNS 和专用 TLS 证书，禁止以明文 HTTP 暴露车辆或登录接口。

上线回滚前先关闭公网入口，再恢复旧代码及 unit，防止旧版免登录服务被公网代理访问。保留最新数据，重启后采集需手动恢复。密码文件与备份不得进入 Git。
