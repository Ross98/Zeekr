#!/bin/zsh
set -u
service_dir="${0:A:h}"
/usr/bin/python3 -B "$service_dir/管理工具/zeekr_manager.py" runtime
operation_result=$?
if [[ -t 0 ]]; then
    printf '\n按回车关闭此窗口…'
    IFS= read -r reply || true
fi
exit "$operation_result"
