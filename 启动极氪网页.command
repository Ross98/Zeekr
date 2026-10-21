#!/bin/bash
# Open the Mac mini dashboard; no cloud service start, private key or SSH tunnel.
set -u
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
/usr/bin/python3 "$SCRIPT_DIR/scripts/open-dashboard.py"
result=$?
if [ "$result" -ne 0 ]; then
    printf '打开失败。检查 Tailscale 连接和网页地址配置。\n'
    read -r -p '按回车关闭窗口…' ignored
fi
exit "$result"
