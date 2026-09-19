from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.snapshots import SnapshotStore


NOW = datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp()
OLD = int(datetime(2025, 12, 1, tzinfo=timezone.utc).timestamp()*1000)


class StorageManagementTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.storage_management import StorageManager
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = StorageManager(self.root, clock=lambda: NOW)
        SnapshotStore(self.root/'snapshots.sqlite3').publish('scope', 'vehicle', {'value': 1}, OLD)

    def execute(self, action, target):
        plan = self.manager.preview(action, target, 'owner')
        return self.manager.execute(plan['token'], plan['confirmation'], 'owner')

    def test_archive_inventory_and_recoverable_delete(self):
        item = self.manager.inventory()['archives'][0]
        self.assertEqual(item['id'], '2025/12')
        self.assertTrue(item['manageable'])
        result = self.execute('trash', item['id'])
        self.assertFalse((self.root/'snapshot-archive/2025/12.sqlite3').exists())
        self.assertEqual(result['released_bytes'], 0)
        trash = self.manager.inventory()['trash'][0]
        self.execute('restore', trash['id'])
        self.assertTrue((self.root/'snapshot-archive/2025/12.sqlite3').exists())
        self.assertEqual(self.manager.inventory()['trash'], [])

    def test_permanent_delete_requires_separate_confirmation_and_is_audited(self):
        self.execute('trash', '2025/12')
        item = self.manager.inventory()['trash'][0]
        plan = self.manager.preview('purge', item['id'], 'owner')
        with self.assertRaises(ValueError):
            self.manager.execute(plan['token'], '确认', 'owner')
        self.manager.execute(plan['token'], plan['confirmation'], 'owner')
        self.assertEqual(self.manager.inventory()['trash'], [])
        self.assertIn('purge', (self.root/'storage-audit.jsonl').read_text())
        with self.assertRaises(ValueError):
            self.manager.execute(plan['token'], plan['confirmation'], 'owner')

    def test_current_month_paths_traversal_and_credentials_protected(self):
        SnapshotStore(self.root/'snapshots.sqlite3').publish('scope', 'vehicle', {}, int(NOW*1000))
        for target in ('2026/09', '../session.json', '/etc/passwd', '2025/../../Key.md', '2025/13'):
            with self.assertRaises(ValueError): self.manager.preview('trash', target, 'owner')

    def test_changed_file_expired_plan_and_different_session_rejected(self):
        plan = self.manager.preview('trash', '2025/12', 'owner')
        with self.assertRaises(ValueError):
            self.manager.execute(plan['token'], plan['confirmation'], 'other')
        SnapshotStore(self.root/'snapshots.sqlite3').publish('scope', 'vehicle', {'value': 2}, OLD+1)
        with self.assertRaises(ValueError):
            self.manager.execute(plan['token'], plan['confirmation'], 'owner')
        plan = self.manager.preview('trash', '2025/12', 'owner')
        self.manager.clock = lambda: NOW + 601
        with self.assertRaises(ValueError): self.manager.execute(plan['token'], plan['confirmation'], 'owner')

    def test_symlink_hardlink_and_sqlite_sidecar_rejected(self):
        import os
        archive = self.root/'snapshot-archive/2025/12.sqlite3'
        linked = self.root/'link'
        os.link(archive, linked)
        with self.assertRaises((ValueError, OSError)): self.manager.preview('trash', '2025/12', 'owner')
        linked.unlink()
        sidecar = archive.with_name(archive.name+'-wal')
        sidecar.touch()
        with self.assertRaises((ValueError, OSError)): self.manager.preview('trash', '2025/12', 'owner')
        sidecar.unlink()
        other = self.root/'secret'
        other.write_text('secret')
        archive.unlink()
        archive.symlink_to(other)
        with self.assertRaises((ValueError, OSError)): self.manager.preview('trash', '2025/12', 'owner')
        self.assertEqual(other.read_text(), 'secret')

    def test_audit_failure_prevents_delete_and_restore_never_overwrites(self):
        with patch.object(self.manager, '_audit', side_effect=OSError('full')):
            with self.assertRaises(OSError): self.execute('trash', '2025/12')
        self.assertTrue((self.root/'snapshot-archive/2025/12.sqlite3').exists())
        self.execute('trash', '2025/12')
        item = self.manager.inventory()['trash'][0]
        SnapshotStore(self.root/'snapshots.sqlite3').publish('scope', 'vehicle', {'new': True}, OLD)
        with self.assertRaises(ValueError): self.manager.preview('restore', item['id'], 'owner')

    def test_post_mutation_sync_failure_reports_completed_not_retry(self):
        with patch('zeekr_control.storage_management._sync', side_effect=OSError('full')):
            result = self.execute('trash', '2025/12')
        self.assertTrue(result['completed'])
        self.assertTrue(result['audit_warning'])
        self.assertEqual(len(self.manager.inventory()['trash']), 1)

    def test_broken_sidecar_symlink_is_not_ignored(self):
        sidecar = self.root/'snapshot-archive/2025/12.sqlite3-wal'
        sidecar.symlink_to(self.root/'absent')
        with self.assertRaises(ValueError): self.manager.preview('trash', '2025/12', 'owner')


class StorageHealthTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.storage_health import StorageHealth
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.messages = []
        self.health = StorageHealth(self.root, self.messages.append)

    def sample(self, used=50, free=20, inode=20):
        return {'checked_at': NOW, 'disk_total_bytes': 100*1024**3,
                'disk_used_bytes': used*1024**3, 'disk_free_bytes': free*1024**3,
                'disk_used_percent': used, 'inode_used_percent': inode,
                'data_bytes': 100, 'archive_bytes': 50, 'trash_bytes': 0, 'scan_complete': True}

    def tick(self, now, sample):
        with patch.object(self.health, 'measure', return_value=dict(sample)):
            self.health.tick(now)

    def test_thresholds_escalation_repeat_throttle_and_recovery(self):
        self.tick(NOW, self.sample())
        self.assertEqual(self.messages, [])
        self.tick(NOW+300, self.sample(used=81))
        self.tick(NOW+600, self.sample(used=82))
        self.assertEqual(len(self.messages), 1)
        self.tick(NOW+900, self.sample(used=91))
        self.assertEqual(len(self.messages), 2)
        self.tick(NOW+1200, self.sample())
        self.assertEqual(len(self.messages), 3)
        self.assertIn('恢复', self.messages[-1])

    def test_low_free_space_inode_and_restart_cooldown(self):
        from zeekr_control.storage_health import StorageHealth
        self.tick(NOW, self.sample(free=1))
        self.assertIn('严重', self.messages[-1])
        self.health = StorageHealth(self.root, self.messages.append)
        self.tick(NOW+600, self.sample(inode=95))
        self.assertEqual(len(self.messages), 1)
        self.tick(NOW+90000, self.sample(inode=95))
        self.assertEqual(len(self.messages), 2)

    def test_ambiguous_delivery_is_not_immediately_retried(self):
        from zeekr_control.notifications import DeliveryError
        def sender(message):
            self.messages.append(message)
            raise DeliveryError('synthetic secret', ambiguous=True)
        self.health.sender=sender
        self.tick(NOW, self.sample(used=90))
        self.tick(NOW+600, self.sample(used=90))
        self.assertEqual(len(self.messages), 1)
        self.assertNotIn('synthetic secret', (self.root/'storage-health.json').read_text())

    def test_growth_needs_history_and_private_files_never_exposed(self):
        self.tick(NOW, self.sample())
        sample=self.sample();sample['data_bytes']=86400100;sample['disk_free_bytes']-=86400000
        self.tick(NOW+86400, sample)
        report=self.health.cached()
        self.assertEqual(report['data_growth_bytes_per_day'], 86400000)
        self.assertGreater(report['estimated_disk_days'], 0)
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_scan_failure_never_hides_critical_disk_pressure(self):
        from zeekr_control.storage_health import severity
        sample = self.sample(used=95)
        sample['scan_complete'] = False
        self.assertEqual(severity(sample), 'critical')
        sample = self.sample(); sample['scan_complete'] = False
        self.assertEqual(severity(sample), 'unknown')

    def test_definite_failure_retry_and_interrupted_send_are_distinct(self):
        from zeekr_control.notifications import DeliveryError
        from zeekr_control.storage_health import StorageHealth
        def sender(message):
            self.messages.append(message)
            raise DeliveryError('safe failure')
        self.health.sender = sender
        self.tick(NOW, self.sample(used=81))
        self.tick(NOW+300, self.sample(used=81))
        self.assertEqual(len(self.messages), 1)
        self.tick(NOW+900, self.sample(used=81))
        self.assertEqual(len(self.messages), 2)
        state = self.health._state(); state['notification_state'] = 'sending'
        self.health._save(state)
        self.health = StorageHealth(self.root, self.messages.append)
        self.tick(NOW+1200, self.sample(used=81))
        self.assertEqual(len(self.messages), 2)
        self.assertEqual(self.health.cached()['notification_state'], 'uncertain')
