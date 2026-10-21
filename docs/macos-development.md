# Mac mini 开发与发布

当前常驻服务为 macOS launchd + Tailscale Serve HTTPS。Linux 部署模板保留给旧环境，不再作为 mini 的操作步骤。不能在 mini 上调用 systemctl、Linux 发布阶段或旧云端启动入口。

## 目录与版本边界

- 运行根目录默认 `~/Library/Application Support/ZeekrServer`，`current` 指向 `releases/<版本>`。
- `state` 是三个任务共同的 HOME，应用数据在 `state/Library/Application Support/ZeekrControl`；网页认证文件在 `state/web-auth.json`。
- 用户任务为 `local.zeekr.web`、`local.zeekr.monitor`、`local.zeekr.reports`；配置在 `~/Library/LaunchAgents`。
- Git 是代码来源，生产 `current`、工作树、Git HEAD 是不同状态。不要把 iCloud 同步的整目录当作一个已提交版本，不要直接在 `current` 开发。
- 开始工作先执行 `git status --short`、`git rev-parse HEAD origin/main`、下方 `inspect`，再核对本机 `deployment-status.json`。迁移记录只证明当时状态；后续发布以当前链接、提交、候选哈希和发布记录为准。
- 发现分叉或大量改动时先留独立快照；禁止 `reset --hard`、`clean` 或用生产文件覆盖原工作树。基于已验证生产提交建立干净开发副本，再逐项移植需要的改动。优先把开发仓库放在 iCloud 同步目录之外。工作树创建遇到 Git/iCloud 文件读取错误时，可从远端克隆独立副本，核对 HEAD 等于线上提交后只迁入本轮改动；保留原工作区。

## 检查与访问

```sh
python3 scripts/release/client.py macos inspect
```

只输出布局、服务状态、入口和代理模式，不输出密码或代理凭据。不需要 SSH，也不启动或重启服务。双击仓库根目录的 `启动极氪网页.command` 只打开现有网页；本机自动读 Web plist 的入口。其他 Mac 使用 `ZEEKR_DASHBOARD_URL` 或仓库外 `~/.config/zeekr/dashboard-url` 配置 HTTPS 地址，先连接同一 tailnet。不开 Funnel，不把无认证开发服务暴露到网络。

改网页密码只在 mini 本机交互终端运行 `scripts/change-web-password.command`；它使用实际运行代码和认证文件，只重启 Web，不停止监控与报表。密码不进入参数、日志或 Git。密码文件更新成功而服务重启失败时，用新密码文件排查服务，不能误报密码未改变。

## 候选流程

入口仍是固定 `scripts/release/client.py`，本机加 `macos` 子命令；Linux transport 流程不变。以 LaunchAgent 用户运行，不能 sudo。

1. 实现时跑相关逻辑与桌面检查。用户明确授权后再提交指定路径；不要混入其他工作。
2. `prepare` 只复制线上公开输入，叠加指定提交的指定路径。私人画像、业务库、账号及通知配置不导出到准备目录。路径与命令数组格式沿用发布文档。
3. `stage` 在独立版本目录复制当前运行版本，保留私有画像与文件权限，再叠加已提交代码。图片及功能清单先通过；后端、认证、发布工具或未知改动，实际 launchd 用户与 `/usr/bin/python3` 在最终候选跑一次全量。纯前端校验精确输入及桌面检查回执。失败不停止旧服务。
4. `deploy` 先重查当前版本、任务配置、候选输入集合和哈希，持有迁移锁；卸载三个任务，等待包装器和子进程退出，再备份整个 state 并校验内容、权限及 SQLite。留存任务配置，原子切换链接，重新加载任务。
5. 上线检查三个任务、进程工作目录、意外重启、双入口 HTTP/匿名认证、车型图、数据库及已发送事件/媒体保留。失败恢复旧代码和任务配置；**保留最新业务状态，不用旧备份覆盖**。通知未发送准备状态按原兼容规则规范化；无法证明停服或规范化失败时停止操作，人工排查。

```sh
python3 scripts/release/client.py macos prepare \
  --commit <完整提交号> --paths <paths.json> --checks <checks.json> \
  --name <日期-功能-提交号> --output <全新准备目录>

# 下列会写候选或切换服务，须在已授权发布时执行。
python3 scripts/release/client.py macos stage --bundle <准备目录>/bundle --tailscale-ip
python3 scripts/release/client.py macos deploy --bundle <准备目录>/bundle
python3 scripts/release/client.py macos verify
python3 scripts/release/client.py macos rollback
```

`--tailscale-ip` 用于首次启用新代理模式。候选先验证支持该模式，只有切换时才在 Web plist 设置 `ZEEKR_TRUST_TAILSCALE_IP=1`、移除旧 `ZEEKR_TRUST_PROXY_IP`。回滚恢复原 plist。后续发布已启用该模式时可以省略该选项。准备和候选失败均不更改线上 plist。

Tailscale 模式仅在指定 HTTPS Origin、回环代理连接下接收单个 `X-Forwarded-For` tailnet 地址及 `X-Forwarded-Proto: https`。拒绝重复头、多地址链、非 tailnet 地址；不读取 `X-Real-IP`。本机入口继续忽略转发头。代理必须是直连本机的 Tailscale Serve，不能在前面再接任意代理。参考 [Serve 转发头实现](https://github.com/tailscale/tailscale/blob/main/ipn/ipnlocal/serve.go)。

发布状态与耗时分别记录为运行根目录 `.macos-release.json`、`.release-timings.jsonl`；候选验证记录在准备包 `macos-validation.json`。Linux 的 cgroup CPU/内存指标不用于 macOS，也不能用 macOS 测试冒充 Linux 资源限制验收。

## 无人值守恢复与维护

当前用户 LaunchAgents 是**登录后启动**，不保证机器停在登录界面时服务可用。`KeepAlive.SuccessfulExit=false` 只针对异常退出恢复。防睡眠、断电后开机、FileVault 解锁、Tailscale 恢复和应用启动是独立事项。

改变前先检查 `pmset -g custom`、FileVault 与实际登录要求。用户选定无人值守策略后，再决定保留用户登录启动，还是迁移到专用账户的 LaunchDaemon；不要直接给服务加 root 身份。若授权修改系统设置，记录旧值及恢复步骤。随后做一次真实重启/断电恢复，核对 Tailscale、三个任务、端口认证、监控采样连续性与报表状态。只看到网页 200 不算恢复验收。

生产 state、认证文件、私有画像、外部代理配置不进 Git/iCloud 开发同步，不用开发测试库替换生产库。停服备份留在受限目录，并另做独立磁盘备份；定期验证 SQLite 和恢复能力。LaunchAgent 文件日志不等于 journald 自动轮转：单独配置日志轮转与保留周期，不能靠每次发布清空日志。以上系统维护不随代码准备自动执行。

## 网络诊断边界

系统代理的“跳过代理”和 DNS 直连是两件事。若 HTTPS 出现 TLS EOF，但 Serve 与本机服务正常，检查域名是否被代理 DNS 映射到 `198.18.0.0/15` Fake IP。将 `tailscale status --json` 中该节点的 DNSName/IP 与系统解析结果比对；不要把 IP 变化当作应用认证错误。

诊断可用系统 curl 的 `--noproxy '*' --resolve '<域名>:443:<实际 tailnet IP>'`，保留原 HTTPS 域名及证书验证，禁止 `-k`。它只用于区分 DNS/路由与服务故障，不能替代普通浏览器访问验收。固定发布门禁仍检查正常域名入口，失败就停止发布；不能为通过门禁跳过 DNS、TLS 或认证。修复应在实际网络代理里为专用域名配置适当的 DNS/路由绕过，并重新实测；不在源码写私人域名或静态 tailnet IP。
