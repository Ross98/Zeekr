"""Zeekr management entry points; runtime stays on the internal APFS volume."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path.home() / 'Library/Application Support/ZeekrServer'
ACTIONS = ('status', 'health', 'start', 'stop', 'restart', 'rollback',
           'web', 'logs', 'backups', 'runtime', 'release-guide', 'password')
CONFIRMATIONS = {'stop': '停止', 'restart': '重启', 'rollback': '回退'}
NAMES = {'local.zeekr.web': '网页', 'local.zeekr.monitor': '采集与通知',
         'local.zeekr.reports': '周期报表', 'local.zeekr.resources': '资源巡检'}


def load_native():
    if sys.platform != 'darwin' or os.geteuid() == 0:
        raise ValueError('请在 mini 上以原服务用户运行，不要使用 sudo。')
    current = ROOT / 'current'
    active = current.resolve(strict=True)
    if not current.is_symlink() or active.parent != ROOT / 'releases':
        raise ValueError('当前版本路径异常；未操作服务。')
    helper = active / 'scripts/release/macos.py'
    if not helper.is_file():
        raise ValueError('当前版本缺少原生管理工具；未操作服务。')
    sys.path.insert(0, str(helper.parent))
    spec = importlib.util.spec_from_file_location('zeekr_native_release', helper)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    return native, native.Host(ROOT)


def public_status(native, host):
    source = native.inspect(host)
    return {key: source.get(key) for key in
            ('platform', 'active', 'base', 'state', 'origin', 'services', 'starts_at', 'tailscale_ip')}


def control(action, native, host, confirm=input):
    if action not in ('start', 'stop', 'restart', 'rollback'):
        raise ValueError('未知服务操作。')
    if action == 'rollback':
        record = native.read(host.base / '.macos-release.json')
        shown_active = host.active()
        print('当前版本：', shown_active)
        print('目标版本：', record['previous'])
        print('回退仅切换代码，保留最新业务数据。')
    if action in CONFIRMATIONS:
        word = CONFIRMATIONS[action]
        print('此操作会影响本套 Zeekr 的全部后台任务。')
        if confirm('输入“' + word + '”继续，其他输入取消：').strip() != word:
            print('已取消。')
            return False
    with native.lock(host):
        if action == 'rollback':
            locked_record = native.read(host.base / '.macos-release.json')
            if locked_record != record or host.active() != shown_active:
                raise ValueError('版本或发布记录已变化；已取消回退，请重新查看目标并确认。')
            # The original adapter validates versions, restores agents and
            # normalizes only delivery states proven safe for rollback.
            native.rollback(host, locked_record)
        else:
            if action in ('stop', 'restart'):
                host.stop()
            if action in ('start', 'restart'):
                host.start()
                host.health()
    print('操作完成。')
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description='管理当前 mini 的 Zeekr；不搬动运行文件。')
    parser.add_argument('action', choices=ACTIONS)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    native, host = load_native()
    if args.action == 'status':
        report = public_status(native, host)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print('实际运行版本：', report['active'])
            print('私网入口：', report['origin'])
            print('本机入口：http://127.0.0.1:18765/')
            print('启动方式：用户登录后启动')
            for label, job in report['services'].items():
                job = job or {}
                print(NAMES.get(label, label), '：', job.get('state', '未加载'),
                      ' PID=', job.get('pid', '—'), ' 启动次数=', job.get('runs', '—'), sep='')
    elif args.action == 'health':
        print('检查任务、实际进程目录、资源心跳、双入口认证和车型图片……', flush=True)
        host.health()
        host.artwork(host.active())
        print('健康检查通过。此检查不主动刷新车辆，也不发送测试通知。')
    elif args.action in ('start', 'stop', 'restart', 'rollback'):
        control(args.action, native, host)
    elif args.action == 'password':
        with native.lock(host):
            native.change_password(host)
    else:
        targets = {'web': host.origin, 'logs': host.base / 'logs',
                   'backups': host.base / 'backups', 'runtime': host.base,
                   'release-guide': host.active() / 'docs/macos-development.md'}
        subprocess.run(['/usr/bin/open', str(targets[args.action])], check=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('未完成：' + str(error), file=sys.stderr)
        print('请先运行“查看状态”，再按现有日志排查；不要重复启动多个副本。', file=sys.stderr)
        raise SystemExit(1)
