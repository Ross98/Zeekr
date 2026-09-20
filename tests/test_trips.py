"""Synthetic local trip queries; no vehicle or network access."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.monitor import Monitor
from zeekr_control.storage import save
from zeekr_control.web import App
import test_web_server as web_base


# Beijing midnight, 2024-01-02.
MIDNIGHT = 1704124800000


def sample(timestamp, trusted=True, latitude=111600000):
    return {'updateTime': timestamp, 'position': {'latitude': latitude,
            'longitude': 435600000, 'posCanBeTrusted': trusted, 'marsCoordinates': False}}


def point(timestamp, km=100, soc=70):
    return {'time': timestamp, 'observed': timestamp, 'km': km, 'soc': soc,
            'location': {'latitude': 31, 'longitude': 121}, 'private': 'PRIVATE'}


class TripFixtures:
    def event(self, identity='ended', vehicle='car-a', start=None, end=None, **changes):
        start = MIDNIGHT - 60000 if start is None else start
        end = MIDNIGHT + 60000 if end is None else end
        value = {'start_time': start, 'end_time': end, 'duration_seconds': 120,
                 'distance_km': 1.5, 'start_soc': 70, 'end_soc': 69, 'soc_delta': -1,
                 'partial': False, 'battery_capacity_kwh': 100,
                 'start_location': {'latitude': 31}, 'vin': 'PRIVATE', 'report_v2': {'raw': 'PRIVATE'}}
        value.update(changes)
        with self.monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                       (identity, vehicle, 'trip_end', json.dumps(value), 'PRIVATE', end))
        return value

    def active(self, stop=False, start=None, last=None, vehicle='car-a', **changes):
        start = MIDNIGHT - 60000 if start is None else start
        last = MIDNIGHT + 60000 if last is None else last
        trip = {'start': point(start), 'stop': point(last, 102, 69) if stop else None,
                'partial': True, 'profile': {'battery_capacity_kwh': 100},
                'samples': [{'secret': 'PRIVATE'}]}
        trip.update(changes)
        state = {'last': point(last + 120000 if stop else last, 102, 69), 'trip': trip}
        with self.monitor.tracks.connect() as db:
            db.execute('INSERT OR REPLACE INTO monitor_state VALUES (?,?)', (vehicle, json.dumps(state)))
        return state


class TripTests(TripFixtures, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private'
        self.root.mkdir(mode=0o700)
        self.app = App(self.root / 'session.json')
        self.addCleanup(self.app.close)
        self.monitor = Monitor(self.app.database_path)
        self.app.vehicle_key = 'car-a'

    def test_list_ended_by_end_date_and_whitelist(self):
        self.event()
        self.event('other', 'car-b')
        self.assertTrue(callable(getattr(self.app, 'trips', None)), 'read-only trip listing missing')
        result = self.app.trips('2024-01-02')
        self.assertEqual([x['id'] for x in result['events']], ['ended'])
        self.assertEqual(result['events'][0]['status'], 'ended')
        self.assertIsNone(result['active'])
        self.assertEqual(self.app.trips('2024-01-01')['events'], [])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('latitude', json.dumps(result))

    def test_active_and_waiting_keep_observed_bounds_and_overlap_date(self):
        self.active()
        self.assertTrue(callable(getattr(self.app, 'trips', None)), 'read-only trip listing missing')
        for date in ('2024-01-01', '2024-01-02'):
            active = self.app.trips(date)['active']
            self.assertEqual((active['id'], active['status']), ('current', 'driving'))
            self.assertEqual(active['end_time'], MIDNIGHT + 60000)
            self.assertEqual(active['duration_seconds'], 120)
            self.assertEqual(active['distance_km'], 2)
            self.assertEqual(active['soc_delta'], -1)
            self.assertNotIn('PRIVATE', json.dumps(active))
            self.assertNotIn('latitude', json.dumps(active))
        self.assertIsNone(self.app.trips('2024-01-03')['active'])
        self.active(stop=True)
        active = self.app.trips('2024-01-02')['active']
        self.assertEqual(active['status'], 'waiting')
        self.assertEqual(active['end_time'], MIDNIGHT + 60000)

    def test_single_trip_uses_full_cross_midnight_bounds_and_excludes_outside(self):
        self.event()
        for offset in (-60001, -60000, 0, 60000, 60001):
            self.monitor.tracks.record('car-a', sample(MIDNIGHT + offset), MIDNIGHT + offset, 180)
        self.assertIn('trip', __import__('inspect').signature(self.app.tracks).parameters,
                      'trip route selection missing')
        result = self.app.tracks('2024-01-02', trip='ended')
        self.assertEqual([p['state_time'] for p in result['observations']],
                         [MIDNIGHT - 60000, MIDNIGHT, MIDNIGHT + 60000])
        self.assertEqual(self.app.tracks('2024-01-02')['count'], 3)

    def test_selected_routes_reject_wrong_vehicle_unknown_empty_and_malformed_bounds(self):
        self.event('other', 'car-b')
        self.event('reverse', start=MIDNIGHT + 60000, end=MIDNIGHT)
        self.event('missing', start_time=None)
        self.event('boolean', start_time=True)
        self.assertIn('trip', __import__('inspect').signature(self.app.tracks).parameters,
                      'trip route selection missing')
        for identity in ('other', 'unknown', '', 'reverse', 'missing', 'boolean'):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                self.app.tracks('2024-01-02', trip=identity)
        with self.assertRaises(ValueError):
            self.app.tracks('2024-1-2', trip='unknown')

    def test_current_route_stops_at_waiting_snapshot(self):
        self.active(stop=True)
        for offset in (-60000, 0, 60000, 180000):
            self.monitor.tracks.record('car-a', sample(MIDNIGHT + offset), MIDNIGHT + offset, 180)
        self.assertIn('trip', __import__('inspect').signature(self.app.tracks).parameters,
                      'trip route selection missing')
        result = self.app.tracks('2024-01-02', trip='current')
        self.assertEqual(result['count'], 3)
        with self.assertRaises(ValueError):
            self.app.tracks('2024-01-03', trip='current')

    def test_single_archived_event_vehicle_can_be_read_offline_without_mutation(self):
        self.event()
        self.app.vehicle_key = None
        before = self.app.database_path.read_bytes()
        self.assertTrue(callable(getattr(self.app, 'trips', None)), 'read-only trip listing missing')
        with patch.object(self.app, 'client_factory', side_effect=AssertionError('no remote access')):
            self.assertEqual(self.app.trips('2024-01-02')['events'][0]['id'], 'ended')
            self.assertEqual(self.app.tracks('2024-01-02', trip='ended')['count'], 0)
        self.assertEqual(before, self.app.database_path.read_bytes())
        self.assertIsNone(self.app.vehicle_key)

    def test_ambiguous_archives_do_not_choose_first_and_binding_is_shared(self):
        for vehicle in ('car-a', 'car-b'):
            self.event(vehicle, vehicle)
            self.monitor.tracks.record(vehicle, sample(MIDNIGHT), MIDNIGHT, 180)
        self.app.vehicle_key = None
        with self.assertRaises(ValueError):
            self.app.tracks('2024-01-02')
        self.assertTrue(callable(getattr(self.app, 'trips', None)), 'read-only trip listing missing')
        with self.assertRaises(ValueError):
            self.app.trips('2024-01-02')
        save(self.root / 'monitor-binding.json', {'vehicle_key': 'car-b'})
        self.assertEqual(self.app.trips('2024-01-02')['events'][0]['id'], 'car-b')
        self.assertEqual(self.app.tracks('2024-01-02')['count'], 1)
        self.app.vehicle_key = 'car-a'
        with self.assertRaises(ValueError):
            self.app.tracks('2024-01-02', archive='car-b')

    def test_legacy_archive_cannot_choose_among_ambiguous_vehicles(self):
        for vehicle in ('car-a', 'car-b'):
            self.event(vehicle, vehicle)
        self.app.vehicle_key = None
        for vehicle in ('car-a', 'car-b'):
            with self.subTest(vehicle=vehicle), self.assertRaises(ValueError):
                self.app.tracks('2024-01-02', archive=vehicle)

    def test_legacy_archive_must_match_resolved_single_or_bound_vehicle(self):
        self.event('single', 'car-a')
        self.app.vehicle_key = None
        self.assertEqual(self.app.tracks('2024-01-02', archive='car-a')['count'], 0)
        with self.assertRaises(ValueError):
            self.app.tracks('2024-01-02', archive='car-b')
        self.event('other', 'car-b')
        save(self.root / 'monitor-binding.json', {'vehicle_key': 'car-a'})
        self.assertEqual(self.app.tracks('2024-01-02', archive='car-a')['count'], 0)
        with self.assertRaises(ValueError):
            self.app.tracks('2024-01-02', archive='car-b')

    def test_malformed_binding_is_value_error_without_archive_fallback(self):
        self.event()
        self.app.vehicle_key = None
        save(self.root / 'monitor-binding.json', {'vehicle_key': ['car-a']})
        with self.assertRaises(Exception) as caught:
            self.app.tracks('2024-01-02', archive='car-a')
        self.assertIsInstance(caught.exception, ValueError)

    def test_non_string_binding_value_never_becomes_vehicle_selection(self):
        self.event()
        self.app.vehicle_key = None
        for value in (['car-a'], [], 1, {}):
            with self.subTest(value=value), patch('zeekr_control.web.load', return_value={'vehicle_key': value}):
                with self.assertRaises(Exception) as caught:
                    self.app.trips('2024-01-02')
                self.assertIsInstance(caught.exception, ValueError)

    def test_missing_database_stays_missing_and_validates_date_cursor_selection(self):
        self.app.database_path.unlink()
        self.assertTrue(callable(getattr(self.app, 'trips', None)), 'read-only trip listing missing')
        self.assertEqual(self.app.trips('2024-01-02')['events'], [])
        self.assertEqual(self.app.tracks('2024-01-02')['quality']['gap_count'], 0)
        for date, cursor in [('bad', None), ('2024-1-2', None), ('2024-01-02', 'bad')]:
            with self.assertRaises(ValueError):
                self.app.trips(date, cursor=cursor)
        with self.assertRaises(ValueError):
            self.app.tracks('2024-01-02', trip='current')
        self.assertFalse(self.app.database_path.exists())

    def test_pagination_stays_current_vehicle(self):
        for index in range(22):
            self.event('event-%02d' % index, end=MIDNIGHT + 60000 + index)
        self.assertTrue(callable(getattr(self.app, 'trips', None)), 'read-only trip listing missing')
        first = self.app.trips('2024-01-02')
        second = self.app.trips('2024-01-02', cursor=first['next_cursor'])
        self.assertEqual(len(first['events']), 20)
        self.assertEqual(len(second['events']), 2)
        self.assertFalse({x['id'] for x in first['events']} & {x['id'] for x in second['events']})

    def test_malformed_active_state_is_not_projected_or_used_as_route_bounds(self):
        self.active()
        for payload in ('not json', '[]', '{"trip": {"start": {"time": true}}}'):
            with self.monitor.tracks.connect() as db:
                db.execute('UPDATE monitor_state SET payload=? WHERE vehicle=?', (payload, 'car-a'))
            self.assertIsNone(self.app.trips('2024-01-02')['active'])
            with self.assertRaises(ValueError):
                self.app.tracks('2024-01-02', trip='current')

    def test_summary_values_cannot_smuggle_nested_private_fields(self):
        self.event(distance_km={'latitude': 31, 'private': 'PRIVATE'}, start_soc='PRIVATE',
                   battery_capacity_kwh=float('nan'))
        data = self.app.trips('2024-01-02')
        self.assertIsNone(data['events'][0]['distance_km'])
        self.assertIsNone(data['events'][0]['start_soc'])
        self.assertIsNone(data['events'][0]['battery_capacity_kwh'])
        self.assertNotIn('PRIVATE', json.dumps(data))

    def test_tracks_only_database_can_serve_empty_trip_list_without_schema_write(self):
        with self.monitor.tracks.connect() as db:
            db.execute('DROP TABLE monitor_events')
            db.execute('DROP TABLE monitor_state')
        self.monitor.tracks.record('car-a', sample(MIDNIGHT), MIDNIGHT, 180)
        before = self.app.database_path.read_bytes()
        self.assertEqual(self.app.trips('2024-01-02')['events'], [])
        self.assertEqual(self.app.tracks('2024-01-02')['count'], 1)
        self.assertEqual(before, self.app.database_path.read_bytes())


class TripWebTests(TripFixtures, unittest.TestCase):
    cleanup = web_base.WebServerTests.cleanup
    request = web_base.WebServerTests.request
    post = web_base.WebServerTests.post

    def setUp(self):
        web_base.WebServerTests.setUp(self)
        self.monitor = Monitor(self.app.database_path)
        self.app.vehicle_key = 'car-a'

    def test_trip_http_projects_summaries_and_routes_only_on_explicit_request(self):
        self.event()
        self.active()
        self.monitor.tracks.record('car-a', sample(MIDNIGHT), MIDNIGHT, 180)
        with patch.object(self.app, 'client_factory', side_effect=AssertionError('no remote access')):
            code, data = self.request('GET', '/api/trips?date=2024-01-02')
            self.assertEqual(code, 200)
            self.assertEqual(data['events'][0]['id'], 'ended')
            self.assertNotIn('latitude', json.dumps(data))
            self.assertNotIn('PRIVATE', json.dumps(data))
            self.assertNotIn('latitude', json.dumps(self.request('GET', '/api/state')[1]))
            code, route = self.request('GET', '/api/tracks?date=2024-01-02&trip=ended')
            self.assertEqual(code, 200)
            self.assertEqual(route['count'], 1)
            self.assertIn('latitude', json.dumps(route))
        self.assertEqual(self.request('GET', '/api/tracks?date=2024-01-02&trip=')[0], 400)
        self.assertEqual(self.request('GET', '/api/trips?date=wrong')[0], 400)
