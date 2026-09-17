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
