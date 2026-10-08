"""Crash boundaries use only temporary stores and fake senders."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import sqlite3
import threading

from zeekr_control.periodic_report import PeriodicDelivery, demo_report
from zeekr_control.storage import save


class DeliveryReliabilityTests(unittest.TestCase):
    def test_event_revision_tracks_same_length_summary_edits_insert_delete_and_vehicle_move(self):
        from zeekr_control.monitor import Monitor
        with tempfile.TemporaryDirectory() as folder:
            monitor=Monitor(Path(folder)/'tracks.sqlite3')
            with monitor.tracks.connect() as db:
                def revision(vehicle):
                    row=db.execute('SELECT revision FROM analysis_event_revisions WHERE vehicle=?',(vehicle,)).fetchone()
                    return row[0] if row else 0
                db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES('e','a','trip_end','{\"address\":\"AAAA\"}','safe',1)")
                self.assertEqual(revision('a'),1)
                db.execute("UPDATE monitor_events SET summary='{\"address\":\"BBBB\"}' WHERE id='e'")
                self.assertEqual(revision('a'),2)
                db.execute("UPDATE monitor_events SET delivery='sent' WHERE id='e'")
                self.assertEqual(revision('a'),2)
                db.execute("UPDATE monitor_events SET vehicle='b' WHERE id='e'")
                self.assertEqual((revision('a'),revision('b')),(3,1))
                db.execute("DELETE FROM monitor_events WHERE id='e'")
                self.assertEqual((revision('a'),revision('b')),(3,2))
                db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES('new','a','trip_end','{}','safe',1)")
                self.assertEqual(revision('a'),4)

    def test_blocked_sender_in_real_subprocess_does_not_block_collection(self):
        import socket
        import subprocess
        import sys
        from zeekr_control.monitor_runtime import Runner
        from test_monitor import BASE,sample
        class Client:
            calls=0
            def __init__(self,session):pass
            def vehicles(self):return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin):
                Client.calls+=1
                return sample(Client.calls*30)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private';save(root/'session.json',{'accessToken':'synthetic'})
            runner=Runner(root/'session.json',client_factory=Client,sender=Mock())
            runner.auth_failure_alert.blocked('网关代码 1509',BASE)
            parent,child=socket.socketpair();parent.settimeout(5)
            process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('delivery_blocking_child.py')),str(root),str(child.fileno()),str(BASE)],pass_fds=(child.fileno(),))
            child.close()
            try:
                self.assertEqual(parent.recv(1),b'S')
                for offset in (30,60,90):runner.tick(BASE+offset*1000)
                self.assertEqual(Client.calls,3)
                self.assertIsNone(process.poll())
                self.assertEqual(runner.health()['last_success'],str(BASE+90000))
                parent.sendall(b'R');self.assertEqual(process.wait(timeout=5),0)
            finally:
                parent.close();runner.insight_worker.close()
                if process.poll() is None:process.kill();process.wait(timeout=2)

    def test_rollback_requeues_only_preparation_and_preserves_ambiguous_sends(self):
        from zeekr_control.monitor import Monitor
        from zeekr_control.delivery_state import normalize_preparation_for_rollback
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);monitor=Monitor(root/'tracks.sqlite3');delivery=PeriodicDelivery(root/'periodic-reports.sqlite3')
            states=('preparing','ready','sending','unknown','uncertain','sent','failed')
            with monitor.tracks.connect() as db:
                for state in states:
                    db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created,delivery,attempts) VALUES(?,?,?,?,?,?,?,?)',(state,'v','trip_end','{}','unchanged',1,state,2))
            with delivery.connect() as db,db:
                for state in states:db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)',(state,'{}','light',state,state,2,2,0))
            normalize_preparation_for_rollback(root)
            with monitor.tracks.connect() as db:
                for identity,state,attempts,message in db.execute('SELECT id,delivery,attempts,message FROM monitor_events'):
                    self.assertEqual(state,'pending' if identity in ('preparing','ready') else identity)
                    self.assertEqual((attempts,message),(2,'unchanged'))
            with delivery.connect() as db:
                for identity,text,image in db.execute('SELECT id,text,image FROM reports'):
                    self.assertEqual((text,image),('pending','pending') if identity in ('preparing','ready') else (identity,identity))
            self.assertTrue(all(n==0 for n in normalize_preparation_for_rollback(root).values()))

    def test_rollback_does_not_touch_live_locked_delivery(self):
        from zeekr_control.delivery_state import delivery_lock,DeliveryBusy,normalize_preparation_for_rollback
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);entered=threading.Event();release=threading.Event()
            def hold():
                with delivery_lock(root/'notifications.lock'):entered.set();release.wait(2)
            thread=threading.Thread(target=hold);thread.start()
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(DeliveryBusy):normalize_preparation_for_rollback(root)
            finally:release.set();thread.join(2)

    def test_image_only_failure_and_auth_alert_are_visible_without_private_error(self):
        from zeekr_control.monitor import Monitor
        from zeekr_control.notification_health import read_health
        from zeekr_control.system_notifications import AuthFailureAlert
        from zeekr_control.notifications import DeliveryError
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);monitor=Monitor(root/'tracks.sqlite3')
            with monitor.tracks.connect() as db:
                db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created,delivery) VALUES('e','v','trip_end','PRIVATE','PRIVATE',1,'sent')")
                db.execute("INSERT INTO monitor_event_media(event_id,kind,delivery,error) VALUES('e','trip_image','failed','PRIVATE')")
            alert=AuthFailureAlert(root,Mock(side_effect=DeliveryError('PRIVATE',ambiguous=True)))
            alert.blocked('网关代码 1509',1000);alert.deliver()
            health=read_health(root,owner='o',vehicle='v',context='c',now_ms=2000)
            self.assertEqual(health['summary']['failed_events'],1)
            self.assertEqual(health['summary']['uncertain_events'],1)
            self.assertEqual(health['events'][0]['parts']['image']['state'],'failed')
            self.assertEqual(health['system_alerts']['auth']['parts']['bark']['state'],'uncertain')
            self.assertNotIn('PRIVATE',json.dumps(health))
            self.assertFalse(health['services']['reports']['enabled'])
            self.assertIsNone(health['services']['reports']['next_due'])

    def test_shutdown_during_vehicle_list_does_not_start_status_request(self):
        from zeekr_control.monitor_runtime import Runner,collection_loop
        stop=threading.Event()
        class Client:
            def __init__(self,session):pass
            def vehicles(self):stop.set();return [{'vin':'L6T79X2Z0NP000001'}]
            def status(self,vin):raise AssertionError('new request started during shutdown')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private';save(root/'session.json',{'accessToken':'synthetic'})
            runner=Runner(root/'session.json',client_factory=Client,sender=Mock())
            try:collection_loop(runner,stop,once=True)
            finally:runner.insight_worker.close()
            runner.sender.assert_not_called()

    def test_once_budget_prevents_new_claims_and_leaves_pending_intent(self):
        from zeekr_control.delivery_runtime import DeliveryWorker
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private';save(root/'session.json',{'accessToken':'synthetic'})
            sender=Mock();worker=DeliveryWorker(root/'session.json',sender=sender,alert_sender=sender)
            worker.auth_alert.blocked('网关代码 1509',1000)
            with patch.object(worker.storage,'tick'):worker.tick(1000,budget_seconds=0)
            sender.assert_not_called()
            with worker.auth_alert.connect() as db:self.assertEqual(db.execute('SELECT state FROM auth_outbox').fetchone()[0],'pending')

    def test_pause_still_checks_storage_but_does_not_deliver_vehicle_alerts(self):
        from zeekr_control.delivery_runtime import DeliveryWorker
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private';save(root/'sampling.json',{'enabled':'false'})
            sender=Mock();worker=DeliveryWorker(root/'session.json',sender=sender,alert_sender=sender)
            worker.auth_alert.blocked('网关代码 1509',1000)
            with patch.object(worker.storage,'tick') as storage:worker.tick(1000)
            storage.assert_called_once();sender.assert_not_called()
            self.assertEqual(worker.status,'paused')

    def test_report_lock_prevents_recovery_of_a_live_sender(self):
        from zeekr_control.delivery_state import DeliveryBusy
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reports.sqlite3';report=demo_report();report.pop('demo')
            entered=threading.Event();release=threading.Event();renderer=Mock();renderer.render.return_value=b'PNG'
            sender=Mock();sender.send_markdown.side_effect=lambda _: (entered.set(),release.wait(2))
            thread=threading.Thread(target=lambda:PeriodicDelivery(path,renderer).deliver('a','v',report,sender))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(DeliveryBusy):PeriodicDelivery(path,renderer).deliver('a','v',report,sender)
                with sqlite3.connect(path) as db:self.assertEqual(db.execute('SELECT text FROM reports').fetchone()[0],'sending')
            finally:release.set();thread.join(2)
            self.assertEqual(sender.send_markdown.call_count,1)

    def test_reports_table_remains_writable_by_legacy_eight_value_insert(self):
        with tempfile.TemporaryDirectory() as folder:
            delivery=PeriodicDelivery(Path(folder)/'reports.sqlite3')
            with delivery.connect() as db,db:
                db.execute("INSERT INTO reports VALUES('old','{}','light','sent','sent',1,1,0)")
                self.assertEqual(len(db.execute('PRAGMA table_info(reports)').fetchall()),8)

    def test_trip_image_preparation_crash_recovers_and_never_claims_send_early(self):
        from zeekr_control.monitor import Monitor
        with tempfile.TemporaryDirectory() as folder:
            renderer=Mock();renderer.render_trip.side_effect=KeyboardInterrupt
            path=Path(folder)/'tracks.sqlite3';monitor=Monitor(path,map_renderer=renderer)
            report={'report_v2':{'schema_version':2,'start_time':1000,'end_time':2000,'metrics':{'distance_km':8}}}
            with monitor.tracks.connect() as db:
                db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created,delivery) VALUES('e','v','trip_end',?,'safe',0,'sent')",(json.dumps(report),))
                db.execute("INSERT INTO monitor_event_media(event_id,kind) VALUES('e','trip_image')")
            sender=Mock()
            with self.assertRaises(KeyboardInterrupt):monitor.deliver(sender,3000)
            with monitor.tracks.connect() as db:
                self.assertEqual(db.execute('SELECT delivery,attempts,prepare_attempts FROM monitor_event_media').fetchone(),('preparing',0,1))
            renderer.render_trip.side_effect=None;renderer.render_trip.return_value=b'PNG'
            Monitor(path,map_renderer=renderer).deliver(sender,4000)
            sender.send_image.assert_called_once_with(b'PNG')

    def test_legacy_sending_image_is_not_replayed_but_pending_text_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reports.sqlite3';delivery=PeriodicDelivery(path,Mock());report=demo_report();report.pop('demo')
            from zeekr_control.periodic_report import report_id
            with delivery.connect() as db,db:
                db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)',(report_id('a','v',report['period'],report['start_date'],report['end_date']),json.dumps(report),'light','pending','sending',0,1,0))
            sender=Mock();state=delivery.deliver('a','v',report,sender)
            self.assertEqual((state['text'],state['image']),('sent','unknown'))
            sender.send_markdown.assert_called_once();sender.send_image.assert_not_called()

    def test_supervised_child_exits_when_parent_control_pipe_closes(self):
        from zeekr_control.delivery_runtime import DeliveryProcess
        import os
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private';save(root/'sampling.json',{'enabled':'false'})
            process=DeliveryProcess(root/'session.json');process.ensure_running()
            self.assertIsNotNone(process.process)
            os.close(process.control);process.control=None
            try:self.assertEqual(process.process.wait(timeout=5),0)
            finally:process.close()

    def test_report_preparation_interruption_recovers_without_losing_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reports.sqlite3'; report=demo_report();report.pop('demo')
            renderer=Mock();renderer.render.side_effect=KeyboardInterrupt
            sender=Mock()
            with self.assertRaises(KeyboardInterrupt):
                PeriodicDelivery(path,renderer).deliver('owner','vehicle',report,sender)
            renderer.render.side_effect=None;renderer.render.return_value=b'PNG'
            result=PeriodicDelivery(path,renderer).deliver('owner','vehicle',report,sender)
            self.assertEqual(result['text'],'sent');self.assertEqual(result['image'],'sent')
            self.assertEqual(sender.send_markdown.call_count,1)
            self.assertEqual(sender.send_image.call_count,1)

    def test_monitor_construction_never_recovers_another_workers_send(self):
        from zeekr_control.monitor import Monitor
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'tracks.sqlite3';monitor=Monitor(path)
            with monitor.tracks.connect() as db:
                db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created,delivery) VALUES('event','car','trip_end','{}','message',0,'sending')")
            Monitor(path)
            with monitor.tracks.connect() as db:
                self.assertEqual(db.execute('SELECT delivery FROM monitor_events').fetchone()[0],'sending')

    def test_collection_tick_never_calls_any_notification_sender(self):
        from zeekr_control.monitor_runtime import Runner
        from zeekr_control.errors import ApiError
        class Client:
            def __init__(self,session):pass
            def vehicles(self):raise ApiError('网关代码 1509')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private';save(root/'session.json',{'accessToken':'synthetic'})
            sender=Mock(side_effect=AssertionError('collector sent a notification'))
            runner=Runner(root/'session.json',client_factory=Client,sender=sender,alert_sender=sender)
            try:runner.tick(1000)
            finally:runner.insight_worker.close()
            sender.assert_not_called()

    def test_health_is_readonly_scoped_and_never_exposes_payload(self):
        from zeekr_control.notification_health import read_health
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'periodic-reports.sqlite3';report=demo_report();report.pop('demo')
            renderer=Mock();renderer.render.return_value=b'PNG';sender=Mock()
            PeriodicDelivery(path,renderer).deliver('owner-a','car-a',report,sender)
            own=read_health(root,owner='owner-a',vehicle='car-a',context='current',now_ms=1000)
            other=read_health(root,owner='owner-b',vehicle='car-b',context='other',now_ms=1000)
            self.assertEqual(len(own['periodic_reports']),1)
            self.assertEqual(other['periodic_reports'],[])
            self.assertNotIn('metrics',json.dumps(own));self.assertNotIn('owner-a',json.dumps(own))
            self.assertEqual(own['context'],'current')
