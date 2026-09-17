#!/bin/bash
# macOS double-click launcher. No credentials are stored here.
ssh -t ubuntu@124.222.221.173 sudo /usr/local/sbin/zeekr-password
result=$?
if [ "$result" -ne 0 ]; then
    echo "操作未完成（退出码 $result），请查看上方提示。"
fi
read -r -p '按回车关闭窗口…' ignored
exit "$result"
