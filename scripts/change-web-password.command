#!/bin/bash
# Run locally on the Mac mini. Password never travels through SSH or argv.
set -u
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
/usr/bin/python3 "$SCRIPT_DIR/release/client.py" macos password
result=$?
if [ "$result" -ne 0 ]; then
    printf '操作未完成（退出码 %s）。须在 mini 本机交互终端运行。\n' "$result"
fi
read -r -p '按回车关闭窗口…' ignored
exit "$result"
