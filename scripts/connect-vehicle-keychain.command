#!/bin/zsh
set -eu
cd "${0:A:h:h}"
echo '极氪副账号连接：手机号、验证码仅在本机隐藏输入，不进入聊天。'
/usr/bin/python3 -m zeekr_control.connection_setup \
  --session "$HOME/Library/Application Support/ZeekrServer/state/Library/Application Support/ZeekrControl/session.json" login
echo '本机登录步骤结束；请返回 Codex 继续单次验证。'
read -r '?按回车关闭。'
