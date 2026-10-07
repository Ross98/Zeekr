import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('workflow', Path(__file__).parents[1]/'scripts/release/workflow.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class ReleaseWorkflowTests(unittest.TestCase):
    def test_static_ui_does_not_require_full_python_suite(self):
        self.assertEqual(w.risk(['zeekr_control/static/app.css', 'zeekr_control/static/app.js', 'tests/ui_smoke.cjs']), 'ui')

    def test_backend_auth_unknown_and_deletions_use_full_gate(self):
        for files in [['zeekr_control/web.py'], ['zeekr_control/static/login.js'], ['setup.cfg'], ['zeekr_control/static/app.css']]:
            self.assertEqual(w.risk(files, deleted=files[-1:] if files == ['zeekr_control/static/app.css'] else []), 'full')

    def test_repository_release_instructions_allowed(self):
        self.assertEqual(w.allowed('AGENTS.md'), 'AGENTS.md')

    def test_public_report_assets_and_unit_are_exactly_allowed(self):
        for name in ('deploy/zeekr-reports.service','zeekr_control/assets/periodic-report/manifest.json'):
            self.assertEqual(w.allowed(name),name)
        for name in ('deploy/private.service','zeekr_control/assets/periodic-report/secrets.json'):
            with self.assertRaises(ValueError):w.allowed(name)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);unit=root/'deploy/zeekr-reports.service';unit.parent.mkdir();unit.write_text('unit')
            self.assertIn('deploy/zeekr-reports.service',w.inputs(root))

    def test_optional_report_service_starts_only_on_supported_release(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(w.runtime_services(root,True),['zeekr-monitor','zeekr-control'])
            source=root/'zeekr_control/periodic_schedule.py';source.parent.mkdir();source.write_text('module')
            self.assertIn('zeekr-reports',w.runtime_services(root,True))
            self.assertNotIn('zeekr-reports',w.runtime_services(root,False))

    def test_private_and_traversal_paths_rejected(self):
        for name in ['Key.md', 'Adam.pem', '../zeekr_control/web.py', '/etc/passwd', 'zeekr_control/vehicle_profiles.json', 'docs/private.json']:
            with self.assertRaises(ValueError):
                w.allowed(name)

    def test_validation_reuses_only_exact_inputs_and_passing_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'a').write_text('one')
            report = root/'result.json'
            commands = [['python3', '-c', 'pass']]
            first = w.validate(root, ['a'], commands, report)
            self.assertFalse(first['reused'])
            self.assertTrue(w.validate(root, ['a'], commands, report)['reused'])
            (root/'a').write_text('two')
            self.assertFalse(w.validate(root, ['a'], commands, report)['reused'])
            self.assertFalse(w.validate(root, ['a'], commands, report, context='service-user')['reused'])
            with self.assertRaises(Exception):
                w.validate(root, ['a'], [['python3', '-c', 'raise SystemExit(1)']], report)
            self.assertFalse(json.loads(report.read_text())['passed'])

    def test_files_changed_during_validation_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'a').write_text('one')
            with self.assertRaises(ValueError):
                w.validate(root, ['a'], [['python3', '-c', "from pathlib import Path; Path('a').write_text('two')"]], root/'result.json')

class ReleaseBuildTests(unittest.TestCase):
    def test_bundle_requires_committed_overlay_and_browser_gate(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            root = parent/'tree'
            source = root/'zeekr_control/static/app.css'
            source.parent.mkdir(parents=True)
            source.write_text('new')
            baseline = parent/'baseline.json'
            baseline.write_text(json.dumps({'active': '/opt/zeekr-control/releases/old', 'manifest': {'zeekr_control/static/app.css': 'old'}}))
            kwargs = dict(root=root, baseline_path=baseline, commit='a'*40, previous='/opt/zeekr-control/releases/old',
                          candidate='/opt/zeekr-control/releases/new', backup='/opt/zeekr-control/backups/new',
                          paths=['zeekr_control/static/app.css'], commands=[], output=parent/'bundle')
            with patch.object(w.subprocess, 'check_output', return_value=b'old'):
                with self.assertRaisesRegex(ValueError, 'committed'):
                    w.build(**kwargs)
            with patch.object(w.subprocess, 'check_output', return_value=b'new'):
                with self.assertRaisesRegex(ValueError, 'browser'):
                    w.build(**kwargs)
                kwargs['commands'] = [['node', 'tests/ui_smoke.cjs']]
                with patch.object(w, 'validate'):
                    self.assertEqual(w.build(**kwargs)['risk'], 'ui')
                receipt = json.loads((parent/'bundle/.release-receipt.json').read_text())
                self.assertEqual(set(receipt['hashes']), {'zeekr_control/static/app.css'})

    def test_public_input_inventory_includes_data_dependencies_not_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['zeekr_control/parameter_dictionary.json', 'zeekr_control/assets/glyphs.zlib',
                         'tests/fixtures/a.json', 'zeekr_control/vehicle_profiles.json']:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}')
            self.assertEqual(len(w.inputs(root)), 3)

    def test_new_source_during_validation_invalidates_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'a').write_text('one')
            command = "from pathlib import Path; Path('tests').mkdir(); Path('tests/new.py').write_text('pass')"
            with self.assertRaises(ValueError):
                w.validate(root, ['a'], [['python3', '-c', command]], root/'result.json')

    def test_post_deploy_failure_runs_rollback(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('server', Path(__file__).parents[1]/'scripts/release/server.py')
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            def phase(name):
                calls.append(name)
                if name == 'verify':
                    raise RuntimeError('unhealthy')
            with patch.object(server, 'base', Path(folder)), patch.object(server, 'phase', side_effect=phase), patch('sys.argv', ['server.py', 'deploy']):
                with self.assertRaises(RuntimeError):
                    server.main()
            self.assertEqual(calls, ['cutover', 'verify', 'rollback'])


class CandidateStageTests(unittest.TestCase):
    def test_ui_stage_skips_full_suite_and_backend_runs_it_once(self):
        import hashlib
        import runpy
        import shutil
        import subprocess
        import sys
        from unittest.mock import patch
        from zeekr_control.release_info import write_manifest
        repository = Path(__file__).parents[1]
        original_path = list(sys.path)
        try:
            for tier in ('ui', 'full'):
                with self.subTest(tier=tier), tempfile.TemporaryDirectory() as folder:
                    base = Path(folder).resolve()/'host'
                    current = base/'releases/old'
                    current.mkdir(parents=True)
                    (base/'current').symlink_to(current)
                    for name, data in {
                        'zeekr_control/release_info.py': (repository/'zeekr_control/release_info.py').read_bytes(),
                        'zeekr_control/web.py': b'old web',
                        'zeekr_control/static/app.js': b'old app',
                        'zeekr_control/static/app.css': b'old css',
                        'tests/ui_fixture.cjs': b'process.exit(0)',
                        'zeekr_control/vehicle_profiles.json': b'private config must stay on server',
                    }.items():
                        target = current/name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
                    write_manifest(current, 'b'*40, ['release-summary'])
                    public = w.inputs(current)+['release-manifest.json']
                    baseline = {'active': str(current), 'manifest': {n: hashlib.sha256((current/n).read_bytes()).hexdigest() for n in public}}
                    baseline_path = Path(folder)/'baseline.json'
                    baseline_path.write_text(json.dumps(baseline))
                    preview = Path(folder)/'preview'
                    shutil.copytree(current, preview)
                    # Local snapshot intentionally lacks private server configuration.
                    (preview/'zeekr_control/vehicle_profiles.json').unlink()
                    name = 'zeekr_control/static/app.css' if tier == 'ui' else 'zeekr_control/web.py'
                    (preview/name).write_bytes(b'new')
                    (preview/'docs').mkdir()
                    (preview/'docs/notes.md').write_bytes(b'new')
                    bundle = Path(folder)/'bundle'
                    with patch.object(w.subprocess, 'check_output', return_value=b'new'):
                        w.build(preview, baseline_path, 'a'*40, str(current), str(base/'releases/new'), str(base/'backups/new'),
                                [name, 'docs/notes.md'], [['node', 'tests/ui_fixture.cjs']] if tier == 'ui' else [], bundle)
                    for path in bundle.glob('.release-*'):
                        shutil.copyfile(path, base/path.name)
                    shutil.copyfile(repository/'scripts/release/workflow.py', base/'.release-workflow.py')
                    stage_source = (repository/'scripts/release/stage.py').read_text().replace("Path('/opt/zeekr-control')", 'Path('+repr(str(base))+')')
                    stage = Path(folder)/'stage.py'
                    stage.write_text(stage_source)
                    calls = []
                    def run(argv, **kwargs):
                        calls.append(argv)
                        if argv[0] == 'cp':
                            shutil.copytree(Path(argv[2]), Path(argv[3]), dirs_exist_ok=True)
                        return subprocess.CompletedProcess(argv, 0)
                    with patch('subprocess.run', side_effect=run):
                        result = runpy.run_path(str(stage))
                    full_runs = [c for c in calls if 'unittest' in c]
                    self.assertEqual(len(full_runs), 0 if tier == 'ui' else 1)
                    candidate = base/'releases/new'
                    self.assertEqual((candidate/'zeekr_control/vehicle_profiles.json').read_bytes(), b'private config must stay on server')
                    self.assertTrue((base/'.release-ready.json').exists())
                    ready = json.loads((base/'.release-ready.json').read_text())
                    self.assertIn('docs/notes.md', ready['candidate_hashes'])
                    # Drift fails BEFORE stopping any service or reading private data.
                    (candidate/name).write_bytes(b'tampered')
                    cutover_source = (repository/'scripts/release/cutover.py').read_text().replace("Path('/opt/zeekr-control')", 'Path('+repr(str(base))+')')
                    cutover_source = cutover_source[:cutover_source.index('size=int')]
                    with patch('subprocess.run') as stopped:
                        with self.assertRaisesRegex(AssertionError, 'Candidate drift'):
                            exec(compile(cutover_source, '<cutover-preflight>', 'exec'), {})
                        stopped.assert_not_called()
        finally:
            sys.path[:] = original_path


class SnapshotAndTimingTests(unittest.TestCase):
    def test_snapshot_never_exports_private_profile(self):
        import io
        import tarfile
        import types
        from unittest.mock import patch
        repository = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            active = base/'releases/old'
            (active/'zeekr_control').mkdir(parents=True)
            (active/'zeekr_control/web.py').write_text('public source')
            (active/'zeekr_control/vehicle_profiles.json').write_text('PRIVATE SENTINEL')
            (active/'release-manifest.json').write_text('{"features":{"x":{}}}')
            (base/'current').symlink_to(active)
            source = (repository/'scripts/release/workflow.py').read_text().replace("if __name__ == '__main__':", 'if False:')
            source += '\n'+(repository/'scripts/release/snapshot.py').read_text().replace("Path('/opt/zeekr-control')", 'Path('+repr(str(base))+')')
            buffer = io.BytesIO()
            with patch('sys.stdout', types.SimpleNamespace(buffer=buffer)):
                exec(compile(source, '<snapshot>', 'exec'), {})
            with tarfile.open(fileobj=io.BytesIO(buffer.getvalue()), mode='r:gz') as archive:
                self.assertNotIn('staged/zeekr_control/vehicle_profiles.json', archive.getnames())
                for entry in archive.getmembers():
                    self.assertNotIn(b'PRIVATE SENTINEL', archive.extractfile(entry).read())

    def test_failure_keeps_timing_and_restores_runner(self):
        from unittest.mock import patch
        import subprocess
        spec = importlib.util.spec_from_file_location('timed_server', Path(__file__).parents[1]/'scripts/release/server.py')
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        original = subprocess.run
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(server, 'base', Path(folder)), patch.object(server.runpy, 'run_path', side_effect=RuntimeError('bad')):
                with self.assertRaises(RuntimeError):
                    server.phase('verify')
            row = json.loads((Path(folder)/'.release-timings.jsonl').read_text())
            self.assertFalse(row['passed'])
            self.assertEqual(row['phase'], 'verify')
            self.assertIs(subprocess.run, original)


if __name__ == "__main__":
    unittest.main()
