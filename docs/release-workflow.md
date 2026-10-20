# 固定发布流程

入口：`scripts/release/client.py`。替代每次在 `/tmp` 编写一套发布脚本。

## 执行规则

1. 完成实现时跑相关检查。用户授权 commit、部署后，先确定指定文件并提交；不要再次跑工作树全量。
2. `prepare` 只读获取生产公开源码，覆盖指定提交的指定文件。测试运行在这个生产匹配副本，不混入工作区其他修改。私人车型配置、业务库、凭据不下载。
3. 纯静态前端改动：在副本跑相关浏览器检查；服务器核对整份源码、测试、公共数据依赖的哈希后复用结果，跳过 Python 全量。
4. Python、登录资源、共享导航、发布工具、未知类型或仅测试改动：服务器实际服务用户跑一次全量。可先跑必要专项检查；不要再加本机全量、提交后全量等重复关卡。
5. 上传固定模板，候选图片门禁、功能清单通过，再切换；上线验证失败自动切回旧代码。业务数据不回滚覆盖。
6. 上线记录按实际输出写一次。不要为重复检查或重复记录再造多个提交。

全量验证结果绑定所有公开可执行输入、数据依赖、命令、解释器、用户、平台和目录；失败结果不复用。验证途中修改或增加源码立即失败。候选验证后到切换前再核对输入集合和哈希。真实生产交互验收与合成浏览器检查仍分别记录。

## 使用

`transport.json` 是 SSH 参数数组，或已有远端包装器参数数组；保存在仓库外，不含密码。工具不自动查找凭据或输出 SSH 目标。例如使用你已有的本地 SSH 主机别名：

```json
["ssh", "-o", "BatchMode=yes", "zeekr-server"]
```

`paths.json` 是用户授权的指定文件数组。`checks.json` 是命令参数数组，例如：

```json
[["node", "tests/ui_overview_dashboard.cjs"], ["node", "tests/ui_refresh_scroll.cjs"]]
```

浏览器依赖沿用已有 Playwright 和 Chromium；运行前配置 `NODE_PATH`、`CHROMIUM_EXECUTABLE`（如原环境需要）。工具不另装依赖。这些环境变量及命令可执行文件信息也进入验证指纹。

前端发布必须提供 `node tests/ui_*.cjs` 浏览器检查，不能用空命令跳过。后端可使用 `[]`，服务器候选仍必跑全量；必要的专项浏览器检查照常列入。

```sh
python3 scripts/release/workflow.py plan zeekr_control/static/app.css
python3 scripts/release/client.py prepare \
  --transport /private/tmp/transport.json \
  --commit <完整40位提交号> \
  --paths /private/tmp/paths.json \
  --checks /private/tmp/checks.json \
  --name <日期-功能-提交号> \
  --output /private/tmp/zeekr-release-new

# 仅在用户明确授权部署后执行以下动作。
python3 scripts/release/client.py upload --transport /private/tmp/transport.json --bundle /private/tmp/zeekr-release-new/upload.tar.gz
python3 scripts/release/client.py stage --transport /private/tmp/transport.json
python3 scripts/release/client.py deploy --transport /private/tmp/transport.json
```

`prepare` 不提交、不上传、不切换生产。准备失败保留输出排错，修复后换新目录。新增文件权限为 644，既有文件保留原权限；可执行脚本或服务变更需扩展计划。

桌面检查新增的公开输入仅允许 `package.json`、`scripts/browser-failure-evidence.cjs`、`scripts/check-desktop-manifest.cjs`、`scripts/desktop-test-manifest.json`、`scripts/test-desktop.cjs`，它们进入快照、候选验证指纹及切换前哈希校验；不放开其他根 JSON 或 scripts 文件。

删除仅支持三组固定退役路径，须有对应功能移除及发布授权。`--delete-retired-ui-car` 仅删除 `tests/ui_car.cjs`；`--delete-cloud-history` 仅删除 `zeekr_control/history.py`、`zeekr_control/static/history.js`、`tests/test_history.py`、`tests/test_history_connect.py`、`tests/test_history_web.py`。`--delete-parking-page` 仅删除 `zeekr_control/static/parking.js`、`tests/parking_calendar.cjs`、`tests/parking_calendar_model.cjs`、`tests/parking_manual_start.cjs`、`tests/ui_parking_calendar.cjs`，不影响后台停车分析。给 `prepare` 添加对应选项，不要把退役文件放进写入用的 `paths.json`。不支持其他路径或任意删除列表，不删除私有数据。

构建必须证明指定 Git 提交中每个退役路径均不存在，且生产基线逐项记录旧文件哈希。删除以 changes 中各路径的 `null` 表示，不含删除用归档成员。候选只删除普通文件，拒绝文件和父目录符号链接；删除强制走服务用户 Python 全量。切换前及上线后逐项核验候选文件缺失，重新出现立即失败。

代码回滚备份仍是保留的上一版 release 目录；不会从中删除退役文件。stage、切换前、上线核验及手动回滚前均验证退役文件与生产基线哈希一致。回滚原子切回上一目录即可恢复旧代码，不用旧业务数据覆盖新数据。停服私有目录备份及逐文件校验保持原流程。合成回归执行实际回滚脚本，验证旧文件恢复且后续业务数据保留；这不代表在生产执行过回滚演练。

## 耗时与范围

本机专项检查记录在 `bundle/local-validation.json`；服务器阶段耗时记录在 `/opt/zeekr-control/.release-timings.jsonl`；全量测试每项命令耗时和通过指纹记录在 `/opt/zeekr-control/.release-server-validation.json`。传输耗时直接输出。命令失败终止后续阶段。

发布工具本身不改应用业务逻辑；安装和切换生产版本仍须用户授权。保留原发布锁、两服务重启、停服私有目录备份及逐文件校验、服务进程目录、匿名认证边界、图片门禁、持久登录库检查，以及已发送事件和图片记录保留检查。它们有业务价值，暂不为追求速度移除。删掉的是前端发布的无关全量和切换前重复图片门禁；上线后门禁仍保留。

预期纯前端每次省掉服务器全量约 109–116 秒；不再叠加无变更的本机全量可再省约 64–66 秒/轮。依据历史日志估算，纯前端快路径尚未生产实测，不能承诺总耗时。首次工具安装实测候选验证116.346秒、切换1.507秒、上线验收0.879秒，见 [发布记录](release-workflow-release-2026-10-05.md)。

## 通知准备状态的回滚兼容

手动回滚和切换失败后的自动回滚均先确认全部服务停下，再以服务用户调用失败候选的 `delivery_state.normalize_preparation_for_rollback`。函数取得通知与报表两把独占锁，只把已证明尚未发送的 `preparing` / `ready` 改回旧版本认识的 `pending`，保留尝试次数、冻结内容和全部已发送记录。`sending`、`unknown`、`uncertain` 不转换、不自动重发；任何规范化失败都会阻止旧代码切换，等待排查。没有该模块的旧候选无需此步骤。

周期报表新增信息放在 `report_delivery_metadata` 旁表，原 `reports` 八列保持不变，旧版本仍能按原格式插入。回滚只切代码并兼容未发送状态，不用旧备份覆盖后续个人记录或业务数据。Linux 发布验收仍须验证采集进程、投递子进程与图片进程共享的 15% CPU / 128 MiB 预算；本机离线功能检查不替代该项资源验证。
