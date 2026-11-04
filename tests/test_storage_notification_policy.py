"""Storage alert handover retains sampling without duplicate delivery."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zeekr_control.storage import save
from zeekr_control.storage_health import GIB, StorageHealth


class StorageNotificationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.messages = []
        self.health = StorageHealth(self.root, lambda *args: self.messages.append(args),
                                    lambda *args: self.messages.append(args))
        self.sample = dict(scan_complete=True, disk_total_bytes=100*GIB,
                           disk_free_bytes=GIB, disk_used_percent=99,
                           inode_used_percent=1, data_bytes=100)

    def tick(self, now):
        with patch.object(self.health, 'measure', return_value=dict(self.sample)):
            self.health.tick(now)

    def test_disabled_channels_still_sample_but_never_alert_remind_retry_or_recover(self):
        save(self.root/'storage-notifications.json', {'enabled': '0'})
        self.health._save(dict(notification_level='critical', notification_state='failed',
                              alert_notification_state='pending', retry_at=0, attempt_at=0))
        self.tick(1790000000)
        self.tick(1790086400)
        self.sample.update(disk_free_bytes=50*GIB, disk_used_percent=50)
        self.tick(1790086700)
        self.assertEqual(self.messages, [])
        state = self.health._state()
        self.assertEqual(state['sample']['status'], 'healthy')
        self.assertEqual(state['last_check'], 1790086700)
        self.assertTrue(state['history'])
        self.assertFalse(state['notifications_enabled'])
        self.assertEqual(state['notification_state'], 'failed')

    def test_missing_policy_keeps_existing_channels(self):
        self.tick(1790000000)
        self.assertEqual(len(self.messages), 2)

    def test_policy_is_reread_without_restart(self):
        save(self.root/'storage-notifications.json', {'enabled': '0'})
        self.tick(1790000000)
        self.assertEqual(self.messages, [])
        save(self.root/'storage-notifications.json', {'enabled': '1'})
        self.tick(1790000300)
        self.assertEqual(len(self.messages), 2)

    def test_invalid_policy_does_not_silently_disable_alerts(self):
        save(self.root/'storage-notifications.json', {'enabled': 'typo'})
        with self.assertRaises(ValueError): self.tick(1790000000)
        self.assertEqual(self.messages, [])
