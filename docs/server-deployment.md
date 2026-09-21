# Linux 隔离部署模板

自动行程与充电通知使用独立的 `zeekr-monitor.service`，启用方法见 [监控说明](monitor-usage.md)。下文“采集默认关闭”“重启需手动恢复”指 Web 手动采集；已启用的自动监控会随服务器启动并恢复其持久化状态。

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

## Bark 状态提醒

Bark 配置保存在服务数据目录的 `bark.json`，属主为 `zeekr-control`、权限为 `600`。配置包含 `base_url` 和 `device_key`，不得进入 Git、发布包、命令参数或日志。状态短提醒与企业微信详细报告的通道分工见 [Bark 通知说明](bark-notifications-2026-09-21.md)。

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

### 车型图片发布硬检查

已有车型图片的服务器，必须保留 `zeekr_control/vehicle_profiles.json` 的所有权和权限。复制候选使用 `cp -a /opt/zeekr-control/current/. <候选目录>/`；禁止使用丢失属主/组的普通复制后仅凭 root 读取成功放行。该文件不进 Git、不随代码包覆盖。推荐 `zeekr-control:zeekr-control 640`（或 `root:zeekr-control 640`），不要把整棵代码或数据目录递归改成宽松权限。

每次切换 `current` **之前**，用真实服务用户执行候选检查；失败停止发布，不先停旧服务：

```bash
sudo -u zeekr-control python3 /opt/zeekr-control/check-release.py <候选目录> --require-image --service-user zeekr-control
```

检查真实读取车型配置、合法图片关联、PNG 和 SVG 可读性，以及概览 SVG 内嵌图片与详情 PNG 一致性。不访问车辆接口、不读取凭据、不发送通知；错误不打印私有配置内容。单元测试和文件哈希不能替代这一步。

首次启用门禁：将已验收版本的 `zeekr_control/release_check.py` 用 `install -o root -g root -m 644` 安装到 `/opt/zeekr-control/check-release.py`；在 `/etc/systemd/system/zeekr-control.service.d/` 安装 `deploy/zeekr-profile-check.conf` 为 `profile-check.conf`，再 `systemctl daemon-reload`。`ExecStartPre` 自动以 Web 服务用户执行；配置读不了时 Web 启动失败，不再悄悄显示无车图页面。图片故障不应阻止独立监控服务采集数据，因此不向监控 unit 添加图片检查。独立检查脚本放在版本目录之外，兼容回滚到没有此模块的旧代码。启用之前先修好、验证当前版本。

上线后仍需用服务账户检查真实缓存车况的 `profile.image`，以及浏览器概览、车辆详情图片是否加载。不要为了验图主动调用车辆刷新接口。Web 启动时可能缓存过错误的空车型资料：修权限后需重新加载配置；重启 Web 会注销现有网页登录，但不应删除车况数据。若候选检查失败，旧版本继续服务；若切换后启动检查失败，恢复兼容旧版本并重新验收。

## 登录保护

服务通过 `ZEEKR_AUTH_FILE` 指定权限 600、归服务用户所有的 JSON 密码哈希文件，字段为 salt 和 digest，使用 PBKDF2-HMAC-SHA256（600000 次）。配置缺失或格式错误时启动失败，不降级为免登录。未设置此环境变量的本地开发服务仍是原来的本机模式，不得公开。

登录会话最长 12 小时，重启全部失效；每五分钟最多五次失败登录，单账户全局限速，可被恶意请求暂时锁定。最多 32 个有效会话；Cookie 使用 HttpOnly、SameSite=Strict，HTTPS 域名入口额外使用 Secure。退出立即撤销当前会话。密码更改需替换哈希文件并重启服务，会注销全部会话。

公开域名须设置 `ZEEKR_PUBLIC_ORIGIN=https://<专用域名>`，不能信任任意 Host 或转发头。Nginx 示例位于 deploy/nginx-zeekr.conf.example，必须先有 DNS 和专用 TLS 证书，禁止以明文 HTTP 暴露车辆或登录接口。

上线回滚前先关闭公网入口，再恢复旧代码及 unit，防止旧版免登录服务被公网代理访问。保留最新数据，重启后采集需手动恢复。密码文件与备份不得进入 Git。
