import json
import sqlite3
import unittest
from unittest.mock import Mock, patch

from zeekr_control.analysis_cancel import AnalysisCancelled, cancellation_scope
from zeekr_control.movement_barriers import trip_start_between, trip_movement_between


class MovementBarrierTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE monitor_events(id INTEGER PRIMARY KEY,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')

    def save(self, payload, created, *, vehicle='car', kind='trip_start'):
        return self.db.execute('INSERT INTO monitor_events(vehicle,kind,summary,created) VALUES(?,?,?,?)',
                               (vehicle,kind,payload,created)).lastrowid

    def test_vehicle_time_and_each_callers_boundary_policy(self):
        for stamp, exclusive, inclusive in [(999,False,False),(1000,False,False),
                                            (1001,True,True),(2000,False,True),(2001,False,False)]:
            with self.subTest(stamp=stamp):
                self.db.execute('DELETE FROM monitor_events')
                self.save(json.dumps({'start_time':stamp}), 1500)
                self.assertEqual(trip_start_between(self.db,'car',1000,2000), exclusive)
                self.assertEqual(trip_start_between(self.db,'car',1000,2000,upper_inclusive=True), inclusive)

    def test_unknown_timestamp_preserves_write_window_and_invalid_payload_is_safe(self):
        for payload in ('not-json','[]','{}','{"start_time":true}','{"start_time":"1500"}',
                        '{"start_time":1e999}', '['*1200+'0'+']'*1200):
            for created, expected in [(999,False),(1000,False),(1500,True),(2000,False),(2001,False)]:
                with self.subTest(payload=payload[:25],created=created):
                    self.db.execute('DELETE FROM monitor_events')
                    self.save(payload, created)
                    self.assertEqual(trip_start_between(self.db,'car',1000,2000), expected)
                    if created == 1000:
                        self.assertTrue(trip_start_between(self.db,'car',1000,2000,unknown_lower_inclusive=True))
                    if created == 2000:
                        self.assertTrue(trip_start_between(self.db,'car',1000,2000,upper_inclusive=True))

    def test_unrelated_starts_cannot_hide_late_written_movement_and_read_is_pure(self):
        for _ in range(258):
            self.save('{"start_time":500}', 1500)
        self.save('{"start_time":1500}', 3000, vehicle='other')
        self.save('{"start_time":1500}', 3000, kind='charge_start')
        self.assertFalse(trip_start_between(self.db,'car',1000,2000))
        self.save('{"start_time":1500}', 3000)
        before = list(self.db.iterdump())
        self.assertTrue(trip_start_between(self.db,'car',1000,2000))
        self.assertEqual(list(self.db.iterdump()), before)

    def test_oversized_payload_uses_unknown_time_policy(self):
        self.save(json.dumps({'start_time':500,'padding':'x'*100}), 1500)
        with patch('zeekr_control.movement_barriers.MAX_SUMMARY_BYTES', 32):
            self.assertTrue(trip_start_between(self.db,'car',1000,2000))
        self.assertFalse(trip_start_between(self.db,'car',1000,2000))

    def test_cancelled_analysis_does_not_execute_query(self):
        cancelled = []
        db = Mock()
        with cancellation_scope(lambda: bool(cancelled)):
            cancelled.append(True)
            with self.assertRaises(AnalysisCancelled):
                trip_start_between(db,'car',1000,2000)
        db.execute.assert_not_called()

    def test_completed_trip_spans_use_overlap_not_write_time_or_endpoint_only(self):
        for start, end, expected in [(500,1000,False),(2000,2500,False),(1000,1000,False),
                                      (1000,2000,True),(999,2001,True),(1001,1500,True),
                                      (500,1001,True),(1999,2500,True)]:
            with self.subTest(start=start,end=end):
                self.db.execute('DELETE FROM monitor_events')
                self.save(json.dumps(dict(start_time=start,end_time=end)),3000,kind='trip_end')
                self.assertEqual(trip_movement_between(self.db,'car',1000,2000),expected)

    def test_explicit_review_anchors_are_excluded_but_other_movement_is_not(self):
        anchors = [self.save('{"start_time":500,"end_time":2500}',1500,kind='trip_end') for _ in range(2)]
        self.save('{"start_time":1200,"end_time":1800}',1500,kind='trip_end',vehicle='other')
        self.save('{"start_time":1500}',1500,kind='charge_start')
        self.assertFalse(trip_movement_between(self.db,'car',1000,2000,exclude_event_ids=anchors))
        self.save('{"start_time":1200,"end_time":1800}',3000,kind='trip_end')
        self.assertTrue(trip_movement_between(self.db,'car',1000,2000,exclude_event_ids=anchors))

    def test_partial_or_unreadable_trip_still_conservatively_blocks_review(self):
        for payload, created, expected in [('{"start_time":1500}',3000,True),
                                           ('{"end_time":1500}',3000,True),
                                           ('not-json',1500,True),('not-json',3000,False),
                                           ('{"start_time":2500,"end_time":500}',1500,True)]:
            with self.subTest(payload=payload,created=created):
                self.db.execute('DELETE FROM monitor_events')
                self.save(payload,created,kind='trip_end')
                self.assertEqual(trip_movement_between(self.db,'car',1000,2000),expected)

    def test_cancelled_review_does_not_execute_query(self):
        cancelled = []
        db = Mock()
        with cancellation_scope(lambda: bool(cancelled)):
            cancelled.append(True)
            with self.assertRaises(AnalysisCancelled):
                trip_movement_between(db,'car',1000,2000)
        db.execute.assert_not_called()

    def test_unknown_lower_boundary_policy_applies_to_both_movement_kinds(self):
        for kind in ('trip_start','trip_end'):
            with self.subTest(kind=kind):
                self.db.execute('DELETE FROM monitor_events')
                self.save('{}',1000,kind=kind)
                self.assertFalse(trip_movement_between(self.db,'car',1000,2000))
                self.assertTrue(trip_movement_between(self.db,'car',1000,2000,unknown_lower_inclusive=True))
