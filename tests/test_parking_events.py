import unittest
import tempfile
import sqlite3
import json
from pathlib import Path

from zeekr_control.parking_events import build_events
from zeekr_control.parking_analytics import ParkingAnalytics
from zeekr_control.tracks import day_bounds


class ParkingEventTests(unittest.TestCase):
    def trip(self, identity, start, end, start_soc, end_soc):
        return {'id': identity, 'kind': 'trip_end', 'start_time': start, 'end_time': end,
                'start_soc': start_soc, 'end_soc': end_soc, 'partial': False}

    def sample(self, minute, soc, *, charging=False, km=100, off=True):
        time = minute * 60000
        return {'record': {'key': str(minute), 'state_time': time, 'observed_at': time,
                           'flags': [], 'change': 'new'},
                'state': {'soc': soc, 'charging': charging, 'km': km, 'off': off, 'speed': 0}}

    def test_gap_keeps_one_event_but_blocks_consumption(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 2400000, 3000000, 68, 67)]
        samples = [self.sample(5, 70), self.sample(6, 70), self.sample(35, 68), self.sample(40, 68)]
        result = build_events(trips, [], samples, 0, 3600000, 86)
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['status'], 'uncertain')
        self.assertIn('gap', result['events'][0]['reasons'])
        self.assertIsNone(result['events'][0]['soc_drop'])

    def test_continuous_observation_can_calculate(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 69, 68)]
        samples = [self.sample(minute, 70 if minute < 15 else 69) for minute in (5, 10, 15, 20)]
        row = build_events(trips, [], samples, 0, 2400000, 86)['events'][0]
        self.assertEqual(row['status'], 'comparable')
        self.assertEqual(row['soc_drop'], 1)
        self.assertEqual(row['estimated_kwh'], .86)

    def test_charge_blocks_consumption_without_splitting_event(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 75, 74)]
        samples = [self.sample(minute, 70 if minute == 5 else 75, charging=minute == 10)
                   for minute in (5, 10, 15, 20)]
        row = build_events(trips, [], samples, 0, 2400000, 86)['events'][0]
        self.assertEqual(row['status'], 'uncertain')
        self.assertIn('charging', row['reasons'])

    def test_charge_history_blocks_even_when_charge_samples_are_missing(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 75, 74)]
        samples = [self.sample(minute, 70 if minute < 15 else 75) for minute in (5, 10, 15, 20)]
        charge = {'kind': 'charge_end', 'start_time': None, 'end_time': 900000}
        row = build_events(trips, [charge], samples, 0, 2400000, 86)['events'][0]
        self.assertEqual(row['status'], 'uncertain')
        self.assertIn('charging', row['reasons'])

    def test_last_trip_creates_open_candidate_without_energy(self):
        trips = [self.trip('a', 0, 300000, 72, 70)]
        samples = [self.sample(5, 70), self.sample(10, 69)]
        row = build_events(trips, [], samples, 0, 1200000, 86)['events'][0]
        self.assertTrue(row['open'])
        self.assertIsNone(row['soc_drop'])
        self.assertEqual(row['end_time'], 600000)

    def test_unknown_charging_state_blocks_energy(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 69, 68)]
        samples = [self.sample(minute, 70 if minute < 15 else 69) for minute in (5, 10, 15, 20)]
        samples[1]['state']['charging'] = None
        row = build_events(trips, [], samples, 0, 2400000, 86)['events'][0]
        self.assertEqual(row['status'], 'uncertain')

    def test_stale_vehicle_time_blocks_energy(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 69, 68)]
        samples = [self.sample(minute, 70 if minute < 15 else 69) for minute in (5, 10, 15, 20)]
        samples[1]['record']['state_time'] = 0
        row = build_events(trips, [], samples, 0, 2400000, 86)['events'][0]
        self.assertEqual(row['status'], 'uncertain')

    def test_missing_speed_with_stable_odometer_is_parked(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 69, 68)]
        samples = [self.sample(minute, 70 if minute < 15 else 69) for minute in (5, 10, 15, 20)]
        for sample in samples:
            sample['state']['speed'] = None
        row = build_events(trips, [], samples, 0, 2400000, 86)['events'][0]
        self.assertEqual(row['status'], 'comparable')

    def test_repeat_cache_does_not_invalidate_parking_evidence(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 69, 68)]
        samples = [self.sample(minute, 70 if minute < 15 else 69) for minute in (5, 10, 15, 20)]
        repeat = self.sample(12, 70)
        repeat['record']['change'] = 'repeat'
        repeat['record']['state_time'] = 300000
        samples.insert(2, repeat)
        row = build_events(trips, [], samples, 0, 2400000, 86)['events'][0]
        self.assertEqual(row['status'], 'comparable')

    def test_query_uses_adjacent_saved_trips_across_date_boundary(self):
        lower, upper = day_bounds('2026-09-20')
        first = self.trip('a', lower-1200000, lower-300000, 72, 70)
        second = self.trip('b', lower+1200000, lower+1800000, 69, 68)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tracks.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE monitor_events (id TEXT,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
                for trip in (first, second):
                    summary = dict(trip, duration_seconds=(trip['end_time']-trip['start_time'])/1000)
                    db.execute('INSERT INTO monitor_events VALUES (?,?,?,?,?)',
                               (trip['id'], 'car', 'trip_end', json.dumps(summary), trip['end_time']))
            path.chmod(0o600)
            class Archive:
                def iter_records(self, scope, vehicle, start, end):
                    for minute, soc in ((0,70),(5,70),(10,69),(15,69)):
                        stamp=lower+minute*60000
                        if start <= stamp < end:
                            yield ({'key':str(minute),'state_time':stamp,'observed_at':stamp,
                                    'flags':[],'change':'new'},
                                   {'basicVehicleStatus':{}})
            result = ParkingAnalytics(Archive(), path).query('scope','car','2026-09-20','2026-09-20',86)
            self.assertEqual(len(result['events']),1)
            self.assertEqual(result['events'][0]['start_trip_id'],'a')

    def test_query_splits_long_archive_reads(self):
        lower, upper = day_bounds('2026-09-20')
        trips = [self.trip('a', float(lower-21*86400000-600000), float(lower-21*86400000), 72, 70),
                 self.trip('b', float(lower+21*86400000), float(lower+21*86400000+600000), 69, 68)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tracks.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE monitor_events (id TEXT,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
                for trip in trips:
                    summary = dict(trip, duration_seconds=600)
                    db.execute('INSERT INTO monitor_events VALUES (?,?,?,?,?)',
                               (trip['id'], 'car', 'trip_end', json.dumps(summary), trip['end_time']))
            path.chmod(0o600)
            class Archive:
                def iter_records(self, scope, vehicle, start, end):
                    if type(start) is not int or type(end) is not int:
                        raise ValueError('归档分析范围无效。')
                    if end-start > 33*86400000:
                        raise ValueError('归档分析范围无效。')
                    return iter(())
            result = ParkingAnalytics(Archive(), path).query('scope','car','2026-09-20','2026-09-20',86)
            self.assertEqual(len(result['events']),1)


if __name__ == '__main__':
    unittest.main()
