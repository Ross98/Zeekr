import importlib.util
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'scripts/macos-management/管理工具/zeekr_manager.py'
spec = importlib.util.spec_from_file_location('zeekr_manager', MODULE)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class ManagementTests(unittest.TestCase):
    def setup_host(self, stop_fails=False):
        calls = []

        @contextmanager
        def lock(host):
            calls.append('lock')
            try:
                yield
            finally:
                calls.append('unlock')

        def stop():
            calls.append('stop')
            if stop_fails:
                raise ValueError('Unverified descendants still running')

        host = SimpleNamespace(
            base=Path('/runtime/ZeekrServer'),
            active=lambda: Path('/runtime/ZeekrServer/releases/current-version'),
            start=lambda: calls.append('start'), stop=stop,
            health=lambda: calls.append('health'),
            artwork=lambda root: calls.append('artwork'),
        )
        native = SimpleNamespace(
            lock=lock,
            inspect=lambda host: {
                'active': str(host.active()), 'base': str(host.base),
                'state': '/runtime/ZeekrServer/state',
                'origin': 'https://service.example', 'starts_at': 'user login',
                'services': {'local.zeekr.resources': {'state': 'running', 'pid': '1'}},
                'environment': {'TOKEN': 'secret-never-export'},
            },
            read=lambda path: {'previous': '/runtime/ZeekrServer/releases/previous-version'},
            rollback=lambda host, record: calls.append('native-rollback'),
        )
        return host, native, calls

    def test_declining_stop_never_locks_or_stops(self):
        host, native, calls = self.setup_host()
        self.assertFalse(manager.control('stop', native, host, lambda prompt: 'no'))
        self.assertEqual(calls, [])

    def test_restart_reuses_quiescence_and_health_under_release_lock(self):
        host, native, calls = self.setup_host()
        self.assertTrue(manager.control('restart', native, host, lambda prompt: '重启'))
        self.assertEqual(calls, ['lock', 'stop', 'start', 'health', 'unlock'])

    def test_failed_stop_does_not_spawn_duplicate_workers(self):
        host, native, calls = self.setup_host(stop_fails=True)
        with self.assertRaises(ValueError):
            manager.control('restart', native, host, lambda prompt: '重启')
        self.assertEqual(calls, ['lock', 'stop', 'unlock'])

    def test_start_needs_no_stop_and_preserves_native_idempotence(self):
        host, native, calls = self.setup_host()
        manager.control('start', native, host)
        self.assertEqual(calls, ['lock', 'start', 'health', 'unlock'])

    def test_rollback_delegates_to_existing_data_preserving_tool(self):
        host, native, calls = self.setup_host()
        self.assertTrue(manager.control('rollback', native, host, lambda prompt: '回退'))
        self.assertEqual(calls, ['lock', 'native-rollback', 'unlock'])

    def test_status_is_explicit_allowlist_without_environment_or_secrets(self):
        host, native, calls = self.setup_host()
        report = manager.public_status(native, host)
        self.assertNotIn('environment', report)
        self.assertNotIn('secret-never-export', str(report))
        self.assertIn('local.zeekr.resources', report['services'])
        self.assertEqual(calls, [])

    def test_rollback_rereads_record_after_acquiring_lock(self):
        host, native, calls = self.setup_host()
        record = {'previous': '/runtime/ZeekrServer/releases/previous-version'}

        def read(path):
            calls.append('read')
            return dict(record)

        native.read = read
        self.assertTrue(manager.control('rollback', native, host, lambda prompt: '回退'))
        self.assertEqual(calls, ['read', 'lock', 'read', 'native-rollback', 'unlock'])

    def test_changed_release_or_active_version_cancels_before_rollback(self):
        for change in ('record', 'active'):
            with self.subTest(change=change):
                host, native, calls = self.setup_host()
                record = {'previous': '/runtime/ZeekrServer/releases/previous-version',
                          'backup': '/runtime/ZeekrServer/backups/original'}
                native.read = lambda path: dict(record)

                def confirm(prompt):
                    if change == 'record':
                        # Even the same target with different restore inputs is stale.
                        record['backup'] = '/runtime/ZeekrServer/backups/new'
                    else:
                        host.active = lambda: Path('/runtime/ZeekrServer/releases/new')
                    return '回退'

                with self.assertRaisesRegex(ValueError, '版本或发布记录已变化'):
                    manager.control('rollback', native, host, confirm)
                self.assertEqual(calls, ['lock', 'unlock'])

    def test_declining_rollback_does_not_acquire_lock(self):
        host, native, calls = self.setup_host()
        self.assertFalse(manager.control('rollback', native, host, lambda prompt: '取消'))
        self.assertEqual(calls, [])

    def test_password_tool_runs_under_the_existing_release_lock(self):
        host, native, calls = self.setup_host()
        native.change_password = lambda host: calls.append('password')
        with patch.object(manager, 'load_native', return_value=(native, host)):
            manager.main(['password'])
        self.assertEqual(calls, ['lock', 'password', 'unlock'])


if __name__ == '__main__':
    unittest.main()
