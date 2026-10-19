"""Run isolated synthetic capacity workers on the production Linux host as root.

Copy this script and tests/capacity_workload.py outside the active release.
Workload imports use --source, so no production code or data is overwritten.
"""
import argparse
import hashlib
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


def sample_memory(group, sample):
    memory_stat = None
    for name, keys in (('memory.events', ('high', 'max', 'oom', 'oom_kill')),
                       ('memory.stat', ('anon', 'file'))):
        try:
            values = dict(line.split() for line in (group / name).read_text().splitlines())
        except OSError:
            continue
        if name == 'memory.stat':
            memory_stat = {key: int(value) for key, value in values.items()}
        for key in keys:
            label = key if name == 'memory.events' else key+'_peak_bytes'
            sample[label] = max(sample.get(label, 0), int(values.get(key, 0)))
    try:
        current = int((group / 'memory.current').read_text())
        if current > sample.get('current_peak_bytes', 0):
            sample['current_peak_bytes'] = current
            sample['stat_at_sampled_peak'] = memory_stat
    except OSError:
        pass


def workload_passed(row, minimum_headroom_percent=20):
    limit = row['state']['MemoryMax']
    return (row['state']['Result'] == 'success' and row['state']['ExecMainStatus'] == '0'
            and row['workload'] is not None and limit.isdigit()
            and row['memory']['oom'] == 0 and row['memory']['oom_kill'] == 0
            and row['memory'].get('max') == 0
            and 0 < row['memory']['peak_bytes']*100 <= int(limit)*(100-minimum_headroom_percent))


def source_hashes(source):
    """Use the release public-input allowlist; never hash/export runtime secrets."""
    import runpy
    workflow=runpy.run_path(str(source/'scripts/release/workflow.py'))
    return {name:hashlib.sha256((source/name).read_bytes()).hexdigest()
            for name in workflow['inputs'](source)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--worker', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--records', type=int, default=267840)
    parser.add_argument('--tasks',nargs='+',choices=['monitor','month','web'],default=['monitor','month','web'])
    parser.add_argument('--scenario',choices=['standard','complex'],default='standard')
    parser.add_argument('--minimum-headroom-percent',type=int,default=20)
    args = parser.parse_args()
    if not 1<=args.minimum_headroom_percent<=90:raise ValueError('Headroom must be 1..90 percent')
    if os.geteuid() != 0:
        raise ValueError('Run as root to create isolated systemd units')
    source, worker, output = args.source.resolve(), args.worker.resolve(), args.output.resolve()
    output.mkdir(mode=0o700)
    owner = pwd.getpwnam('zeekr-control')
    os.chown(output, owner.pw_uid, owner.pw_gid)
    initial_inputs=source_hashes(source)
    root = output / 'synthetic'
    env = dict(os.environ, PYTHONPATH=str(source)+':'+str(source/'tests'), PYTHONDONTWRITEBYTECODE='1')
    production = ['zeekr-control', 'zeekr-monitor', 'zeekr-reports']
    before = {unit: properties(unit) for unit in production}
    with (output / 'prepare.json').open('w') as log:
        subprocess.run(['sudo', '-u', 'zeekr-control', 'env', 'PYTHONPATH='+env['PYTHONPATH'],
            'PYTHONDONTWRITEBYTECODE=1', 'python3', str(worker), '--task', 'prepare',
            '--root', str(root), '--records', str(args.records),'--scenario',args.scenario], stdout=log, check=True)
    # Evict only synthetic fixture pages, never global production caches.
    for path in root.rglob('*.sqlite3'):
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
            os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    prefix = 'zeekr-capacity-'+str(os.getpid())
    units, samples, final = {}, {}, {}
    specs = {'monitor': 'zeekr-monitor', 'month': 'zeekr-reports', 'web': 'zeekr-control'}
    specs={task:specs[task] for task in dict.fromkeys(args.tasks)}
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
        # Workers keep the 600-second budget. Allow systemd termination to be
        # observed before collecting the failure evidence and cleaning up.
        deadline = time.monotonic()+630
        while len(final)<len(units):
            for task, unit in units.items():
                if task in final:
                    continue
                state = properties(unit)
                group = Path('/sys/fs/cgroup') / state['ControlGroup'].lstrip('/')
                if state['ControlGroup']:
                    sample_memory(group, samples[task])
                peak = state.get('MemoryPeak', '')
                if peak.isdigit():
                    samples[task]['peak_bytes'] = max(samples[task]['peak_bytes'], int(peak))
                if state['SubState'] == 'exited' or state['ActiveState'] in ('failed', 'inactive'):
                    if state['MemoryMax'].isdigit():
                        samples[task]['headroom_bytes']=int(state['MemoryMax'])-samples[task]['peak_bytes']
                    final[task] = dict(state=state, memory=samples[task])
                    path = output / (task+'.json')
                    try:
                        final[task]['workload'] = json.loads(path.read_text())
                    except (ValueError, OSError):
                        final[task]['workload'] = None
                    if task == 'web':
                        try:
                            final[task]['progress'] = json.loads((root/'web-progress.json').read_text())
                        except (ValueError, OSError):
                            final[task]['progress'] = None
                    print(json.dumps({'completed': task, **final[task]}), flush=True)
            if time.monotonic()>deadline:
                raise TimeoutError('Workers did not terminate after the 600-second budget')
            time.sleep(1)
        after = {unit: properties(unit) for unit in production}
        stable = all(before[u]['MainPID']==after[u]['MainPID'] and
            before[u]['NRestarts']==after[u]['NRestarts'] and after[u]['ActiveState']=='active'
            for u in production)
        source_stable=initial_inputs==source_hashes(source)
        passed = stable and source_stable and all(workload_passed(row,args.minimum_headroom_percent) for row in final.values())
        evidence = dict(passed=passed, production_stable=stable, source=str(source),
            records=args.records, source_commit=json.loads((source/'release-manifest.json').read_text())['base_version'],
            units=final, production_before=before, production_after=after,
            network_disabled=True, production_data_used=False, swap_disabled=True)
        origin=source/'.capacity-origin.json'
        revision=json.loads(origin.read_text()) if origin.exists() else {}
        evidence['source_base_commit']=evidence['source_commit']
        evidence['source_commit']=revision.get('commit',evidence['source_commit'])
        evidence['source_input_hashes']=initial_inputs
        evidence['source_inputs_stable']=source_stable
        evidence['workload_budget_seconds'] = 600
        evidence['minimum_headroom_percent']=args.minimum_headroom_percent
        evidence['scenario']=args.scenario
        evidence['tasks']=list(specs)
        evidence['production_cache_purged']=False
        evidence['synthetic_cache_policy']='only newly generated fixture SQLite files'
        evidence['source_archive_reader_sha256'] = hashlib.sha256(
            (source/'zeekr_control/archive_reader.py').read_bytes()).hexdigest()
        evidence['harness_sha256'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in (Path(__file__), worker)}
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
