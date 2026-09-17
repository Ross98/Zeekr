# 自动行程与充电通知

后台每 60 秒读取缓存车辆状态。有效车速或连续里程增长触发行程记录；明确下电后，新的连续观测确认经过十分钟，才发送总结。充电开始与停止分别发送通知。关闭网页不会停止自动监控；网页手动采集与自动监控是两个独立功能。

## 配置和启动

将已创建的企业微信群机器人 Webhook 保存到应用数据目录的 `wecom-webhook.json`，字段为 `webhook_url`。应用数据目录必须归运行用户所有且权限 700，文件权限 600。不要把此文件放进 Git、截图、日志或命令行参数。

本机应用数据目录是 `~/Library/Application Support/ZeekrControl`；部署模板的服务用户目录是 `/var/lib/zeekr-control/Library/Application Support/ZeekrControl`。

```bash
python3 -m zeekr_control monitor
python3 -m zeekr_control monitor-status
```

首条命令持续运行；第二条只读取状态，不查询车辆或发送消息。`monitor --once` 会检查一次车辆并处理待发通知，不是无副作用的测试模式。单车首次自动绑定车辆摘要；多车首次使用 `--vehicle 序号`。绑定后按身份选择，不因列表重排或换账号而静默换车。确认换车时停止服务并备份、移走 `monitor-binding.json`，再明确选择新车。

企业微信纯文本通知不含 VIN、经纬度、账号或登录链接。SSH 隧道网页无法从普通手机直接访问，因此本版不发送不可用的轨迹链接；轨迹在现有网页中查看。

## 服务器服务

在已准备代码和配置的服务器安装 `deploy/zeekr-monitor.service`，然后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zeekr-monitor
sudo systemctl status zeekr-monitor --no-pager
sudo -u zeekr-control env HOME=/var/lib/zeekr-control sh -c 'cd /opt/zeekr-control/current && python3 -m zeekr_control monitor-status'
```

网页设置页显示后台健康状态和最近通知。`stale` 表示缓存太旧，`unchanged` 表示未取得更晚的车辆状态，均不代表车辆当前静止。网络故障退避重试，429 遵守冷却；会话失效暂停请求，更新同一路径的会话文件后恢复，或处理问题后重启监控。服务端会话须使用服务用户权限保存。

停止和恢复：

```bash
sudo systemctl stop zeekr-monitor
sudo systemctl start zeekr-monitor
```

停用开机自动运行：`sudo systemctl disable --now zeekr-monitor`。独立监控不更改网站、SSH、Nginx、防火墙或公司官网配置。

## 数据准确性

- 云端缓存延迟会推迟通知；车辆休眠后不再上传新状态时，十分钟确认会延后，而不会靠重复旧缓存宣布行程结束。
- 里程以起止总里程差计算，耗时含途中堵车和等灯，不含结束后的通知等待时间。只有部分观测时注明不完整。没有 kWh 数据时仅报电量百分点，不能把电池容量乘电量变化当作精确耗电。
- 下电要求 `engineStatus=engine_off` 与 `ptReady=0` 同时满足。上电或未知状态会取消当前结束确认，行程保留；有效移动证据不会被零速/旧动力状态覆盖。
- 电流、电压回充不能单独识别外接充电（可能涉及动能回收或缓存）。直流充电采用本车已核验组合：直流口盖 chargeLidDcAcStatus=1、chargerState=24、dcChargeSts=12，且桩侧电压与桩侧电流均有效且大于零。明确文字状态或配置的充电状态码也必须结合已确认打开的口盖。与有效行驶/动力就绪信号冲突时保持待确认。首次观测就处于充电中时，不声称知道真实开始时间。
- 直流组合优先，不能被通用充电码、连接码或通用电流为零覆盖。未充电使用已核验的三项全零组合或明确停止状态，且必须排除直流侧活动、非法字段及冲突。直流口盖 2=关闭；交流口盖只核验过 2=关闭，未推定交流打开码，交流自动识别暂待校准。插枪未充电、电流瞬间为零、未知数字状态码不直接触发开始或停止。因此某些“充完但未拔枪”的数字状态需要实车校准，否则停止总结可能延至拔枪后的确认观测。
- `--charging-active-code` / `--charging-stopped-code` 只接收本车实测核验后的 `chargeSts`，可重复提供。社区枚举明确标为经验性，不作为所有非零状态均为充电的依据。字段参考：[固定版本解析器](https://github.com/RexzeLu/zeekr_ha/blob/316ce6e7ea718b3d5ba4597bf87627904add5330/custom_components/zeekr_ev/parser.py)。
- 轨迹为有效缓存采样点；不反推未采集路段。状态和通知存入现有私有 `tracks.sqlite3`，Webhook 不进入数据库。

## 通知可靠性与验证

成功响应写入后不会重发。明确的临时拒绝退避重试，最多六次；永久拒绝标记失败。超时、无效响应或发送中进程中断标记 `uncertain`，人工核对群内事件编号后处理，不自动重复发送。群机器人没有客户端幂等键，不能承诺绝对不丢且绝对不重复。

```bash
python3 -m unittest discover -s tests -v
node --check zeekr_control/static/app.js
```

测试使用合成数据，覆盖开始/停止、重复/陈旧/未来缓存、断点恢复、发送重试及车辆绑定。实车需要分别核验一次行驶至下电、一次充电至停止，记录对应原始状态码及实际通知时间；后台运行成功不等于这些实车场景已经验收。
