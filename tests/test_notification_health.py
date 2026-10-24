"""Collector liveness must not be confused with vehicle cache freshness."""
from pathlib import Path
import tempfile
import unittest

from zeekr_control.notification_health import service, read_health
from zeekr_control.storage import save
from zeekr_control.system_notifications import AuthFailureAlert


class CollectorHealthTests(unittest.TestCase):
    def test_public_collector_liveness_matches_diagnostics_for_invalid_deadlines(self):
        from unittest.mock import patch
        from zeekr_control.monitor_runtime import read_status
        for deadline in ('inf','Infinity','1e309','NaN','broken','-inf'):
            with self.subTest(deadline=deadline):
                save(self.root/'monitor-health.json',dict(status='cooldown',heartbeat='1000000',next_check=deadline))
                before=(self.root/'monitor-health.json').read_bytes()
                with patch('zeekr_control.monitor_runtime.time.time',return_value=1200):
                    public=read_status(self.root,public=True)
                diagnostic=service(self.root,'monitor-health.json',1200000)
                self.assertFalse(public['online'])
                self.assertEqual(public['online'],diagnostic['online'])
                self.assertEqual((self.root/'monitor-health.json').read_bytes(),before)

    def test_invalid_missing_or_future_heartbeat_never_reports_online(self):
        from unittest.mock import patch
        from zeekr_control.monitor_runtime import read_status
        for stamp in ('-inf','inf','NaN','broken','0','-1','1300000'):
            with self.subTest(stamp=stamp):
                save(self.root/'monitor-health.json',dict(status='fresh',heartbeat=stamp,next_check='inf'))
                with patch('zeekr_control.monitor_runtime.time.time',return_value=1200):
                    public=read_status(self.root,public=True)
                self.assertFalse(public['online'])
                self.assertFalse(service(self.root,'monitor-health.json',1200000)['online'])
        for data in (dict(status='not_started',heartbeat='1190000'),
                     dict(status='stopped',heartbeat='1190000'),dict(heartbeat='1190000'),
                     dict(status='fresh',next_check='1600000')):
            with self.subTest(fields=sorted(data)):
                save(self.root/'monitor-health.json',data)
                with patch('zeekr_control.monitor_runtime.time.time',return_value=1200):
                    self.assertFalse(read_status(self.root,public=True)['online'])
                self.assertFalse(service(self.root,'monitor-health.json',1200000)['online'])

    def test_valid_cooldown_and_fractional_heartbeat_keep_same_liveness(self):
        from unittest.mock import patch
        from zeekr_control.monitor_runtime import read_status
        for stamp,next_at,now,expected in (('1000000','1600000',1500000,True),
                                          ('1000000','1600000',1660001,False),
                                          ('1000000.5','broken',1100000,True)):
            with self.subTest(stamp=stamp,next_at=next_at,now=now):
                save(self.root/'monitor-health.json',dict(status='cooldown',heartbeat=stamp,next_check=next_at))
                with patch('zeekr_control.monitor_runtime.time.time',return_value=now/1000):
                    public=read_status(self.root,public=True)
                self.assertEqual(public['online'],expected)
                self.assertEqual(service(self.root,'monitor-health.json',now)['online'],expected)

    def test_corrupt_report_payload_does_not_hide_other_health_sources(self):
        import json
        from zeekr_control.periodic_report import PeriodicDelivery,report_id
        from zeekr_control.usage_events import MAX_SUMMARY_BYTES
        from unittest.mock import patch
        delivery=PeriodicDelivery(self.root/'periodic-reports.sqlite3')
        good=dict(period='day',start_date='2026-10-20',end_date='2026-10-20',generated_at=1000000)
        key=report_id('owner','car','day','2026-10-20','2026-10-20')
        with delivery.connect() as db,db:
            db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)',(key,json.dumps(good),'light','failed','skipped',1,0,0))
            db.execute('INSERT INTO report_delivery_metadata(id,owner_key,vehicle_key) VALUES(?,?,?)',(key,'owner','car'))
        AuthFailureAlert(self.root).blocked('网关代码 1509',1000000)
        decoder=json.loads
        for bad in ('['*10000+'0'+']'*10000,'{"note":"'+'X'*(MAX_SUMMARY_BYTES+1)+'"}'):
            with self.subTest(size=len(bad)):
                with delivery.connect() as db,db:
                    db.execute('INSERT OR REPLACE INTO reports VALUES(?,?,?,?,?,?,?,?)',('bad',bad,'light','pending','pending',0,0,0))
                    db.execute('INSERT OR REPLACE INTO report_delivery_metadata(id,owner_key,vehicle_key) VALUES(?,?,?)',('bad','owner','car'))
                before=delivery.path.read_bytes()
                with patch('zeekr_control.notification_health.json.loads',wraps=decoder) as parsed:
                    result=read_health(self.root,owner='owner',vehicle='car',now_ms=1010000)
                self.assertFalse(result['summary']['complete'])
                self.assertIn('reports',result['unavailable_sources'])
                self.assertEqual([r['id'] for r in result['periodic_reports']],[key])
                self.assertEqual(result['summary']['failed_events'],1)
                self.assertEqual(result['system_alerts']['auth']['parts']['bark']['state'],'pending')
                self.assertEqual(delivery.path.read_bytes(),before)
                self.assertTrue(all(len(c.args[0])<=MAX_SUMMARY_BYTES for c in parsed.call_args_list))
                other=read_health(self.root,owner='other',vehicle='other-car',now_ms=1010000)
                self.assertTrue(other['summary']['complete'])
                self.assertEqual(other['periodic_reports'],[])
        # The bound is UTF-8 bytes; an otherwise valid exact-boundary report
        # remains visible instead of being classified as damaged.
        prefix=json.dumps(dict(good,note=''),ensure_ascii=False,separators=(',',':'))
        padding=MAX_SUMMARY_BYTES-len(prefix.encode())
        good['note']='汉'*(padding//3)+'x'*(padding%3)
        encoded=json.dumps(good,ensure_ascii=False,separators=(',',':'))
        self.assertEqual(len(encoded.encode()),MAX_SUMMARY_BYTES)
        with delivery.connect() as db,db:
            db.execute("DELETE FROM reports WHERE id='bad'")
            db.execute('UPDATE reports SET payload=? WHERE id=?',(encoded,key))
        result=read_health(self.root,owner='owner',vehicle='car',now_ms=1010000)
        self.assertTrue(result['summary']['complete'])
        self.assertEqual([r['id'] for r in result['periodic_reports']],[key])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_cached_vehicle_status_does_not_report_collector_failure(self):
        for status in ('parked_waiting', 'stale'):
            with self.subTest(status=status):
                save(self.root / 'monitor-health.json', {
                    'status': status, 'heartbeat': '1000000', 'next_check': '1020000'})
                result = service(self.root, 'monitor-health.json', 1010000)
                self.assertEqual(result['status'], status)
                self.assertTrue(result['online'])
                self.assertIsNone(result['error_code'])

    def test_cached_status_still_requires_a_live_heartbeat(self):
        save(self.root / 'monitor-health.json', {
            'status': 'parked_waiting', 'heartbeat': '1000000', 'next_check': '1020000'})
        self.assertFalse(service(self.root, 'monitor-health.json', 1200000)['online'])

    def test_unknown_status_still_reports_degraded(self):
        save(self.root / 'monitor-health.json', {'status': 'unrecognized', 'heartbeat': '1000000'})
        result = service(self.root, 'monitor-health.json', 1010000)
        self.assertEqual(result['status'], 'degraded')
        self.assertEqual(result['error_code'], 'service_unavailable')

    def test_malformed_storage_state_does_not_hide_other_notification_sources(self):
        AuthFailureAlert(self.root).blocked('网关代码 1509', 1000000)
        save(self.root / 'monitor-health.json', {'status':'parked_waiting','heartbeat':'1000000'})
        for state in ('null', '[]', '42', '"invalid"', '['*10000+'0'+']'*10000):
            with self.subTest(size=len(state)):
                save(self.root / 'storage-health.json', {'state':state})
                result = read_health(self.root, now_ms=1010000)
                self.assertFalse(result['summary']['complete'])
                self.assertIn('storage', result['unavailable_sources'])
                self.assertTrue(result['services']['collector']['online'])
                self.assertEqual(result['system_alerts']['auth']['parts']['bark']['state'], 'pending')
