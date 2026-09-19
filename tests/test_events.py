import json
import tempfile
from pathlib import Path
import unittest

from zeekr_control.monitor import Monitor


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tracks.sqlite3'
        self.monitor = Monitor(self.path)

    def add(self, event_id, vehicle, kind, end_time, created=None, **values):
        summary = {'start_time': end_time - 60000, 'end_time': end_time,
                   'duration_seconds': 60, 'partial': False, **values,
                   'start_location': {'latitude': 31}, 'end_address': 'SECRET'}
        with self.monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                       (event_id, vehicle, kind, json.dumps(summary), 'PRIVATE MESSAGE', created or end_time))

    def test_query_filters_vehicle_kind_and_beijing_end_date(self):
        from zeekr_control.events import EventStore
        # 2024-01-01 16:30 UTC = 2024-01-02 00:30 China time.
        self.add('a', 'vehicle-a', 'trip_end', 1704126600000, distance_km=12.3,
                 start_soc=80, end_soc=70, soc_delta=-10)
        self.add('b', 'vehicle-b', 'trip_end', 1704126600000, distance_km=99)
        self.add('c', 'vehicle-a', 'charge_end', 1704126600000)
        result = EventStore(self.path).query('vehicle-a', '2024-01-02', 'trip_end')
        self.assertEqual([item['id'] for item in result['events']], ['a'])
        self.assertEqual(result['events'][0]['distance_km'], 12.3)
        self.assertNotIn('location', str(result))
        self.assertNotIn('SECRET', str(result))
        self.assertNotIn('message', str(result))

    def test_cursor_paginates_stably(self):
        from zeekr_control.events import EventStore
        for index in range(3):
            self.add(str(index), 'vehicle-a', 'trip_end', 1704126600000 + index, created=10 + index)
        store = EventStore(self.path)
        first = store.query('vehicle-a', '2024-01-02', 'trip_end', limit=2)
        self.assertEqual([item['id'] for item in first['events']], ['2', '1'])
        second = store.query('vehicle-a', '2024-01-02', 'trip_end', cursor=first['next_cursor'], limit=2)
        self.assertEqual([item['id'] for item in second['events']], ['0'])

    def test_charge_details_projection_does_not_expose_private_report(self):
        from zeekr_control.events import EventStore
        self.add('charge', 'vehicle-a', 'charge_end', 1704126600000,
                 report_v2={'schema_version': 2, 'start': {'soc': 52, 'location': 'SECRET'},
                            'end': {'soc': 80}, 'metrics': {'sampled_peak_kw': 6.5},
                            'render': {'message': 'SECRET'}})
        result = EventStore(self.path).query('vehicle-a', '2024-01-02', 'charge_end')
        self.assertEqual(result['events'][0]['charging_details']['metrics']['sampled_peak_kw'], 6.5)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('report_v2', json.dumps(result))

    def test_latest_returns_each_completed_kind_for_one_vehicle(self):
        from zeekr_control.events import EventStore
        self.add('old-trip', 'vehicle-a', 'trip_end', 1000, created=1, distance_km=1)
        self.add('new-trip', 'vehicle-a', 'trip_end', 2000, created=2, distance_km=2)
        self.add('charge', 'vehicle-a', 'charge_end', 3000, created=3, start_soc=20, end_soc=80)
        self.add('other', 'vehicle-b', 'trip_end', 4000, created=4)
        result = EventStore(self.path).latest('vehicle-a')
        self.assertEqual(result['trip_end']['id'], 'new-trip')
        self.assertEqual(result['charge_end']['id'], 'charge')
        self.assertNotIn('location', str(result))
