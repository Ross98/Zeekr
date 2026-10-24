import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zeekr_control.system_notifications import AuthFailureAlert


class GatewayReasonNotificationTests(unittest.TestCase):
    def test_failed_schema_upgrade_keeps_original_context_and_database_bytes(self):
        alert=self.alert()
        db=sqlite3.connect(alert.path)
        try:
            db.execute('CREATE TABLE auth_outbox_context(generation INTEGER PRIMARY KEY,kind TEXT,incident_id TEXT)')
            db.executemany('INSERT INTO auth_outbox_context VALUES(?,?,?)',
                           [(1,'manual','duplicate'),(2,'manual','duplicate')])
            db.commit()
        finally:db.close()
        alert.path.chmod(0o600);before=alert.path.read_bytes()
        with self.assertRaises(sqlite3.IntegrityError):
            with alert.connect():pass
        self.assertEqual(alert.path.read_bytes(),before)

    def test_malformed_unicode_reason_cannot_abort_auth_alert_queue(self):
        for index,bad in enumerate(('\ud800','\udfff')):
            with self.subTest(bad=ascii(bad)):
                alert=self.alert()
                alert.blocked('网关代码 1509',1000+index,reason='服务维护'+bad+'中，稍后再试。')
                self.alert().deliver()
                self.assertEqual(len(self.messages),index+1)
                body=self.messages[-1][1]
                body.encode('utf-8')
                self.assertIn('服务维护',body)
                self.assertIn('稍后再试',body)
                self.assertIn(ascii(bad)[1:-1],body)
                alert.recovered()

    def test_unicode_reason_expansion_still_obeys_stored_length_limit(self):
        alert=self.alert()
        alert.blocked('网关代码 1509',1000,reason='\ud800'*240)
        with alert.connect() as db:
            reason=db.execute('SELECT reason FROM auth_outbox_context').fetchone()[0]
        self.assertLessEqual(len(reason),240)
        reason.encode('utf-8')

    def test_recovery_during_preparation_cancels_old_auth_alert(self):
        from zeekr_control.system_notifications import load
        alert = self.alert()
        alert.blocked('网关代码 1509',1000)
        def recover(path):
            if path.name=='monitor-health.json':alert.recovered()
            return load(path)
        with patch('zeekr_control.system_notifications.load',side_effect=recover):
            alert.deliver()
        self.assertEqual(self.messages,[])
        with alert.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM auth_outbox').fetchone()[0],'cancelled')

    def test_pause_after_preparation_leaves_auth_intent_pending(self):
        from zeekr_control.delivery_state import DeliveryCancelled
        alert = self.alert()
        alert.blocked('网关代码 1509',1000)
        calls = []
        def guard():
            calls.append(True)
            if len(calls)==2:raise DeliveryCancelled('synthetic pause')
        with self.assertRaises(DeliveryCancelled):alert.deliver(guard)
        self.assertEqual(self.messages,[])
        with alert.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM auth_outbox').fetchone()[0],'pending')
        alert.deliver()
        self.assertEqual(len(self.messages),1)

    def test_manual_escalation_during_preparation_replaces_old_alert(self):
        from zeekr_control.system_notifications import load
        alert = self.alert()
        alert.blocked('网关代码 1509',1000,reason='旧中断原因')
        def escalate(path):
            if path.name=='monitor-health.json':
                alert.blocked('网关代码 1509',2000,manual=True,reason='新认证原因')
            return load(path)
        with patch('zeekr_control.system_notifications.load',side_effect=escalate):alert.deliver()
        self.assertEqual(self.messages,[])
        with alert.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM auth_outbox ORDER BY generation').fetchall(),
                             [('cancelled',),('pending',)])
        alert.deliver()
        self.assertEqual(len(self.messages),1)
        self.assertIn('新认证原因',self.messages[0][1])
        self.assertNotIn('旧中断原因',self.messages[0][1])

    def test_preparation_interruption_is_resumable_but_actual_send_is_not_replayed(self):
        alert = self.alert()
        alert.blocked('网关代码 1509',1000)
        with patch('zeekr_control.system_notifications.load',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):alert.deliver()
        with alert.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM auth_outbox').fetchone()[0],'preparing')
        self.alert().deliver()
        self.assertEqual(len(self.messages),1)
        alert.recovered()
        alert.blocked('网关代码 1509',2000)
        def interrupted(*message):raise KeyboardInterrupt
        alert.sender=interrupted
        with self.assertRaises(KeyboardInterrupt):alert.deliver()
        self.alert().deliver()
        self.assertEqual(len(self.messages),1)
        with alert.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM auth_outbox ORDER BY generation').fetchall(),
                             [('sent',),('uncertain',)])

    def test_real_worker_pause_during_preparation_stops_auth_sender(self):
        from zeekr_control.delivery_runtime import DeliveryWorker
        from zeekr_control.delivery_state import DeliveryCancelled
        from zeekr_control.storage import save
        from zeekr_control.system_notifications import load
        save(self.root/'session.json',{'accessToken':'synthetic'})
        worker=DeliveryWorker(self.root/'session.json',sender=None,alert_sender=self.alert().sender)
        worker.auth_alert.blocked('网关代码 1509',1000)
        def pause(path):
            if path.name=='monitor-health.json':save(self.root/'sampling.json',{'enabled':'false'})
            return load(path)
        with patch('zeekr_control.system_notifications.load',side_effect=pause):
            with self.assertRaises(DeliveryCancelled):worker.auth_alert.deliver(worker.guard)
        self.assertEqual(self.messages,[])
        with worker.auth_alert.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM auth_outbox').fetchone()[0],'pending')

    def test_rollback_requeues_auth_preparation_only(self):
        from zeekr_control.delivery_state import normalize_preparation_for_rollback
        alert = self.alert()
        alert.blocked('网关代码 1509',1000)
        with alert.connect() as db,db:
            db.execute("UPDATE auth_outbox SET state='preparing'")
            db.executemany('INSERT INTO auth_outbox VALUES(?,?,?,NULL,NULL)',
                           [(2,1000,'sending'),(3,1000,'uncertain'),(4,1000,'sent'),(5,1000,'failed')])
        result = normalize_preparation_for_rollback(self.root)
        self.assertEqual(result['auth_outbox.state'],1)
        with alert.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM auth_outbox ORDER BY generation').fetchall(),
                             [('pending',),('sending',),('uncertain',),('sent',),('failed',)])

    def test_recovery_after_actual_sender_entry_preserves_sent_history(self):
        alert = self.alert()
        alert.blocked('网关代码 1509',1000)
        def sent_then_recovered(*message):
            self.messages.append(message)
            alert.recovered()
        alert.sender=sent_then_recovered
        alert.deliver()
        alert.deliver()
        self.assertEqual(len(self.messages),1)
        with alert.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM auth_outbox').fetchone()[0],'sent')

    def test_known_preparation_failure_is_not_marked_as_ambiguous_send(self):
        alert = self.alert()
        alert.blocked('网关代码 1509',1000)
        with patch('zeekr_control.system_notifications.load',side_effect=ValueError('synthetic malformed health')):
            alert.deliver()
        self.assertEqual(self.messages,[])
        with alert.connect() as db:
            self.assertEqual(db.execute('SELECT state,error FROM auth_outbox').fetchone(),('failed','prepare_failed'))

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
