# 假设与验证发布记录

2026-10-06。用户授权完成后 commit、发布。实现提交 `84ef09eddb70f63faa77bf732902c73476feac7f`，分支 `codex/notification-reference-location`；未 push。

## 当前发布

- 当前：`/opt/zeekr-control/releases/20261006-hypothesis-lab-84ef09e`。
- 回滚目标：`/opt/zeekr-control/releases/20261005-overview-compact-c691fb6`。
- 停服备份：`/opt/zeekr-control/backups/20261006-hypothesis-lab-84ef09e`。
- 固定工具 `scripts/release/client.py`。28 个指定文件按提交覆盖线上基线；未提交的无关测试、私人预览、真实研究载荷未进入候选。

## 功能

正式入口“用车研究 → 假设与验证”。全公开目录起草第一版解释，按独立场景或自选参数对照，保留支持和两种反例；常量、未返回、缺口和缺少状态内外样本均提示限制。假设可保存为本车字段级“有疑问”，保护已有人工确认；不自动改变解码或通知。

四档采用用户指定的 0=P、1=R、2=N、3=D，保留来源。停车按排除行程和充电后的相同位置识别，P 档仅作辅助证据，耗电可信度独立处理。此前已提交的前舱盖关闭识别和桌面状态总览也在本次发布中。

## 验证

- 本地专项逻辑、API、核实记录保护及静态检查通过。
- 线上源码匹配副本的 `ui_hypothesis_lab.cjs`、`ui_parking_observations.cjs`、`ui_status_summary.cjs` 通过。仅测试 1440、1280、1024 桌面宽度及深浅主题，无手机检查。
- 服务用户候选全量 `python3 -m unittest discover -s tests` 退出码 0，116.996 秒；stage 117.540 秒。未重复本机全量。
- 原子切换 1.498 秒，上线验收 0.869 秒；28 个部署文件与未覆盖文件哈希匹配。
- zeekr-control、zeekr-monitor、nginx 均 active/running，NRestarts=0；应用进程目录匹配当前发布。
- 根页 200，保护 API、脚本与图片匿名 401。新增 hypotheses API、hypothesis-lab.js、hypothesis-lab.css 的匿名边界另行核对为 401。
- 图片门禁、功能清单、持久登录库与道路库完整性检查通过；93 条已发送事件、38 条图片记录与停服备份逐项保留。
- 已上线代码以实际服务用户只读真实归档，完成全目录假设输出、停车区间和四档映射专项核对。没有车辆刷新、通知发送、业务记录写入或历史回填。
- 专项验收脚本一度将显示到秒的时间误当精确时间，实际端点带毫秒；按真实端点修正后通过。应用源码未变，未重复全量。
- 已登录生产浏览器交互尚未人工验收；合成桌面检查与真实归档只读核对分别记录，不混称。

## 证据与后续

生产匹配副本及本地验证：`/tmp/zeekr-hypothesis-release-20261006/`。实际专项只读证据：`/tmp/zeekr-hypothesis-production-acceptance.json`，不提交私人载荷。服务端阶段与验证指纹由固定发布工具保存。

回滚使用 `client.py rollback`，仅切代码并复验，不覆盖发布后的业务数据。普通登录会话可能随重启失效，持久登录库已检查。
