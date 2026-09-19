import json
from pathlib import Path
import tempfile
import unittest

from zeekr_control.charging_analytics import ChargingAnalytics
from zeekr_control.monitor import Monitor


BASE = 1704067200000


def sample(at, soc, power, mode='ac', *, observed=None, charging=True, decoder='we86-v2-ac'):
    voltage = 220 if mode == 'ac' else 400
    current = power * 1000 / voltage if power is not None else None
    return {
        'schema_version': 2, 'decoder_version': decoder, 'state_time': at,
        'observed_at': at if observed is None else observed, 'soc': soc,
        'charging': charging, 'charging_mode': mode, 'power_kw': power,
        'power_source': 'ac_ui' if mode == 'ac' else 'dc_pile_ui',
        'ac_voltage': {'value': voltage if mode == 'ac' else None, 'validity': 'valid'},
        'ac_current': {'value': current if mode == 'ac' else None, 'validity': 'valid'},
        'voltage': {'value': voltage if mode == 'dc' else None, 'validity': 'valid'},
        'current': {'value': current if mode == 'dc' else None, 'validity': 'valid'},
        'secret': 'NEVER-PUBLIC',
    }


class ChargingAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'tracks.sqlite3'
        Monitor(self.path)
        self.analytics = ChargingAnalytics(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def insert_observations(self, vehicle, rows):
        with Monitor(self.path).tracks.connect() as db:
            for row in rows:
                db.execute('INSERT INTO report_observations VALUES (?,?,?,?,?)', (
                    vehicle, row['state_time'], row['observed_at'], json.dumps(row),
                    row['decoder_version']))

    def insert_event(self, event_id, vehicle, start, end, *, mode='ac', partial=False,
                     capacity=86, metrics=None):
        report = {'schema_version': 2, 'decoder_version': 'we86-v2-ac',
                  'kind': 'charge_end', 'start_time': start, 'end_time': end,
                  'partial': partial, 'start': {'soc': 20, 'charging_mode': mode},
                  'end': {'soc': 80, 'charging_mode': mode},
                  'metrics': metrics or {'duration_seconds': (end-start)/1000,
                                         'soc_delta': 60, 'estimated_kwh': 51.6}}
        summary = {'start_time': start, 'end_time': end,
                   'duration_seconds': (end-start)/1000, 'start_soc': 20,
                   'end_soc': 80, 'soc_delta': 60, 'partial': partial,
                   'battery_capacity_kwh': capacity, 'report_v2': report,
                   'private': 'NEVER-PUBLIC'}
        with Monitor(self.path).tracks.connect() as db:
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                       (event_id, vehicle, 'charge_end', json.dumps(summary), 'PRIVATE', end))

    def test_historical_session_and_series_are_vehicle_scoped_and_whitelisted(self):
        self.insert_event('event-a', 'car-a', BASE, BASE+600000)
        self.insert_event('event-b', 'car-b', BASE, BASE+600000)
        self.insert_observations('car-a', [
            sample(BASE, 20, 6.0), sample(BASE+60000, 21, 6.2),
            sample(BASE+400000, 30, 6.4), sample(BASE+460000, 31, 6.3),
        ])
        session = self.analytics.session('car-a', 'event-a')
        self.assertEqual(session['id'], 'event-a')
        self.assertEqual(session['mode'], 'ac')
        with self.assertRaises(ValueError):
            self.analytics.session('car-a', 'event-b')
        series = self.analytics.series('car-a', 'event-a', 'power-soc')
        self.assertEqual(series['raw_count'], 4)
        self.assertEqual(len(series['segments']), 2)
        self.assertTrue(series['has_gaps'])
        self.assertEqual(set(series['points'][0]), {'time', 'soc', 'power_kw', 'segment_id', 'quality'})
        self.assertNotIn('NEVER-PUBLIC', json.dumps(series))

    def test_current_session_uses_monitor_state_bounds(self):
        rows = [sample(BASE, 40, 6.0), sample(BASE+60000, 41, 6.1)]
        self.insert_observations('car-a', rows)
        state = {'charge': {'report_start': rows[0], 'samples': rows, 'partial': True}, 'last': {}}
        with Monitor(self.path).tracks.connect() as db:
            db.execute('INSERT OR REPLACE INTO monitor_state VALUES (?,?)', ('car-a', json.dumps(state)))
        result = self.analytics.session('car-a', 'current')
        self.assertEqual(result['status'], 'active')
        self.assertTrue(result['partial'])
        self.assertEqual(result['start_time'], BASE)
        self.assertEqual(self.analytics.series('car-a', 'current', 'electrical')['raw_count'], 2)

    def test_statistics_use_all_events_and_conservative_complete_totals(self):
        day = 86400000
        complete = {'duration_seconds': 3600, 'soc_delta': 60, 'estimated_kwh': 51.6,
                    'sampled_peak_kw': 6.5, 'average_power_kw': 6.2,
                    'power_sample_count': 10, 'power_covered_seconds': 3200,
                    'power_coverage': .89}
        self.insert_event('complete-ac', 'car-a', BASE, BASE+3600000, metrics=complete)
        self.insert_event('partial-dc', 'car-a', BASE+day, BASE+day+1800000,
                          mode='dc', partial=True, metrics={'duration_seconds': 1800,
                          'soc_delta': 60, 'estimated_kwh': 51.6, 'sampled_peak_kw': 80})
        self.insert_event('other-car', 'car-b', BASE, BASE+3600000, metrics=complete)
        result = self.analytics.statistics('car-a', 30, 'all', now=BASE+2*day)
        self.assertEqual(result['summary']['ended_count'], 2)
        self.assertEqual(result['summary']['complete_count'], 1)
        self.assertEqual(result['summary']['partial_count'], 1)
        self.assertEqual(result['summary']['estimated_kwh'], 51.6)
        self.assertEqual(result['summary']['included_energy_count'], 1)
        self.assertEqual(result['summary']['excluded_energy_count'], 1)
        self.assertEqual(result['summary']['complete_duration_seconds'], 3600)
        self.assertEqual(len(result['records']), 2)
        self.assertEqual(self.analytics.statistics('car-a', 30, 'ac', now=BASE+2*day)['summary']['ended_count'], 1)
        self.assertEqual(self.analytics.statistics('car-a', 30, 'dc', now=BASE+2*day)['summary']['ended_count'], 1)

    def test_invalid_inputs_and_empty_state(self):
        for bad in ('', '../secret', 'x'*129):
            with self.assertRaises(ValueError):
                self.analytics.session('car-a', bad)
        with self.assertRaises(ValueError):
            self.analytics.series('car-a', 'current', 'wrong')
        with self.assertRaises(ValueError):
            self.analytics.statistics('car-a', 8, 'all')
        self.assertEqual(self.analytics.statistics('car-a', 7, 'all')['summary']['ended_count'], 0)
        self.assertEqual(self.analytics.session('car-a', 'current')['status'], 'empty')

    def test_downsampling_keeps_peak_endpoints_and_gap_edges(self):
        rows = [sample(BASE+i*60000, 20+i//100, 99 if i == 777 else 6+i/1000)
                for i in range(1001)]
        rows[501]['state_time'] += 300000
        rows[501]['observed_at'] += 300000
        for index in range(502, len(rows)):
            rows[index]['state_time'] += 300000
            rows[index]['observed_at'] += 300000
        self.insert_event('long-event', 'car-a', rows[0]['state_time'], rows[-1]['state_time'])
        self.insert_observations('car-a', rows)
        result = self.analytics.series('car-a', 'long-event', 'power-soc')
        self.assertEqual(result['display_count'], 600)
        self.assertTrue(result['downsampled'])
        self.assertEqual(result['points'][0]['time'], rows[0]['state_time'])
        self.assertEqual(result['points'][-1]['time'], rows[-1]['state_time'])
        self.assertIn(99, [point['power_kw'] for point in result['points']])
        displayed_times = {point['time'] for point in result['points']}
        self.assertIn(rows[500]['state_time'], displayed_times)
        self.assertIn(rows[501]['state_time'], displayed_times)


if __name__ == '__main__':
    unittest.main()
