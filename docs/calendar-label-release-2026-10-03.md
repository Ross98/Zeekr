# 日历金额标记精简 · 发布

用户明确授权 commit、部署。功能提交 `386a0d9`，仅日历脚本与对应浏览器断言；移除日期格右上金额后的“部分”两字，保留悬停/无障碍描述、当天详情及成本算法。

基线 `7d3fb0e` / `20261003-calendar-consumption` 的所有应用代码哈希匹配。候选复制 current/.，只覆盖两文件，全部已跟踪应用源码匹配提交。正式服务账号全量 Python 776 项通过，75.211 秒；图片门禁和 12 项发布功能匹配通过。此前合成成本浏览器验证无角标文字且详情保留限定。

活动版本 `/opt/zeekr-control/releases/20261003-calendar-label`；回滚 `/opt/zeekr-control/releases/20261003-calendar-consumption`；备份 `/opt/zeekr-control/backups/20261003-calendar-label`。持发布锁原子切换，仅重启 Web；Web、monitor、nginx active，两个应用 NRestarts=0。文件哈希、进程目录、根页 200、日历/账本等私有接口及脚本 401 通过。

切换前后只读正式数据核对成本、实际账本、范围和个人记录版本，均通过；未请求实车、修改账本或发送通知。登录会话重置。未另验正式登录后的浏览器，未 push。
