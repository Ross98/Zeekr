import unittest
import tempfile
import sqlite3
import json
from unittest.mock import patch
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
                'location': {'valid': True, 'latitude': 30, 'longitude': 120, 'coordinate_system': 'test'},
                'state': {'soc': soc, 'charging': charging, 'km': km, 'off': off, 'speed': 0}}

    def test_gps_drift_with_stationary_evidence_keeps_one_parking(self):
        trips = [self.trip('a', 0, 300000, 72, 70),
                 self.trip('b', 1200000, 1800000, 70, 69)]
        samples = [self.sample(minute, 70) for minute in (5, 10, 15, 20)]
        for row, offset in zip(samples, (0, .00008, -.00004, .00002)):
            row['location']['latitude'] += offset
            row['state']['gear'] = 'P'
        result = build_events(trips, [], samples, 0, 2400000, 86)
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['sample_count'], 4)
        self.assertEqual(result['events'][0]['status'], 'comparable')

    def test_drift_tolerance_does_not_follow_slow_movement(self):
        trips = [self.trip('a', 0, 300000, 72, 70),
                 self.trip('b', 1800000, 2100000, 70, 69)]
        samples = [self.sample(minute, 70) for minute in (5, 10, 15, 20, 25, 30)]
        for index, row in enumerate(samples):
            row['location']['latitude'] += index * .00008
        result = build_events(trips, [], samples, 0, 2400000)
        self.assertGreater(len(result['events']), 1)
        self.assertTrue(all(row['status'] == 'uncertain' for row in result['events']))

    def test_small_gps_change_with_movement_evidence_never_merges(self):
        for change in ({'km': 101}, {'speed': 1}, {'gear': 'D'}, {'off': False}):
            with self.subTest(change=change):
                samples = [self.sample(minute, 70) for minute in (5, 10, 15, 20)]
                for row in samples[2:]:
                    row['location']['latitude'] += .00002
                    row['state'].update(change)
                result = build_events([], [], samples, 0, 1500000)
                self.assertGreater(len(result['events']), 1)
                self.assertTrue(all(row['status'] == 'uncertain' for row in result['events']))

    def test_same_gps_with_odometer_change_blocks_energy(self):
        trips = [self.trip('a', 0, 300000, 72, 70),
                 self.trip('b', 1200000, 1800000, 70, 69)]
        samples = [self.sample(minute, 70) for minute in (5, 10, 15, 20)]
        samples[-1]['state']['km'] = 101
        result = build_events(trips, [], samples, 0, 2400000)
        self.assertEqual(len(result['events']), 1)
        self.assertTrue(all(row['soc_drop'] is None for row in result['events']))

    def test_drift_without_stationary_support_is_not_merged(self):
        samples = [self.sample(minute, 70, off=None, km=None) for minute in (5, 10, 15, 20)]
        for row in samples[2:]:
            row['location']['latitude'] += .00002
        self.assertGreater(len(build_events([], [], samples, 0, 1500000)['events']), 1)

    def test_coordinate_system_change_is_not_gps_drift(self):
        samples = [self.sample(minute, 70) for minute in (5, 10, 15, 20)]
        for row in samples[2:]:
            row['location']['coordinate_system'] = 'other'
        self.assertGreater(len(build_events([], [], samples, 0, 1500000)['events']), 1)

    def test_gps_drift_keeps_gaps_and_charging_energy_gates(self):
        trips = [self.trip('a', 0, 300000, 72, 70),
                 self.trip('b', 2400000, 3000000, 70, 69)]
        samples = [self.sample(minute, 70) for minute in (5, 6, 35, 40)]
        for row in samples[2:]:
            row['location']['latitude'] += .00002
        result = build_events(trips, [], samples, 0, 3600000, 86)
        self.assertEqual(len(result['events']), 1)
        self.assertIn('gap', result['events'][0]['reasons'])
        self.assertIsNone(result['events'][0]['estimated_kwh'])
        charge = {'start_time': 600000, 'end_time': 1800000}
        events = build_events(trips, [charge], samples, 0, 3600000, 86)['events']
        self.assertEqual(len(events), 2)
        self.assertTrue(all(row['end_time'] <= 600000 or row['start_time'] >= 1800000 for row in events))
        self.assertTrue(all(row['estimated_kwh'] is None for row in events))

    def test_query_assigns_single_and_delayed_fragments(self):
        lower, _ = day_bounds('2026-10-03')
        cases = (((5,), (2000,), 'observed', 0),
                 ((5, 6), (9000, 9000), 'observed', 0),
                 ((5,), (2000,), 'vehicle_endpoint', 0),
                 ((5, 6), (2000, 2000), 'inside_trip', 1))
        for minutes, delays, kind, orphan_count in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'tracks.sqlite3'
                with sqlite3.connect(path) as db:
                    db.execute('CREATE TABLE monitor_events (id TEXT,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
                path.chmod(0o600)
                rows = [self.sample(minute, 70) for minute in minutes]
                for row, delay in zip(rows, delays):
                    row['record']['state_time'] += lower
                    row['record']['observed_at'] += lower + delay
                class Archive:
                    def iter_records(self, *args):
                        return iter((row['record'], row) for row in rows)
                stamp = rows[-1]['record']['observed_at']
                if kind == 'vehicle_endpoint':
                    stamp = rows[-1]['record']['state_time'] - 60000
                elif kind == 'inside_trip':
                    stamp += 600000
                events = {'events': [{'start_time': stamp, 'end_time': stamp + 60000}]}
                with patch('zeekr_control.parking_analytics.decode', side_effect=lambda raw: raw['state']), patch('zeekr_control.parking_analytics.parse_location', side_effect=lambda raw: raw['location']), patch('zeekr_control.parking_analytics.build_events', return_value=events):
                    result = ParkingAnalytics(Archive(), path).query('scope', 'car', '2026-10-03', '2026-10-03')
                self.assertEqual(result['orphan_count'], orphan_count)

    def test_time_advances_even_when_values_and_repeat_label_are_unchanged(self):
        trips = [self.trip('a', 0, 300000, 72, 70),
                 self.trip('b', 3900000, 4200000, 70, 69)]
        samples = [self.sample(minute, 70) for minute in range(5, 66, 5)]
        for row in samples[1:]:
            row['record']['change'] = 'repeat'
        row = build_events(trips, [], samples, 0, 4500000, 86)['events'][0]
        self.assertEqual(row['sample_count'], 13)
        self.assertEqual(row['gap_count'], 0)
        self.assertEqual(row['status'], 'comparable')
        self.assertEqual(row['soc_drop'], 0)

    def test_gap_keeps_one_event_but_blocks_consumption(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 2400000, 3000000, 68, 67)]
        samples = [self.sample(5, 70), self.sample(6, 70), self.sample(35, 68), self.sample(40, 68)]
        result = build_events(trips, [], samples, 0, 3600000, 86)
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['status'], 'uncertain')
        self.assertIn('gap', result['events'][0]['reasons'])
        self.assertIsNone(result['events'][0]['soc_drop'])

    def test_long_stationary_interval_counts_as_parking_despite_time_quality(self):
        trips = [self.trip('a', 0, 300000, 82, 80),
                 self.trip('b', 17801000, 19000000, 79, 76)]
        samples = [self.sample(5, 80), self.sample(60, 79), self.sample(296, 79)]
        samples[1]['record']['flags'] = ['stale']
        result = build_events(trips, [], samples, 0, 20000000, 86)
        row = result['events'][0]
        self.assertEqual(row['parking_status'], 'parked')
        self.assertEqual(result['parking_count'], 1)
        self.assertEqual(row['duration_seconds'], 17501)
        self.assertEqual((row['start_soc'], row['end_soc']), (80, 79))
        self.assertIn('gap', row['reasons'])
        self.assertIn('invalid', row['reasons'])
        self.assertIsNone(row['estimated_kwh'])

    def test_movement_evidence_keeps_interval_a_candidate(self):
        trips = [self.trip('a', 0, 300000, 72, 70),
                 self.trip('b', 1200000, 1800000, 69, 68)]
        samples = [self.sample(5, 70), self.sample(20, 69, km=101)]
        samples[1]['location']['longitude'] = 121
        result = build_events(trips, [], samples, 0, 2400000, 86)
        self.assertEqual(result['events'], [])
        self.assertEqual(result['parking_count'], 0)

    def test_continuous_observation_can_calculate(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 69, 68)]
        samples = [self.sample(minute, 70 if minute < 15 else 69) for minute in (5, 10, 15, 20)]
        row = build_events(trips, [], samples, 0, 2400000, 86)['events'][0]
        self.assertEqual(row['status'], 'comparable')
        self.assertEqual(row['soc_drop'], 1)
        self.assertEqual(row['estimated_kwh'], .86)

    def test_charge_time_is_removed_from_parking(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 75, 74)]
        samples = [self.sample(minute, 70 if minute < 15 else 75)
                   for minute in (5, 6, 10, 15, 16, 20)]
        charge = {'kind': 'charge_end', 'start_time': 600000, 'end_time': 900000}
        rows = build_events(trips, [charge], samples, 0, 2400000, 86)['events']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['end_time'] <= 600000 or row['start_time'] >= 900000 for row in rows))
        self.assertEqual(sum(row['duration_seconds'] for row in rows), 600)

    def test_charge_history_with_unknown_start_excludes_through_charge_end(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 75, 74)]
        samples = [self.sample(minute, 75) for minute in (5, 10, 15, 20)]
        charge = {'kind': 'charge_end', 'start_time': None, 'end_time': 900000}
        rows = build_events(trips, [charge], samples, 0, 2400000, 86)['events']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['start_time'], 900000)

    def test_stationary_stop_inside_trip_is_never_parking(self):
        trips = [self.trip('a', 0, 1800000, 80, 78)]
        samples = [self.sample(minute, 80) for minute in (5, 10, 15, 20)]
        self.assertEqual(build_events(trips, [], samples, 0, 1800000)['events'], [])

    def test_same_gps_counts_without_power_off_speed_or_odometer(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 69, 68)]
        samples = [self.sample(minute, 70, off=False, km=None) for minute in (5, 10, 15, 20)]
        for row in samples:
            row['state']['speed'] = None
        result = build_events(trips, [], samples, 0, 2400000)
        self.assertEqual(result['parking_count'], 1)
        self.assertEqual(result['events'][0]['parking_status'], 'parked')

    def test_p_gear_supports_parking_but_never_overrides_trip_or_charge(self):
        trips = [self.trip('a', 0, 300000, 72, 70), self.trip('b', 1200000, 1800000, 69, 68)]
        samples = [self.sample(minute, 70) for minute in (1, 2, 5, 10, 15, 20)]
        for sample in samples:
            sample['state']['gear'] = 'P'
        result = build_events(trips, [], samples, 0, 1800000)
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['p_gear_samples'], 4)
        charge = {'start_time': 300000, 'end_time': 1200000}
        self.assertEqual(build_events(trips, [charge], samples, 0, 1800000)['events'], [])

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
            self.assertEqual(len(result['events']),0)


if __name__ == '__main__':
    unittest.main()
