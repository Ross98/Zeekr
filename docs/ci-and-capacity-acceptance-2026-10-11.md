# CI 与实际资源配额验收 — 2026-10-11

## CI

新增 `.github/workflows/tests.yml`，push、pull_request 和手动触发均执行检查。Python 使用 Ubuntu 24.04／Python 3.12，运行 `python -m unittest discover -s tests`。桌面任务使用 Node 22、`npm ci` 和锁定版本 Playwright 的 Chromium，运行 `check:js`、`test:unit`、`test:desktop`；明确指定 Chromium 路径，避免旧测试的 `channel: chrome` 选用未锁定浏览器。仅授予 `contents: read`，不读取生产凭据，也不部署。

本地验证：actionlint 1.7.12 通过；32 个 JS 语法文件、17 个逻辑测试文件、15 个桌面浏览器文件通过，浏览器检查耗时 115.0 秒。3 个新容量工具测试通过。浏览器环境为 macOS、Node 26.5.0、Playwright 1.62.1、Chromium 151.0.7922.34；这不等于 GitHub Ubuntu／Node 22 的首次运行已通过。应用代码未改，本轮未重复原应用 Python 全量；上一发布最终 Linux 候选全量 1084 项已通过，新增 3 项在本轮单独验证。

原刷新测试出现底部位置 1598→1560 的误报。诊断时文档最大滚动位置也变为 1560，浏览器必须夹紧到底部；随后的内容更新又增加可滚动高度，但旧断言仍与第一次更新前的位置比较。修正测试为 `min(更新前实际位置, 更新后最大位置)`，下一次更新以第一次更新后的实际位置为基准。保持 2 px 容差和展开状态断言，未跳过检查；最终 108 项桌面刷新位置检查通过。

GitHub 在本轮检查时 main 为 `2af79d8`，工作流数量为 0；本地已上线提交 `0409c9c` 尚未 push。用户随后明确授权 commit、push；工作流随本次上传激活。首次 GitHub Ubuntu 检查结果以 Actions 运行记录为准，不能用本地结果代替。

首次 GitHub Actions 运行 [38145337217](https://github.com/Ross98/Zeekr/actions/runs/38145337217)：Ubuntu／Python 3.12 的 1087 项测试通过，93.686 秒；桌面任务在 `ui_tool_navigation.cjs` 的账本懒加载可见性检查失败。测试先前点击后立即查询 `isVisible()`；补充等待目标 visible/hidden 状态，保留原可见性、导航和选中状态断言。本地专项通过，后续 Actions 结果仍以运行记录为准。

规范依据：[GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)、[Playwright CI](https://playwright.dev/docs/ci)。

## 生产配置与隔离方法

验收读取当前生产 `0409c9cb051b6ed8ff411a7ada01db4dda5e463c` 的代码，不修改 current、unit、配置或业务库。使用真实服务用户、独立 systemd cgroup、合成私有库、禁用网络、PrivateTmp、共享启动屏障。月报和采集通知各自有独立的 128 MiB／15% CPU 限额；Web 为 256 MiB／25% CPU，MemoryHigh 为 192 MiB。采集与通知图片的父、子进程共用采集通知 cgroup，月报图片子进程共用月报 cgroup。

测试额外禁用 swap；仅对生成的合成 SQLite 文件执行定向缓存驱逐，没有清理生产缓存。267840 条鲜活合成记录覆盖完整 31 天；行程图片使用 300 点合成轨迹和合成道路库。采集按每秒一次调用真实 Runner.tick，使用假车辆客户端，模拟车辆时间每次推进 30 秒，不调用真实发送器。

初始两次环境准备失败分别是临时目录只读、PrivateTmp 隐藏 `/var/tmp` 下的工具，均不计为容量证据。工具改放独立 `/opt` 目录后，31 条小样本环境验证通过，再执行完整月场景。工具完整结果见 [JSON 证据](ci-capacity-2026-10-11.json)。

## 实测结果

| 独立 cgroup | 配额 | cgroup 内存峰值 | 结果 |
| --- | --- | --- | --- |
| 采集＋通知图片 | 128 MiB／15% CPU | 76.34 MiB | 图片成功；20 次采集及归档完成，最长单次 0.386 秒 |
| 定期月报＋图片 | 128 MiB／15% CPU | 123.05 MiB | 成功，31 天均有采样，未截断；106.501 秒 |
| Web 月历→月报→停车分析 | 256 MiB／25% CPU，MemoryHigh 192 MiB | 192.05 MiB | 组合任务触及测试的 600 秒预算，systemd Result=timeout，ExecMainStatus=15 |

全部 cgroup 的 oom、oom_kill 为 0。真实 Web、采集、报表服务的 MainPID 与 NRestarts 在测试前后相同，状态正常。验收 transient units 已停止、清理；正式服务未重启。总体 `passed=false`：核心月报与通知图片并发场景通过，额外 Web 顺序组合场景未完成。

600 秒是本次三个 Web 分析顺序执行的测试预算，不是已确认的单个 API 超时或用户接受的性能 SLA。由于 worker 在全部阶段结束后才返回完整计时，不能把 600 秒归给某一个分析。内存峰值是整个 cgroup，包含子进程和文件缓存，不能当作单进程 Python RSS。月报峰值距 128 MiB 上限约 4.95 MiB；成功代表本次合成负载通过，不能保证所有真实路线、数据组合或自然通知均通过。

## 后续性能线索

对同一合成库做只读分页诊断：首 512 条约 0.0005 秒，260000 条之后的一页约 0.0374 秒。两次查询计划均只显示 `scope_key、vehicle_key、observed_at 月区间` 的覆盖索引搜索，而非游标之后的直接边界定位。结合 `ArchiveReader._iter_rows` 的 OR 游标过滤，推测后续页反复扫描月区间前缀，是优先对照优化的候选；本轮没有修改分页逻辑，没有把它断言为全部耗时的唯一原因。

## 复现

将 `scripts/capacity_acceptance.py` 和 `tests/capacity_workload.py` 复制到服务器的独立 `/opt/zeekr-capacity-tools` 目录，保留 `tests/` 层级。不要放在 `/tmp` 或 `/var/tmp`，因为 PrivateTmp 会隐藏它们。output 必须是全新目录：

```sh
sudo python3 /opt/zeekr-capacity-tools/capacity_acceptance.py \
  --source /opt/zeekr-control/current \
  --worker /opt/zeekr-capacity-tools/tests/capacity_workload.py \
  --output /opt/zeekr-capacity-results-new
```

脚本先构造合成库，再启动三个独立受限任务。结果写入 output/result.json；失败返回非零。不要通过增加生产内存或 CPU 配额来掩盖验收失败。自然通知送达、真实网络查询和任意复杂路线不在本次合成验收范围。
