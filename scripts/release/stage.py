"""Run on release host as root, before switching current."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

base = Path('/opt/zeekr-control')
with (base/'.deploy.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    config = json.loads((base/'.release-config.json').read_text())
    baseline = json.loads((base/'.release-baseline.json').read_text())
    changes = json.loads((base/'.release-changes.json').read_text())
    receipt = json.loads((base/'.release-receipt.json').read_text())
    current = (base/'current').resolve()
    candidate = Path(config['candidate'])
    assert str(current) == baseline['active'] == config['previous'], 'Active release changed'
    assert candidate.parent == base/'releases' and candidate != current, 'Invalid candidate path'
    assert Path(config['backup']).parent == base/'backups', 'Invalid backup path'
    for name, value in baseline['manifest'].items():
        assert hashlib.sha256((current/name).read_bytes()).hexdigest() == value, 'Baseline drift: '+name
    assert not candidate.exists(), 'Candidate already exists; validate it explicitly, do not overwrite'
    assert shutil.disk_usage(base).free > 1024**3, 'Insufficient release space'
    candidate.mkdir()
    subprocess.run(['cp', '-a', str(current)+'/.', str(candidate)], check=True)
    with tarfile.open(base/'.release-changes.tar') as archive:
        assert set(archive.getnames()) == set(changes)
        for member in archive.getmembers():
            assert member.isfile() and not member.name.startswith('/') and '..' not in Path(member.name).parts
            target = candidate/member.name
            assert not target.is_symlink() and candidate.resolve() in target.resolve().parents, 'Symlink target rejected'
            member.uid = member.gid = 0
            member.uname = member.gname = 'root'
            member.mode = 0o644
        archive.extractall(candidate)
    for name, value in changes.items():
        assert hashlib.sha256((candidate/name).read_bytes()).hexdigest() == value, 'Overlay mismatch'
    for name, value in baseline['manifest'].items():
        if name not in changes and name != 'release-manifest.json':
            assert hashlib.sha256((candidate/name).read_bytes()).hexdigest() == value, 'Unrelated change'
    for source in [current, *current.rglob('*')]:
        destination = candidate/source.relative_to(current)
        if destination.exists() or destination.is_symlink():
            info = source.lstat()
            os.chown(destination, info.st_uid, info.st_gid, follow_symlinks=False)
            if not source.is_symlink():
                os.chmod(destination, info.st_mode & 0o7777)
    sys.path.insert(0, str(candidate))
    from zeekr_control.release_info import write_manifest, read_release
    write_manifest(candidate, config['commit'], list(json.loads((current/'release-manifest.json').read_text())['features']))
    metadata = read_release(candidate)
    assert metadata['status'] == 'recorded' and all(f['status'] == 'matched' for f in metadata['features'])
    subprocess.run(['sudo', '-u', 'zeekr-control', 'env', 'HOME=/var/lib/zeekr-control', 'python3', str(base/'check-release.py'), str(candidate), '--require-image', '--service-user', 'zeekr-control'], check=True)
    # Risk is recomputed here, rather than trusting a config asking to skip tests.
    sys.path.insert(0, str(base))
    import importlib.util
    spec = importlib.util.spec_from_file_location('release_workflow', base/'.release-workflow.py')
    workflow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workflow)
    tier = workflow.risk(list(changes))
    assert tier == config['risk'], 'Risk configuration mismatch'
    if tier == 'ui':
        assert receipt['passed'] and workflow.browser_checks(receipt['commands']), 'Missing browser validation'
        assert set(workflow.inputs(candidate)) == set(receipt['hashes']), 'Candidate input set differs'
        for name, value in receipt['hashes'].items():
            assert hashlib.sha256((candidate/name).read_bytes()).hexdigest() == value, 'UI validation invalidated'
        print('EXACT_TREE_UI_VALIDATION_PASS; full Python suite not required', flush=True)
    else:
        command = ['sudo', '-u', 'zeekr-control', 'env', 'HOME=/var/lib/zeekr-control', 'PYTHONDONTWRITEBYTECODE=1', 'python3', '-m', 'unittest', 'discover', '-s', 'tests']
        workflow.validate(candidate, workflow.inputs(candidate), [command], base/'.release-server-validation.json', context='service-user-candidate')
    candidate_hashes = {name: hashlib.sha256((candidate/name).read_bytes()).hexdigest() for name in set(workflow.inputs(candidate)+list(changes)+['release-manifest.json'])}
    (base/'.release-ready.json').write_text(json.dumps(dict(config, features=len(metadata['features']), candidate_hashes=candidate_hashes)))
    print('CANDIDATE_READY', flush=True)
