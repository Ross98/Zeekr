"""Synthetic delivery durations; no network or real map rendering."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from zeekr_control.monitor import Monitor
from zeekr_control.notifications import DeliveryError
from zeekr_control.focused_trip_image import ImagePreparationError
from test_monitor import BASE

NOW=BASE+600000


class EventDeliveryTimingTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.monitor=Monitor(Path(temp.name)/'tracks.sqlite3')

    def seed(self,identity='event',kind='trip_end',image=False):
        summary=dict(start_time=BASE,end_time=BASE+300000,duration_seconds=300,distance_km=10,
                     start_soc=80,end_soc=70,soc_delta=-10,partial=False,addresses_resolved=True)
        if image:summary['report_v2']=dict(schema_version=2,start_time=BASE,end_time=BASE+300000,
                                           metrics=dict(distance_km=10))
        with self.monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created,delivery) VALUES(?,?,?,?,?,?,?)',
                       (identity,'car',kind,json.dumps(summary),'safe',NOW,'sent' if image else 'pending'))
            if image:db.execute("INSERT INTO monitor_event_media(event_id,kind) VALUES(?,'trip_image')",(identity,))
            if kind=='charge_start':db.execute('INSERT INTO monitor_event_alerts(event_id) VALUES(?)',(identity,))

    def test_slow_text_failure_keeps_full_retry_wait(self):
        self.seed();clock=[100.0];calls=[]
        def fail(message):
            calls.append(message);clock[0]+=20;raise DeliveryError('synthetic failure')
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.monitor.deliver(fail,NOW)
            self.monitor.deliver(fail,NOW+60000)
        self.assertEqual(len(calls),1)
        with self.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT next_attempt FROM monitor_events').fetchone()[0],NOW+80000)

    def test_slow_bark_failure_keeps_full_retry_wait(self):
        self.seed(kind='charge_start');clock=[100.0];calls=[]
        def fail(*message):
            calls.append(message);clock[0]+=20;raise DeliveryError('synthetic failure')
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.monitor.deliver(None,NOW,alert_sender=fail)
            self.monitor.deliver(None,NOW+60000,alert_sender=fail)
        self.assertEqual(len(calls),1)

    def test_slow_image_failure_keeps_full_retry_wait(self):
        self.seed(image=True);clock=[100.0];calls=[]
        self.monitor.map_renderer=SimpleNamespace(render_trip=lambda *args:b'synthetic image')
        def fail(image):
            calls.append(image);clock[0]+=20;raise DeliveryError('synthetic failure')
        sender=SimpleNamespace(send_image=fail)
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.monitor._deliver_images(sender,NOW)
            self.monitor._deliver_images(sender,NOW+60000)
        self.assertEqual(len(calls),1)

    def test_image_preparation_failure_backoff_includes_rendering_duration(self):
        self.seed(image=True);clock=[100.0];calls=[]
        def render(*arguments):
            calls.append(True);clock[0]+=20
            raise ImagePreparationError('synthetic retryable preparation',retryable=True)
        self.monitor.map_renderer=SimpleNamespace(render_trip=render)
        sender=SimpleNamespace(send_image=lambda content:self.fail('must not send'))
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.monitor._deliver_images(sender,NOW)
            self.monitor._deliver_images(sender,NOW+60000)
        self.assertEqual(len(calls),1)
        with self.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT attempts,prepare_attempts,next_attempt FROM monitor_event_media').fetchone(),
                             (0,1,NOW+80000))

    def test_slow_bark_phase_allows_text_already_due_by_its_phase(self):
        self.seed('alert',kind='charge_start');self.seed('text')
        with self.monitor.tracks.connect() as db:
            db.execute("UPDATE monitor_events SET next_attempt=? WHERE id='text'",(NOW+10000,))
        clock=[100.0];messages=[]
        def bark(*arguments):clock[0]+=20
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.monitor.deliver(messages.append,NOW,alert_sender=bark)
        self.assertEqual(messages,['safe'])

    def test_success_timestamp_records_ack_completion_not_batch_start(self):
        self.seed();clock=[100.0]
        def slow_success(message):clock[0]+=20
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.monitor.deliver(slow_success,NOW)
        with self.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT sent_at FROM monitor_events').fetchone()[0],NOW+20000)

    def test_text_retry_limit_preserves_documented_six_attempt_policy(self):
        self.seed();calls=[]
        def fail(message):calls.append(message);raise DeliveryError('synthetic failure')
        with patch('time.monotonic',return_value=100.0):
            for step in range(8):self.monitor.deliver(fail,NOW+step*7200000)
        self.assertEqual(len(calls),6)
        self.assertEqual(self.monitor.events()[0]['delivery'],'failed')

    def test_bark_retry_limit_preserves_documented_six_attempt_policy(self):
        self.seed(kind='charge_start');calls=[]
        def fail(*arguments):calls.append(arguments);raise DeliveryError('synthetic failure')
        with patch('time.monotonic',return_value=100.0):
            for step in range(8):self.monitor.deliver(None,NOW+step*7200000,alert_sender=fail)
        self.assertEqual(len(calls),6)
        with self.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT delivery,attempts FROM monitor_event_alerts').fetchone(),('failed',6))

    def test_image_retry_limit_preserves_documented_six_attempt_policy(self):
        self.seed(image=True);calls=[]
        self.monitor.map_renderer=SimpleNamespace(render_trip=lambda *args:b'synthetic image')
        def fail(content):calls.append(content);raise DeliveryError('synthetic failure')
        sender=SimpleNamespace(send_image=fail)
        with patch('time.monotonic',return_value=100.0):
            for step in range(8):self.monitor._deliver_images(sender,NOW+step*7200000)
        self.assertEqual(len(calls),6)
        with self.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT delivery,attempts FROM monitor_event_media').fetchone(),('failed',6))
