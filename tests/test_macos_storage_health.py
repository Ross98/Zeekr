"""APFS reclaimable capacity must not be mistaken for a full server disk."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zeekr_control.storage_health import StorageHealth, severity, GIB


class MacStorageCapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.health = StorageHealth(Path(self.temp.name))

    def measure(self, available=110*GIB, failure=False):
        usage = SimpleNamespace(total=230*GIB, used=215*GIB, free=15*GIB)
        values = {'NSURLVolumeAvailableCapacityForImportantUsageKey': available,
                  'NSURLVolumeTotalCapacityKey': usage.total}
        with patch('zeekr_control.storage_health.sys.platform', 'darwin'), \
                patch('zeekr_control.storage_health.shutil.disk_usage', return_value=usage), \
                patch('zeekr_control.storage_health.subprocess.run',
                      side_effect=OSError('native unavailable') if failure else None,
                      return_value=SimpleNamespace(stdout=json.dumps(values))):
            return self.health.measure()

    def test_reclaimable_space_changes_alert_basis_but_preserves_physical_readings(self):
        s = self.measure()
        self.assertEqual(s['disk_free_bytes'], 15*GIB)
        self.assertEqual(s['capacity_available_bytes'], 110*GIB)
        self.assertEqual(s['capacity_basis'], 'macos_important_usage')
        self.assertEqual(s['reclaimable_bytes'], 95*GIB)
        self.assertEqual(severity(s, 'critical'), 'healthy')

    def test_low_system_available_space_and_inode_pressure_still_alert(self):
        self.assertEqual(severity(self.measure(0)), 'critical')
        self.assertEqual(severity(self.measure(10*GIB)), 'critical')
        self.assertEqual(severity(self.measure(35*GIB)), 'warning')
        s = self.measure(); s['inode_used_percent'] = 95
        self.assertEqual(severity(s), 'critical')

    def test_native_failure_or_invalid_values_are_unknown_never_false_full_or_healthy(self):
        for value in (None, True, -1, 231*GIB, '110', float('nan')):
            with self.subTest(value=value):
                s = self.measure(value)
                self.assertEqual(severity(s), 'unknown')
                self.assertIsNone(s['capacity_available_bytes'])
        self.assertEqual(severity(self.measure(failure=True)), 'unknown')

    def test_both_notification_channels_explain_immediate_and_system_capacity(self):
        s = self.measure(); s['status'] = 'healthy'
        detail = self.health._message(s)
        _, bark = self.health._alert(s)
        for text in (detail, bark):
            self.assertIn('即时空闲', text)
            self.assertIn('15.00 GiB', text)
            self.assertIn('macOS估算可用', text)
            self.assertIn('110.00 GiB', text)
            self.assertIn('预计可回收', text)
        s = self.measure(failure=True); s['status'] = 'unknown'
        self.assertIn('读取失败', self.health._message(s))

    def test_capacity_basis_change_does_not_generate_false_growth_forecast(self):
        start = 1790000000
        legacy = {'time': start, 'data_bytes': 0, 'free_bytes': 200*GIB}
        self.health._save({'history': [legacy]})
        with patch.object(self.health, 'measure', return_value=self.measure()):
            self.health.tick(start+86400)
        self.assertIsNone(self.health.cached()['estimated_disk_days'])
        state = self.health._state()
        self.assertEqual(state['history'][-1]['capacity_basis'], 'macos_important_usage')
        self.assertEqual(state['history'][-1]['available_bytes'], 110*GIB)

    def test_existing_critical_alert_recovers_once_and_survives_restart(self):
        start = 1790000000
        messages = []
        self.health.sender = messages.append
        self.health._save({'sample': {'status': 'critical'}, 'notification_level': 'critical',
                           'notification_state': 'sent', 'attempt_at': start-300})
        with patch.object(self.health, 'measure', return_value=self.measure()):
            self.health.tick(start)
        self.assertEqual(len(messages), 1)
        self.assertIn('恢复正常', messages[0])
        restarted = StorageHealth(self.health.root, messages.append)
        with patch.object(restarted, 'measure', return_value=self.measure()):
            restarted.tick(start+300)
        self.assertEqual(len(messages), 1)
        self.assertEqual(restarted.cached()['status'], 'healthy')

    def test_linux_keeps_filesystem_thresholds_without_native_subprocess(self):
        with patch('zeekr_control.storage_health.sys.platform', 'linux'), \
                patch('zeekr_control.storage_health.subprocess.run') as native:
            s = self.health.measure()
        native.assert_not_called()
        self.assertEqual(s['capacity_basis'], 'filesystem_free')
        self.assertEqual(s['capacity_available_bytes'], s['disk_free_bytes'])
