"""Exact v6 output parity with one-pass inputs and bounded working storage."""
import copy
import random
import sqlite3
import unittest
from unittest.mock import patch

from parking_events_v6_oracle import build_events as reference
from zeekr_control.parking_events import build_events
from zeekr_control.parking_analytics import analyze_parking
from zeekr_control.analysis_work import AnalysisCapacity, SampleStore, TimeMap, WorkDatabase


def sample(index):
    stamp = 1704067200000 + index * 60000
    return {'record': {'key': str(index), 'state_time': stamp, 'observed_at': stamp,
                      'flags': [], 'change': 'new'},
            'state': {'soc': 70-index/100, 'charging': False, 'km': 100, 'off': True,
                      'gear': 'P', 'speed': 0},
            'location': {'valid': True, 'latitude': 30, 'longitude': 120,
                         'coordinate_system': 'WGS84（社区解释）'}}


class ParkingStreamingTests(unittest.TestCase):
    def test_enter_failure_cleans_scratch_and_maps_full(self):
        work = WorkDatabase()
        with patch('zeekr_control.analysis_work.sqlite3.connect',
                   side_effect=sqlite3.OperationalError('database or disk is full')):
            with self.assertRaises(AnalysisCapacity):
                with work:pass
        self.assertFalse(work.path.parent.exists())

    def test_time_map_schema_failure_cleans_scratch_and_maps_full(self):
        work = TimeMap()
        def execute(sql):
            if sql.startswith('CREATE TABLE'):raise sqlite3.OperationalError('database or disk is full')
        with patch('zeekr_control.analysis_work.sqlite3.connect') as connect:
            connect.return_value.execute.side_effect = execute
            with self.assertRaises(AnalysisCapacity):
                with work:pass
            connect.return_value.close.assert_called_once()
        self.assertFalse(work.path.parent.exists())

    def test_result_fragments_have_an_explicit_memory_budget(self):
        rows = [sample(0), sample(1)]
        lower, upper = rows[0]['record']['state_time'], rows[-1]['record']['state_time']+1
        with patch('zeekr_control.analysis_work.MAX_RESULT_BYTES', 1):
            with self.assertRaises(AnalysisCapacity):
                analyze_parking(iter(rows), lower, upper)
            with self.assertRaises(AnalysisCapacity):
                build_events([], [], iter(rows), lower, upper)

    def test_sqlite_full_cleans_private_scratch_and_returns_capacity_error(self):
        with self.assertRaises(AnalysisCapacity):
            with WorkDatabase() as work:
                path = work.path
                work.db.execute('CREATE TABLE filling(value TEXT)')
                work.db.execute('PRAGMA max_page_count=2')
                work.db.execute('INSERT INTO filling VALUES (?)', ('x'*65536,))
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())

    def test_private_scratch_is_deleted_and_does_not_store_raw_responses(self):
        row = sample(1)
        row['raw'] = {'accessToken': 'DO-NOT-STORE-THIS', 'irrelevant': 'x'*10000}
        with SampleStore(iter([row])) as work:
            path = work.path
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            self.assertEqual(path.parent.stat().st_mode & 0o077, 0)
            self.assertNotIn('DO-NOT-STORE-THIS', '\n'.join(work.db.iterdump()))
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())

    def test_generator_matches_v6_on_mixed_time_location_and_charge_evidence(self):
        rng = random.Random(88117)
        base = sample(0)['record']['state_time']
        for case in range(70):
            rows = [sample(i) for i in range(40)]
            for index, row in enumerate(rows):
                choice = rng.randrange(12)
                if choice == 0: row['record']['flags'] = ['stale']
                if choice == 1: row['record']['state_time'] = None
                if choice == 2: row['state']['charging'] = None
                if choice == 3: row['state']['soc'] = None
                if choice == 4: row['location'] = {'valid': False}
                if choice == 5: row['location']['latitude'] += .00003
                if choice == 6: row['state']['km'] += 1
                if choice == 7: row['state']['speed'] = 2
                if choice == 8 and index:
                    row['record']['state_time'] = rows[index-1]['record']['state_time']
                    row['record']['change'] = rng.choice(['repeat', 'revision'])
                if choice == 9:
                    row['record']['state_time'] -= 180000
                    row['record']['change'] = 'regression'
                if choice == 10: row['record']['observed_at'] += 45000
            rng.shuffle(rows)
            trips = [{'id': 'a', 'kind': 'trip_end', 'start_time': base-600000,
                      'end_time': base, 'start_soc': 71, 'end_soc': 70, 'partial': False},
                     {'id': 'b', 'kind': 'trip_end', 'start_time': base+39*60000,
                      'end_time': base+45*60000, 'start_soc': 69.61, 'end_soc': 69, 'partial': False}]
            charges = [{'start_time': base+10*60000, 'end_time': base+15*60000}]
            with self.subTest(case=case):
                expected = reference(trips, charges, copy.deepcopy(rows), base, base+50*60000, 86)
                actual = build_events(trips, charges, iter(copy.deepcopy(rows)), base, base+50*60000, 86)
                self.assertEqual(actual, expected)
