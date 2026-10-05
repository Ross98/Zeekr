"""Prepare immutable release bundle; upload/deploy only via explicit subcommand."""
import argparse
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

import workflow

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]


def transport(path):
    argv = json.loads(Path(path).read_text())
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) for v in argv):
        raise ValueError('Transport must be a JSON argv list, without shell interpolation')
    return argv


def remote(argv, command, data=None, capture=False):
    started = time.monotonic()
    try:
        return subprocess.run(argv+[command], input=data, stdout=subprocess.PIPE if capture else None, check=True).stdout
    finally:
        print('TRANSPORT_SECONDS '+str(round(time.monotonic()-started, 3)), flush=True)


def prepare(args):
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError('Use a fresh output directory')
    output.mkdir(parents=True)
    source = (HERE/'workflow.py').read_text().replace("if __name__ == '__main__':", "if False:")+'\n'+(HERE/'snapshot.py').read_text()
    raw = remote(transport(args.transport), 'sudo python3 -', source.encode(), capture=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for member in archive.getmembers():
            name = member.name
            if name != 'baseline.json':
                if not name.startswith('staged/'):
                    raise ValueError('Unexpected snapshot entry')
                relative = name[len('staged/'):]
                if relative != 'release-manifest.json':
                    workflow.allowed(relative)
            if not member.isfile():
                raise ValueError('Snapshot may contain only regular public files')
        archive.extractall(output)
    root = output/'staged'
    paths = json.loads(Path(args.paths).read_text())
    for name in paths:
        workflow.allowed(name)
        data = subprocess.check_output(['git', 'show', args.commit+':'+name], cwd=REPOSITORY)
        destination = root/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    baseline = json.loads((output/'baseline.json').read_text())
    # Local tool scripts are kept outside the candidate and never implicitly committed.
    bundle = output/'bundle'
    workflow.build(root, output/'baseline.json', args.commit, baseline['active'],
                   '/opt/zeekr-control/releases/'+args.name, '/opt/zeekr-control/backups/'+args.name,
                   paths, json.loads(Path(args.checks).read_text()), bundle)
    for phase in ('workflow', 'server', 'stage', 'cutover', 'verify', 'rollback'):
        shutil.copyfile(HERE/(phase+'.py'), bundle/('.release-'+phase+'.py'))
    with tarfile.open(output/'upload.tar.gz', 'w:gz') as archive:
        for path in sorted(bundle.glob('.release-*')):
            archive.add(path, arcname=path.name, recursive=False)
    print('BUNDLE_READY '+str(output/'upload.tar.gz'))


def upload(args):
    installer = """import fcntl,io,pathlib,sys,tarfile,os
base=pathlib.Path('/opt/zeekr-control')
lock=(base/'.release-operation.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
ready=base/'.release-ready.json'
if ready.exists(): ready.unlink()
archive=tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode='r:gz')
allowed={'.release-'+n+'.py' for n in ['workflow','server','stage','cutover','verify','rollback']}|{'.release-'+n+'.json' for n in ['baseline','changes','config','receipt']}|{'.release-changes.tar'}
assert set(archive.getnames())==allowed
for m in archive.getmembers():
 assert m.isfile() and m.name in allowed
 m.uid=m.gid=0;m.uname=m.gname='root';m.mode=0o600
archive.extractall(base)
print('UPLOAD_READY')
"""
    import shlex
    remote(transport(args.transport), 'sudo python3 -c '+shlex.quote(installer), Path(args.bundle).read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prep = sub.add_parser('prepare')
    for name in ('transport', 'commit', 'paths', 'checks', 'output', 'name'):
        prep.add_argument('--'+name, required=True)
    up = sub.add_parser('upload')
    up.add_argument('--transport', required=True)
    up.add_argument('--bundle', required=True)
    for action in ('stage', 'deploy', 'verify', 'rollback'):
        command = sub.add_parser(action)
        command.add_argument('--transport', required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.name):
            raise ValueError('Release name must be a plain directory name')
        prepare(args)
    elif args.action == 'upload':
        upload(args)
    else:
        remote(transport(args.transport), 'sudo python3 /opt/zeekr-control/.release-server.py '+args.action)


if __name__ == '__main__':
    main()
