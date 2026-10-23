# macOS 钥匙串与 GW2 续期

默认不启用自动续期。选用钥匙串、真实验证、自动开关是三个不同步骤；程序不会发送无人确认的短信。1509 仍先用原 accessToken 退避探测，不视作永久失效。

## 存储与后台权限

refreshToken 只经 Security.framework 原生 API 写入当前 uid 的 `login.keychain-db`。明确限定 service 和数据目录的引用前缀，不读写其他项目；不使用 shell 传递秘密，不同步 iCloud。read/write 均禁交互，锁定或拒绝时立即报不可用，不自动降级为明文。

服务 HOME 指向独立 state，不能据此查找默认钥匙串。实现按 uid 的真实用户目录打开 login 钥匙串，并明确指定查询搜索范围；已用实际 LaunchAgent 上下文验证读取。服务必须运行在对应登录用户下。未登录、钥匙串未解锁或系统重启后的可用性独立于程序启动，不能声称登录前可用。

现有 accessToken/userId/clientId/deviceId 继续存于 600 会话文件以保持读路径及旧版本兼容。session 和 700 目录内的 600 暂存候选仅含续期引用、指纹及提交版本；协调库不含 Token 值。成功提交后删除冗余候选文件；旧钥匙串项目保留作版本取证，不因退出而云端撤销。

## 本机连接与一次验证

在 mini 的项目目录双击 `scripts/connect-vehicle-keychain.command`。手机号、验证码仅在终端隐藏输入。入口使用 `/usr/bin/python3`，与服务一致；不要将验证码发到聊天，也不保存 JWT。

显式命令等价如下（session 应指向实际私有数据目录）：

```sh
/usr/bin/python3 -m zeekr_control.connection_setup --session "$SESSION_PATH" login
/usr/bin/python3 -m zeekr_control.connection_setup --session "$SESSION_PATH" probe
/usr/bin/python3 -m zeekr_control.connection_setup --session "$SESSION_PATH" validate
```

login 选择 provider 并保持自动开关关闭；沿用同账号与绑定车辆校验。validate 在网络前保存一次验证意图，经持久占位和查询保护，只发一次 refresh；无明确未发送证据时不再发。已成功提交而尚未核对 status 时，重复 validate 只恢复受保护读取，不再次刷新。待 status 实际请求返回结构有效的成功响应才写验证通过；列表成功、缓存命中不算。车辆状态时间可能仍旧，不等同实时车辆恢复或缺失数据已补齐。

首次真实 PUT 刷新成功，返回凭据落盘，绑定车辆实际 status 成功，但未取得不同的新 refreshToken；该成功本身不授予重放资格。随后用户另行授权一次受控复用试验：同一 refreshToken 再次 PUT 成功、凭据落盘、目标车辆实际 status 成功。只据此确认本账号这次可复用，不保证永久有效或无限次数。

复用依据由 `refresh_reuse_trials` 与 `refresh_reuse_contracts` 独立记录，绑定 Token 指纹、一次授权、实际已提交操作及确认读取的会话。自动续期只允许 eligible 的新 Token，或 completed 且有实测依据并已确认当前会话实际读取的同一 Token。后续每次刷新提交都会使确认 scope 过期，必须等该会话实际 status 成功才能再次取得资格；缓存不算。unknown/rejected 不受复用依据解禁。429／明确未发送恢复的是原资格，不能把已使用 Token 改成新 Token。受控试验入口另存先行意图，不能重复执行去多发请求。

`connection-policy.json` 初始 provider 为 keychain、自动开关 false。启用条件绑定 `connection-validation.json` 的真实验证、当前会话，以及不同的新 Token 或上述已验证的复用依据；不能靠改开关文件绕过指纹禁重放。unknown/rejected 标记跨进程、重启及 accessToken 自愈保留。通过精确候选及发布门禁后显式 enable，再由新服务读取策略。

## 备份、回退与恢复

固定发布工具在停服后备份整个 state 并校验；包含活动读会话、候选引用、意图和中断库。refreshToken 不导出到普通备份，不为备份绕过钥匙串保护。机器迁移／钥匙串丢失时重新短信登录；若需要钥匙串整体备份，按 macOS 用户级备份方式另行处理。

回退代码不能回滚业务数据或用旧 Token 覆盖现会话。回退到不认识占位协议的旧版本前，必须确认无活跃凭据交换，完成／安全终结遗留意图。旧读代码仍能使用兼容 accessToken，但不会处理续期。不重发 sending/uncertain 通知，不重建缺失轨迹。

原生 API 依据：[SecItemCopyMatching](https://developer.apple.com/documentation/security/secitemcopymatching(_:_:))、[禁用用户交互](https://developer.apple.com/documentation/security/seckeychainsetuserinteractionallowed(_:))。实现只作用于本应用明确命名的项目。
