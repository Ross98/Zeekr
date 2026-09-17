# API 调研记录

核查日期：2026-09-17。

## 证据

1. 作者发布的国内 Node-RED 经验：<https://bbs.hassbian.com/thread-30209-1-1.html>。作者报告测试过老款 001 和 7X，提供 JWT、短信两种入口，并提示同账号登录会话冲突。正文可检索，流程附件隐藏，未获取附件。
2. 国内 Python 实现：<https://github.com/RexzeLu/zeekr_ha>。实际读取源码固定在 `316ce6e7ea718b3d5ba4597bf87627904add5330`，许可证 MIT。核心来源为 `custom_components/zeekr_ev/api_sms.py`。README 声称支持中国大陆；这不是我们的真实账号验证。
3. 海外实现：<https://github.com/Fryyyyy/zeekr_ev_api>。使用不同认证要求，未直接作为本项目依赖。

## 本版采用的链路

- GW1：`https://api-gw-toc.zeekrlife.com`
  - GET `/zeekrlife-app-user/v1/user/pub/sms/authCode`
  - POST `/zeekrlife-app-user/v1/user/pub/login/mobile`
  - GET `/zeekrlife-mp-auth2/v1/auth/accessCodeList`，取 `data.YIKAT_NEW`
- GW2：`https://api.zeekrline.com`
  - POST `/auth/account/session/secure?identity_type=zeekr`
  - GET `/device-platform/user/vehicle/secure`，包含 `needSharedCar=1`
  - GET `/remote-control/vehicle/status/{vin}`，`latest=Local`、`target=basic%2Cmore`

最后一个路径虽然含 remote-control，本版只用其 GET 缓存读取端点。客户端不包含控制操作、任意 URL 请求入口或第三网关探测。

签名 GW1 使用时间戳、nonce、应用常量排序 SHA1；GW2 使用 HMAC-SHA1，覆盖紧凑 JSON 的 MD5、查询参数、方法、路径等。签名与发送使用同一 body 字节。`target` 预编码按参考实现保留，不能二次编码。短信区号 `+86` 在 URL 中编码成 `%2B86`。

第三网关 `snc-tsp-api.zeekrlife.com` 的参考实现存在未授权错误处理、多种登录与 VIN 候选尝试；本版不移植这些试探逻辑。若 GW2 无法访问，将记录明确失败，需根据实际账号和当前 App 协议继续研究，不能据公开代码宣称已跑通。

## 2026-09-17 账号验证结果

用户提供的终端结果确认：短信发送、认证、分享车辆列表（shareStatus=Y）及 GW2 状态读取成功。样本的动力电池字段位于 additionalVehicleStatus.electricVehicleStatus，不能误用 maintenanceStatus.mainBatteryStatus 或 basicVehicleStatus.distanceToEmpty。updateTime 为毫秒时间戳，显示为北京时间。

已根据样本加入保守中文摘要和脱敏回归测试。门锁/充电/门窗枚举、胎压单位、状态新鲜度及会话有效期仍需与官方 App 对照；本版保留这些字段的原值。未执行任何车辆控制。


## 本车状态核对（2026-09-17）

胎压单位和轮位已通过接口与官方 App 对照核验。原始实车数值与截图仅保存在本机，不纳入仓库；详情保留接口小数，总览采用一位小数展示。

只在完整匹配已核对组合时翻译：centralLockingStatus=2 且四门 doorLockStatus=1 表示本车已锁车；chargeSts、chargerState、statusOfChargerConnection 均为 0 表示本车未充电；四门 doorOpenStatus=0、trunkOpenStatus=0、四窗 winPos=0 分别显示四门关闭、尾门关闭、四窗关闭。缺失、矛盾或其他状态码显示未知并附原值。尚未验证解锁、开门、开窗、充电中等反向状态，不从当前样本推断。不会将四窗关闭泛化成天窗或前舱盖已关闭。所有状态仍是云端缓存。
