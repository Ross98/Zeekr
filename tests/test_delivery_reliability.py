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
    def test_commute_projection_uses_current_account_vehicle_and_guard(self):
        from zeekr_control.delivery_runtime import DeliveryWorker
        from zeekr_control.personal_store import account_scope
        from zeekr_control.delivery_state import DeliveryCancelled
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private'
            session={'accessToken':'synthetic','userId':'synthetic-user'}
            save(root/'session.json',session)
            save(root/'monitor-binding.json',{'vehicle_key':'car'})
            worker=DeliveryWorker(root/'session.json',sender=Mock(),alert_sender=None)
            with patch.object(worker.storage,'tick'), patch.object(worker.monitor,'deliver'),\
                 patch.object(worker.auth_alert,'deliver'):
                worker.tick(1000)
            event={'id':'synthetic'}
            with patch.object(worker.commute,'notification_places',return_value={}) as resolve:
                worker.monitor.commute_resolver('car',event)
                self.assertEqual(resolve.call_args.args,(account_scope(session),'car',event))
                resolve.call_args.kwargs['guard']()
                worker.monitor.commute_resolver('other-car',event)
                self.assertEqual(resolve.call_count,1)
                save(root/'session.json',{'accessToken':'other-synthetic','userId':'other-user'})
                with self.assertRaises(DeliveryCancelled):resolve.call_args.kwargs['guard']()

    def test_watchdog_uses_time_after_slow_storage_phase(self):
        from zeekr_control.delivery_runtime import DeliveryWorker
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private';save(root/'sampling.json',{'enabled':'false'})
            worker=DeliveryWorker(root/'session.json',sender=Mock(),alert_sender=Mock())
            worker.resource_watchdog=Mock();elapsed=[0.0]
            def storage(*args,**kwargs):elapsed[0]=20.0
            with patch('zeekr_control.delivery_runtime.time.monotonic',side_effect=lambda:elapsed[0]),\
                 patch.object(worker.storage,'tick',side_effect=storage),\
                 patch('zeekr_control.delivery_runtime.observer_sample',return_value={}) as sample:
                worker.tick(1000000)
            sample.assert_called_once_with(root,1020)
            self.assertEqual(worker.resource_watchdog.tick.call_args.args[1],1020)

    def test_rollback_requeues_tyre_preparation_but_preserves_actual_send_claim(self):
        from zeekr_control.personal_store import PersonalStore
        from zeekr_control.tyre_notifications import TyreNotifications
        from zeekr_control.delivery_state import normalize_preparation_for_rollback
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=PersonalStore(root/'personal.sqlite3')
            with store.connect(write=True) as db,db:
                TyreNotifications._tables(db)
                for status in ('preparing','sending','uncertain','sent'):
                    db.execute('INSERT INTO tyre_outbox(id,owner,vehicle,signature,created,payload,bark,wecom,attempts_bark) VALUES(?,?,?,?,?,?,?,?,?)',
                               (status,'owner','vehicle','sig',1000,'{}',status,status,2))
            normalize_preparation_for_rollback(root)
            with store.connect() as db:
                for identity,bark,wecom,attempts in db.execute('SELECT id,bark,wecom,attempts_bark FROM tyre_outbox'):
                    expected='pending' if identity=='preparing' else identity
                    self.assertEqual((bark,wecom,attempts),(expected,expected,2))

    def test_bark_preparation_failure_is_unsent_but_ambiguous_send_is_not_retried(self):
        from zeekr_control.monitor import Monitor
        from zeekr_control.notifications import DeliveryError
        with tempfile.TemporaryDirectory() as folder:
            monitor=Monitor(Path(folder)/'tracks.sqlite3')
            with monitor.tracks.connect() as db:
                db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES('event','car','trip_start','[]','safe',1000)")
                db.execute("INSERT INTO monitor_event_alerts(event_id) VALUES('event')")
            sender=Mock()
            monitor._deliver_alerts(sender,1000)
            sender.assert_not_called()
            with monitor.tracks.connect() as db:
                self.assertEqual(db.execute('SELECT delivery,attempts FROM monitor_event_alerts').fetchone(),('failed',0))
                db.execute("UPDATE monitor_events SET summary=? WHERE id='event'",(json.dumps({'start_time':1000}),))
                db.execute("UPDATE monitor_event_alerts SET delivery='pending'")
            sender.side_effect=DeliveryError('synthetic timeout',ambiguous=True)
            monitor._deliver_alerts(sender,2000)
            monitor._deliver_alerts(sender,3000)
            self.assertEqual(sender.call_count,1)
            with monitor.tracks.connect() as db:
                self.assertEqual(db.execute('SELECT delivery,attempts FROM monitor_event_alerts').fetchone(),('uncertain',1))

    def test_interrupted_bark_preparation_can_resume_without_counting_a_send(self):
        from unittest.mock import patch
        from zeekr_control.monitor import Monitor
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'tracks.sqlite3';monitor=Monitor(path)
            with monitor.tracks.connect() as db:
                db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES('event','car','trip_start',?,'safe',1000)",
                           (json.dumps({'start_time':1000}),))
                db.execute("INSERT INTO monitor_event_alerts(event_id) VALUES('event')")
            sender=Mock()
            with patch('zeekr_control.monitor.bark_message_for',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
                monitor._deliver_alerts(sender,1000)
            sender.assert_not_called()
            with monitor.tracks.connect() as db:
                self.assertEqual(db.execute('SELECT delivery,attempts FROM monitor_event_alerts').fetchone(),('preparing',0))
            monitor=Monitor(path)
            monitor.deliver(Mock(),2000,alert_sender=sender)
            self.assertEqual(sender.call_count,1)
            with monitor.tracks.connect() as db:
                self.assertEqual(db.execute('SELECT delivery,attempts FROM monitor_event_alerts').fetchone(),('sent',1))

    def test_bark_rechecks_delivery_guard_after_preparation(self):
        from unittest.mock import patch
        from zeekr_control.delivery_runtime import DeliveryWorker
        from zeekr_control.sampling import save_settings
        from zeekr_control.snapshots import session_scope
        for change in ('pause','account','vehicle','shutdown','deadline'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)/'private';session={'accessToken':'synthetic-original'}
                save(root/'session.json',session);save(root/'monitor-binding.json',{'vehicle_key':'car'})
                save_settings(root,True)
                bark=Mock();worker=DeliveryWorker(root/'session.json',sender=Mock(),alert_sender=bark)
                with worker.monitor.tracks.connect() as db:
                    db.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES('event','car','trip_start',?,'safe',1000)",
                               (json.dumps({'start_time':1000,'end_time':2000,'partial':True}),))
                    db.execute("INSERT INTO monitor_event_alerts(event_id) VALUES('event')")
                def prepare(*args):
                    if change=='pause':save_settings(root,False)
                    elif change=='account':save(root/'session.json',{'accessToken':'synthetic-other'})
                    elif change=='vehicle':save(root/'monitor-binding.json',{'vehicle_key':'other-car'})
                    elif change=='shutdown':worker.stop.set()
                    else:worker.deadline=0
                    return 'synthetic title','synthetic body'
                guard=lambda:worker.guard(session_scope(session),'car')
                with patch('zeekr_control.monitor.bark_message_for',side_effect=prepare):
                    worker.monitor._deliver_alerts(bark,1000,guard,'car')
                bark.assert_not_called()
                with worker.monitor.tracks.connect() as db:
                    row=db.execute('SELECT delivery,attempts FROM monitor_event_alerts').fetchone()
                    self.assertEqual(row,('pending',0))
                save_settings(root,True);save(root/'session.json',session)
                save(root/'monitor-binding.json',{'vehicle_key':'car'})
                worker.stop.clear();worker.deadline=None
                worker.monitor._deliver_alerts(bark,2000,guard,'car')
                self.assertEqual(bark.call_count,1)
                worker.monitor._deliver_alerts(bark,3000,guard,'car')
                self.assertEqual(bark.call_count,1)

    def test_health_merges_latest_events_before_limiting_each_page(self):
        from zeekr_control.monitor import Monitor
        from zeekr_control.personal_store import PersonalStore
        from zeekr_control.custom_reminders import Reminders
        from zeekr_control.tyre_notifications import TyreNotifications
        from zeekr_control.notification_health import read_health
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);monitor=Monitor(root/'tracks.sqlite3')
            with monitor.tracks.connect() as db:
                db.executemany("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created,delivery) VALUES(?,?,'trip_end','{}','safe',?,'sent')",
                    [(f'vehicle-{i}','v',i*3) for i in range(40)])
            with PersonalStore(root/'personal.sqlite3').connect(write=True) as db,db:
                Reminders._tables(db);TyreNotifications._tables(db)
                db.executemany("INSERT INTO rule_history(id,owner,vehicle,kind,created,delivery) VALUES(?,'o','v','low_soc',?,'sent')",
                    [(f'custom-{i}',i*3+1) for i in range(40)])
                db.executemany("INSERT INTO tyre_outbox(id,owner,vehicle,created,bark,wecom) VALUES(?,'o','v',?,'sent','sent')",
                    [(f'tyre-{i}',i*3+2) for i in range(40)])
                db.execute("UPDATE tyre_outbox SET bark='failed' WHERE id IN ('tyre-0','tyre-39')")
                db.execute("INSERT INTO tyre_outbox(id,owner,vehicle,created,bark,wecom) VALUES('other','other','v',1000,'failed','sent')")
            health=read_health(root,owner='o',vehicle='v',now_ms=2000)
            self.assertEqual([e['created_at'] for e in health['events']],list(range(119,89,-1)))
            self.assertEqual(health['events'][0]['id'],'tyre-39')
            self.assertEqual(health['events'][0]['parts']['bark']['state'],'failed')
            self.assertEqual(health['summary']['failed_events'],2)
            self.assertTrue(health['summary']['complete'])

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
