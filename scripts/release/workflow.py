"""Reusable release planning, exact-tree validation and bundle generation.

No credentials discovery; no commit, SSH or production mutation on import.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import time
import os
import shutil
import sys


def allowed(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path) != name:
        raise ValueError('Unsafe release path: '+name)
    permitted = (
        (name.startswith('zeekr_control/') and path.suffix in {'.py', '.js', '.css', '.html', '.svg', '.png', '.webp', '.woff2', '.gz', '.zlib', '.txt', '.md'})
        or (name.startswith('tests/') and path.suffix in {'.py', '.cjs', '.js'})
        or (name.startswith('tests/fixtures/') and path.suffix == '.json')
        or name in {'AGENTS.md', 'zeekr_control/parameter_dictionary.json', 'zeekr_control/vehicle_profiles.example.json'}
        or (name.startswith('scripts/release/') and path.suffix == '.py')
        or (name.startswith('docs/') and path.suffix == '.md')
    )
    if not permitted:
        raise ValueError('Path outside release allowlist: '+name)
    return name


def risk(files, deleted=()):
    if deleted:
        return 'full'
    runtime = False
    for name in files:
        path = PurePosixPath(name)
        if name.startswith(('tests/', 'docs/')):
            continue
        runtime = True
        if not (name.startswith('zeekr_control/static/') and path.suffix in {'.js', '.css', '.png', '.svg', '.webp', '.woff2'}):
            return 'full'
        if path.stem in {'login', 'navigation-state'}:
            return 'full'
    return 'ui' if runtime else 'full'


def browser_checks(commands):
    return any(isinstance(command, list) and len(command) >= 2
               and Path(command[0]).name == 'node'
               and command[1].startswith('tests/ui_') and command[1].endswith('.cjs')
               for command in commands)


def fingerprint(root, files, commands, context):
    executables = {}
    for program in [sys.executable]+[command[0] for command in commands]:
        resolved = shutil.which(program)
        if resolved:
            info = Path(resolved).stat()
            executables[program] = [str(Path(resolved).resolve()), info.st_size, info.st_mtime_ns]
    environment = {name: os.environ.get(name) for name in ('PATH', 'PYTHONPATH', 'NODE_PATH', 'CHROMIUM_EXECUTABLE', 'PLAYWRIGHT_BROWSERS_PATH')}
    payload = {'files': {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sorted(files)},
               'executables': executables, 'environment': environment, 'commands': commands, 'context': [context, str(root.resolve()), sys.version, tuple(os.uname()), os.geteuid()], 'version': 1}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate(root, files, commands, report, context='local'):
    root, report = Path(root), Path(report)
    if not commands or any(not isinstance(c, list) or not c or not all(isinstance(x, str) for x in c) for c in commands):
        raise ValueError('Explicit nonempty argv commands required')
    inventory = inputs(root)
    key = fingerprint(root, files, commands, context)
    if report.exists():
        previous = json.loads(report.read_text())
        if previous.get('passed') and previous.get('fingerprint') == key:
            return dict(previous, reused=True)
    result = {'fingerprint': key, 'passed': False, 'reused': False, 'steps': [], 'context': context}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2)+'\n')
    try:
        for argv in commands:
            started = time.monotonic()
            completed = subprocess.run(argv, cwd=root, check=False)
            result['steps'].append({'command': argv, 'seconds': round(time.monotonic()-started, 3), 'exit_code': completed.returncode})
            print(json.dumps(result['steps'][-1]), flush=True)
            completed.check_returncode()
        if inputs(root) != inventory or fingerprint(root, files, commands, context) != key:
            raise ValueError('Inputs changed during validation')
        result['passed'] = True
        return result
    finally:
        report.write_text(json.dumps(result, indent=2)+'\n')


def inputs(root):
    """All executable candidate inputs, not only changed files. No private data."""
    result = []
    for folder in ('zeekr_control', 'tests', 'scripts/release'):
        for path in (root/folder).rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            name = str(path.relative_to(root))
            try:
                allowed(name)
            except ValueError:
                continue
            if path.is_symlink():
                raise ValueError('Public code symlink requires explicit handling: '+name)
            result.append(name)
    return sorted(result)


def build(root, baseline_path, commit, previous, candidate, backup, paths, commands, output):
    """root MUST be production baseline plus exact committed overlay, not workspace."""
    root, output = Path(root).resolve(), Path(output).resolve()
    if output == root or root in output.parents:
        raise ValueError('Output must be outside candidate tree')
    if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Full commit SHA required')
    paths = sorted(set(allowed(name) for name in paths))
    repository = Path(__file__).resolve().parents[2]
    for name in paths:
        expected = subprocess.check_output(['git', 'show', commit+':'+name], cwd=repository)
        if (root/name).read_bytes() != expected:
            raise ValueError('Overlay differs from committed content: '+name)
    if not paths:
        raise ValueError('Empty release')
    baseline = json.loads(Path(baseline_path).read_text())
    if baseline['active'] != previous:
        raise ValueError('Previous release differs from baseline')
    for name, sha in baseline['manifest'].items():
        if name not in paths and name != 'release-manifest.json':
            if hashlib.sha256((root/name).read_bytes()).hexdigest() != sha:
                raise ValueError('Unrelated candidate change: '+name)
    tier = risk(paths)
    if tier == 'ui' and not browser_checks(commands):
        raise ValueError('UI release requires explicit browser checks')
    output.mkdir(parents=True, exist_ok=True)
    all_inputs = inputs(root)
    if commands:
        validate(root, all_inputs, commands, output/'local-validation.json')
    config = dict(commit=commit, previous=previous, candidate=candidate, backup=backup, risk=tier)
    changes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in paths}
    receipt = {'hashes': {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in all_inputs}, 'commands': commands,
               'inputs': all_inputs, 'passed': bool(commands)}
    for name, record in [('config', config), ('baseline', baseline), ('changes', changes), ('receipt', receipt)]:
        (output/('.release-'+name+'.json')).write_text(json.dumps(record, indent=2)+'\n')
    with tarfile.open(output/'.release-changes.tar', 'w') as archive:
        for name in paths:
            if (root/name).is_symlink():
                raise ValueError('Symlink overlay rejected')
            archive.add(root/name, arcname=name, recursive=False)
    print(json.dumps({'risk': tier, 'changed_files': len(paths), 'server_full_suite': tier == 'full'}))
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    plan = sub.add_parser('plan')
    plan.add_argument('paths', nargs='+')
    check = sub.add_parser('validate')
    check.add_argument('--root', required=True, type=Path)
    check.add_argument('--commands', required=True, type=Path, help='JSON list of argv lists')
    check.add_argument('--report', required=True, type=Path)
    bundle = sub.add_parser('build')
    for key in ('root', 'baseline', 'commit', 'previous', 'candidate', 'backup', 'paths', 'commands', 'output'):
        bundle.add_argument('--'+key, required=True)
    args = parser.parse_args()
    if args.action == 'plan':
        for name in args.paths:
            allowed(name)
        print(json.dumps({'risk': risk(args.paths), 'server_full_suite': risk(args.paths) == 'full'}))
    elif args.action == 'validate':
        print(json.dumps(validate(args.root, inputs(args.root), json.loads(args.commands.read_text()), args.report)))
    else:
        build(args.root, args.baseline, args.commit, args.previous, args.candidate, args.backup,
              json.loads(Path(args.paths).read_text()), json.loads(Path(args.commands).read_text()), args.output)


if __name__ == '__main__':
    main()
