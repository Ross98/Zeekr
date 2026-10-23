import sqlite3
import tempfile
import unittest
from pathlib import Path

from zeekr_control.system_notifications import AuthFailureAlert


class GatewayReasonNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.messages = []

    def alert(self):
        return AuthFailureAlert(self.root, lambda *message: self.messages.append(message))

    def test_reason_survives_restart_and_is_bound_to_queued_notification(self):
        alert = self.alert()
        alert.blocked('网关代码 1509', 1000, reason='服务维护中，稍后再试。')
        alert.record_failure('1509', '另一条错误', 2000)
        self.alert().deliver()
        body = self.messages[0][1]
        self.assertIn('网关代码：1509', body)
        self.assertIn('网关说明：服务维护中，稍后再试。', body)
        self.assertNotIn('另一条错误', body)
        self.assertIn('自动重试', body)
        self.assertNotIn('重新登录', body)

    def test_manual_notification_preserves_original_gateway_reason_for_owner(self):
        alert = self.alert()
        alert.blocked('网关代码 1509', 1000, manual=True,
                      reason='服务维护中，稍后再试。 phone=13800000000 token=private-token-value')
        self.alert().deliver()
        body = self.messages[0][1]
        self.assertIn('服务维护中，稍后再试。', body)
        self.assertIn('不会自动重放', body)
        self.assertIn('13800000000', body)
        self.assertIn('private-token-value', body)
        with alert.connect() as db:
            reason = db.execute('SELECT reason FROM auth_outbox_context').fetchone()[0]
        self.assertIn('13800000000', reason)
        self.assertIn('private-token-value', reason)

    def test_missing_reason_does_not_reuse_previous_failure(self):
        alert = self.alert()
        alert.record_failure('1509', '旧会话错误', 1000)
        alert.blocked('网关代码 1509', 2000)
        alert.deliver()
        self.assertIn('网关未提供具体原因', self.messages[0][1])
        self.assertNotIn('旧会话错误', self.messages[0][1])

    def test_legacy_pending_notification_without_reason_is_deliverable(self):
        alert = self.alert()
        alert.blocked('网关代码 1509', 1000)
        with sqlite3.connect(alert.path) as db:
            db.execute('ALTER TABLE auth_outbox_context RENAME TO old_context')
            db.execute('CREATE TABLE auth_outbox_context(generation INTEGER PRIMARY KEY,kind TEXT,incident_id TEXT)')
            db.execute('INSERT INTO auth_outbox_context SELECT generation,kind,incident_id FROM old_context')
            db.execute('DROP TABLE old_context')
        self.alert().deliver()
        self.assertEqual(len(self.messages), 1)
        self.assertIn('网关未提供具体原因', self.messages[0][1])
