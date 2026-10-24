"""Temporary SQLite fault injection; no real collection or notifications."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.monitor import Monitor
from zeekr_control.report_telemetry import normalize
from test_monitor import BASE,sample


class MonitorReportFailureTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.monitor=Monitor(Path(folder.name)/'tracks.sqlite3')

    def waiting_trip(self):
        for second in range(0,661,60):
            raw=sample(second,km=100 if second==0 else 101 if second==60 else 110,
                       speed=30 if second==60 else 0,
                       engine='engine_on' if second==60 else 'engine_off',ready=int(second==60))
            self.monitor.observe('car',raw,BASE+second*1000)

    def snapshot(self):
        with self.monitor.tracks.connect() as db:
            return {table:db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                    for table in ('monitor_state','monitor_events','report_observations',
                                  'report_metric_index','monitor_event_alerts','monitor_event_media')}

    def test_database_comparison_failure_aborts_settlement_and_can_retry(self):
        self.waiting_trip();before=self.snapshot()
        with patch('zeekr_control.monitor.compare',side_effect=sqlite3.OperationalError('synthetic I/O error')):
            with self.assertRaises(sqlite3.OperationalError):
                self.monitor.observe('car',sample(720,km=110),BASE+720000)
        self.assertEqual(self.snapshot(),before)
        self.monitor.observe('car',sample(720,km=110),BASE+720000)
        self.monitor.observe('car',sample(720,km=110),BASE+720000)
        with self.monitor.tracks.connect() as db:
            rows=db.execute("SELECT summary FROM monitor_events WHERE kind='trip_end'").fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(json.loads(rows[0][0])['distance_km'],10)
        self.assertIsNone(self.monitor.status('car')['trip'])

    def test_filesystem_comparison_failure_does_not_commit_settlement(self):
        self.waiting_trip();before=self.snapshot()
        with patch('zeekr_control.monitor.compare',side_effect=OSError('synthetic storage error')):
            with self.assertRaises(OSError):
                self.monitor.observe('car',sample(720,km=110),BASE+720000)
        self.assertEqual(self.snapshot(),before)

    def test_charge_end_database_failure_keeps_active_session_for_retry(self):
        self.monitor.observe('car',sample(0,soc=40),BASE)
        for second,soc in ((60,40),(120,50)):
            self.monitor.observe('car',sample(second,soc=soc,current=10,voltage=350,
                                             code='charging',dc_lid=1,charger=7,plug=1),BASE+second*1000)
        self.assertIsNotNone(self.monitor.status('car')['charge'])
        before=self.snapshot();stopped=sample(180,soc=60,code='stopped',dc_lid=1)
        with patch('zeekr_control.monitor.compare',side_effect=sqlite3.DatabaseError('synthetic read fault')):
            with self.assertRaises(sqlite3.DatabaseError):
                self.monitor.observe('car',stopped,BASE+180000)
        self.assertEqual(self.snapshot(),before)
        self.monitor.observe('car',stopped,BASE+180000)
        self.monitor.observe('car',stopped,BASE+180000)
        with self.monitor.tracks.connect() as db:
            rows=db.execute("SELECT summary FROM monitor_events WHERE kind='charge_end'").fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(json.loads(rows[0][0])['soc_delta'],20)
        self.assertIsNone(self.monitor.status('car')['charge'])

    def test_engine_rollback_cannot_be_followed_by_a_partial_new_commit(self):
        with self.monitor.tracks.connect() as db:
            db.execute('CREATE TABLE frame_marker(value INTEGER)')
            db.execute('CREATE TABLE abort_probe(value INTEGER)')
            db.execute("CREATE TRIGGER abort_frame BEFORE INSERT ON abort_probe BEGIN SELECT RAISE(ROLLBACK,'synthetic engine rollback'); END")
        start=normalize(sample(0,km=100,soc=80),BASE)
        end=normalize(sample(600,km=110,soc=70),BASE+600000)
        data=dict(start_time=BASE,end_time=BASE+600000,duration_seconds=600,distance_km=10,
                  start_soc=80,end_soc=70,soc_delta=-10,partial=False,battery_capacity_kwh=86)
        data['report_v2']=self.monitor._report('trip_end',start,end,[start,end],{},False)
        before=self.snapshot()
        def fail(db,*args):
            self.assertTrue(db.in_transaction)
            try:db.execute('INSERT INTO abort_probe VALUES(1)')
            except sqlite3.IntegrityError:
                self.assertFalse(db.in_transaction)
                raise
        with self.assertRaises(sqlite3.IntegrityError):
            with self.monitor.tracks.connect() as db:
                db.execute('INSERT INTO frame_marker VALUES(1)')
                with patch('zeekr_control.monitor.compare',side_effect=fail):
                    self.monitor._event(db,'car','trip_end',data,BASE+720000)
        self.assertEqual(self.snapshot(),before)
        with self.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM frame_marker').fetchone()[0],0)
            db.execute('INSERT INTO frame_marker VALUES(1)')
            self.monitor._event(db,'car','trip_end',data,BASE+720000)
        with self.monitor.tracks.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM frame_marker').fetchone()[0],1)
            for table in ('monitor_events','monitor_event_alerts','monitor_event_media','report_metric_index'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],1)

    def test_optional_calculation_error_still_degrades_comparison_only(self):
        self.waiting_trip()
        with patch('zeekr_control.monitor.compare',side_effect=ValueError('synthetic optional calculation')):
            self.monitor.observe('car',sample(720,km=110),BASE+720000)
        with self.monitor.tracks.connect() as db:
            rows=db.execute("SELECT summary FROM monitor_events WHERE kind='trip_end'").fetchall()
        self.assertEqual(len(rows),1)
        report=json.loads(rows[0][0])
        self.assertEqual(report['distance_km'],10)
        self.assertFalse(report['report_v2']['comparison']['available'])
        self.assertEqual(report['report_v2']['comparison']['reason'],'unavailable')
