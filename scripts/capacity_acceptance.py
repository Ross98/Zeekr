"""Run isolated synthetic capacity workers on the production Linux host as root.

Copy this script and tests/capacity_workload.py outside the active release.
Workload imports use --source, so no production code or data is overwritten.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import time


def properties(unit):
    result = subprocess.check_output(['systemctl', 'show', unit,
        '-p', 'MainPID', '-p', 'NRestarts', '-p', 'Result', '-p', 'ExecMainStatus',
        '-p', 'ActiveState', '-p', 'SubState', '-p', 'MemoryPeak', '-p', 'MemoryMax', '-p', 'MemoryHigh',
        '-p', 'CPUQuotaPerSecUSec', '-p', 'CPUUsageNSec', '-p', 'ControlGroup'], text=True)
    return dict(line.split('=', 1) for line in result.splitlines() if '=' in line)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--worker', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--records', type=int, default=267840)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Run as root to create isolated systemd units')
    source, worker, output = args.source.resolve(), args.worker.resolve(), args.output.resolve()
    output.mkdir(mode=0o700)
    owner = pwd.getpwnam('zeekr-control')
    os.chown(output, owner.pw_uid, owner.pw_gid)
    root = output / 'synthetic'
    env = dict(os.environ, PYTHONPATH=str(source)+':'+str(source/'tests'), PYTHONDONTWRITEBYTECODE='1')
    production = ['zeekr-control', 'zeekr-monitor', 'zeekr-reports']
    before = {unit: properties(unit) for unit in production}
    with (output / 'prepare.json').open('w') as log:
        subprocess.run(['sudo', '-u', 'zeekr-control', 'env', 'PYTHONPATH='+env['PYTHONPATH'],
            'PYTHONDONTWRITEBYTECODE=1', 'python3', str(worker), '--task', 'prepare',
            '--root', str(root), '--records', str(args.records)], stdout=log, check=True)
    # Evict only synthetic fixture pages, never global production caches.
    for path in root.rglob('*.sqlite3'):
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
            os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    prefix = 'zeekr-capacity-'+str(os.getpid())
    units, samples, final = {}, {}, {}
    specs = {'monitor': 'zeekr-monitor', 'month': 'zeekr-reports', 'web': 'zeekr-control'}
    barrier = root / 'start'
    try:
        for task, service in specs.items():
            config = before[service]
            if config['MemoryMax'] == 'infinity':
                raise ValueError('Production memory limit is missing')
            unit = prefix+'-'+task
            units[task] = unit
            samples[task] = {'oom': 0, 'oom_kill': 0, 'peak_bytes': 0}
            subprocess.run(['systemd-run', '--quiet', '--unit='+unit,
                '-p', 'User=zeekr-control', '-p', 'Group=zeekr-control',
                '-p', 'WorkingDirectory='+str(source), '-p', 'RemainAfterExit=yes',
                '-p', 'Restart=no', '-p', 'MemoryMax='+config['MemoryMax'],
                '-p', 'MemoryHigh='+config['MemoryHigh'],
                '-p', 'MemorySwapMax=0', '-p', 'CPUQuota='+str(float(config['CPUQuotaPerSecUSec'].removesuffix('ms'))/10)+'%',
                '-p', 'TasksMax='+('64' if task=='web' else '16'),
                '-p', 'RuntimeMaxSec=600', '-p', 'PrivateNetwork=yes',
                '-p', 'PrivateTmp=yes',
                '-p', 'NoNewPrivileges=yes', '-p', 'ProtectSystem=strict',
                '-p', 'ProtectHome=yes', '-p', 'ReadWritePaths='+str(output),
                '-p', 'StandardOutput=file:'+str(output/(task+'.json')),
                '-p', 'StandardError=file:'+str(output/(task+'.stderr')),
                '--setenv=PYTHONPATH='+env['PYTHONPATH'], '--setenv=PYTHONDONTWRITEBYTECODE=1',
                '/usr/bin/python3', str(worker), '--task', task, '--root', str(root),
                '--barrier', str(barrier)], check=True)
        deadline = time.monotonic()+50
        while not all((root/(task+'.ready')).exists() for task in specs):
            if time.monotonic()>deadline:
                raise TimeoutError('Workers did not reach start barrier')
            time.sleep(0.2)
        barrier.touch()
        print('CONCURRENT_WORKLOAD_STARTED', flush=True)
        deadline = time.monotonic()+600
        while len(final)<len(units):
            for task, unit in units.items():
                if task in final:
                    continue
                state = properties(unit)
                group = Path('/sys/fs/cgroup') / state['ControlGroup'].lstrip('/')
                events = group / 'memory.events'
                if events.exists():
                    values = dict(line.split() for line in events.read_text().splitlines())
                    for key in ('oom', 'oom_kill'):
                        samples[task][key] = max(samples[task][key], int(values[key]))
                peak = state.get('MemoryPeak', '')
                if peak.isdigit():
                    samples[task]['peak_bytes'] = max(samples[task]['peak_bytes'], int(peak))
                if state['SubState'] == 'exited' or state['ActiveState'] in ('failed', 'inactive'):
                    final[task] = dict(state=state, memory=samples[task])
                    path = output / (task+'.json')
                    try:
                        final[task]['workload'] = json.loads(path.read_text())
                    except (ValueError, OSError):
                        final[task]['workload'] = None
                    print(json.dumps({'completed': task, **final[task]}), flush=True)
            if time.monotonic()>deadline:
                raise TimeoutError('Acceptance exceeded 600 seconds')
            time.sleep(1)
        after = {unit: properties(unit) for unit in production}
        stable = all(before[u]['MainPID']==after[u]['MainPID'] and
            before[u]['NRestarts']==after[u]['NRestarts'] and after[u]['ActiveState']=='active'
            for u in production)
        passed = stable and all(row['state']['Result']=='success' and row['state']['ExecMainStatus']=='0'
            and row['memory']['oom']==0 and row['memory']['oom_kill']==0
            and 0 < row['memory']['peak_bytes'] <= int(row['state']['MemoryMax'])
            and row['workload'] is not None for row in final.values())
        evidence = dict(passed=passed, production_stable=stable, source=str(source),
            records=args.records, source_commit=json.loads((source/'release-manifest.json').read_text())['base_version'],
            units=final, production_before=before, production_after=after,
            network_disabled=True, production_data_used=False, swap_disabled=True)
        (output/'result.json').write_text(json.dumps(evidence, indent=2)+'\n')
        print('CAPACITY_ACCEPTANCE_'+('PASS' if passed else 'FAIL'), flush=True)
        if not passed:
            raise SystemExit(1)
    finally:
        for unit in units.values():
            subprocess.run(['systemctl', 'stop', unit], check=False, stdout=subprocess.DEVNULL)
            subprocess.run(['systemctl', 'reset-failed', unit], check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
