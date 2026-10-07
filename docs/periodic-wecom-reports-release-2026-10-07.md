# 企业微信定期用车报表启用 · 2026-10-07

用户批准已有图片样式、六张底图预渲染方案，确认北京时间日报08:00、周一周报08:10、每月1日月报08:20，并明确要求“启用”。

- 实现提交：`f84eb2b3abf7a4ab31fbe30939eb68a2ec34393c`，分支 `codex/notification-reference-location`，未push。
- 当前发布：`/opt/zeekr-control/releases/20261007-periodic-reports-f84eb2b`。
- 上一版/回滚：`/opt/zeekr-control/releases/20261007-trip-image-0b5c109`。
- 停服备份：`/opt/zeekr-control/backups/20261007-periodic-reports-f84eb2b`。
- 固定发布工具：`scripts/release/client.py`。26指定路径；资产构建脚本只进Git，不作为服务器运行依赖。小组件试验和14项无关CJS修改未混入。

## 行为

独立 `zeekr-reports.service` 已安装、enabled、active/running，开机自启，15% CPU/128MiB限制。30秒到期检查，使用车辆缓存和历史结束记录，不请求车辆云接口。日报报昨天，周报报上周一至周日，月报报上个自然月。

首次启用时间避免追补历史；只处理当天到期且处于6小时窗口内的任务。独立持久投递表冻结报表与主题，120秒重试间隔、最多3次；明确永久失败停止，发送不明/中断不自动重放。先图片准备、再文字、再图片；图片准备失败文字照发。默认亮色。发布和回滚将已安装报表服务纳入停服备份/切换；旧版不支持时停报表，设置与投递数据保留。

## 验证

- 本机21项报表/调度专项、15项发布工具检查通过；原汇总/企业微信覆盖也在服务器全量内。
- 生产匹配候选实际服务用户全量一次，退出0，120.249秒；stage120.955秒、切换1.600秒、上线验收0.953秒。
- 部署26路径和完整候选哈希通过，原三服务NRestarts=0，根页200、保护API/资源401、图片门禁、功能清单、私人记住登录库和道路库通过。
- 原99条sent事件、38条sent图片逐项保留，未重发。
- 单元先经过systemd-analyze verify，再从已校验active/deploy安装，安装文件与候选源哈希一致。服务用户CLI启用设置后systemctl enable --now。
- 启用后四服务均active/running、NRestarts=0，应用三进程cwd匹配新发布；报表配置/健康文件owner和600权限通过，健康状态ready，15% CPU/128MiB系统限额通过。
- 启用时无到期历史任务，投递表为空，未即时发送。服务读到的下一次时点：日报2026-10-08 08:00、周报2026-10-12 08:10、月报2026-11-01 08:20，均北京时间。
- 预渲染图片此前在相同限额下六图1.203–1.302秒/图；真实历史汇总日/周/月0.491/1.899/1.995秒，出图约1.2秒。属于离线生成证据，不代表企业微信收件验收。

代码发布和服务启用已验证。首份自然触发、实际企业微信收图尚未发生，不能声称已收件。

本机证据：`/tmp/zeekr-periodic-release-20261007-final/` 的upload/stage/deploy日志与activation-verification.json；输入在同名-inputs目录。服务器全量指纹在 `/opt/zeekr-control/.release-server-validation.json`，阶段计时在 `.release-timings.jsonl`。图片限额证据在私有预览目录 `periodic-report/resource-evidence.json`。
