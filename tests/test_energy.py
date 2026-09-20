"""Trip attainment must use matching vehicle observations, never remaining range."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import importlib.util


class EnergyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('zeekr_control.energy'), 'Trip attainment is not implemented')
        from zeekr_control import energy
        self.energy = energy
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tracks.sqlite3'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE monitor_events (vehicle TEXT, kind TEXT, summary TEXT, created INTEGER)')
        self.profile = {'range_km': 546, 'range_standard': 'CLTC'}
        self.trip = dict(start_time=1704067200000, end_time=1704070800000,
                         distance_km=80, start_soc=80, end_soc=60, soc_delta=-20, partial=False)

    def add(self, trip=None, vehicle='car-a', kind='trip_end', created=1):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO monitor_events VALUES (?,?,?,?)',
                       (vehicle, kind, json.dumps(self.trip if trip is None else trip), created))

    def result(self, vehicle='car-a'):
        return self.energy.read_attainment(self.path, vehicle, self.profile)

    def test_actual_distance_and_consumed_soc(self):
        self.add()
        result = self.result()
        self.assertEqual(result['status'], 'available')
        self.assertAlmostEqual(result['ratio'], 73.26007326)
        self.assertAlmostEqual(result['reference_km'], 109.2)
        self.assertEqual(result['used_soc'], 20)
        self.assertEqual(result['distance_km'], 80)

    def test_ignores_other_vehicles_and_charge_summaries(self):
        self.add(vehicle='car-b', created=4)
        self.add(kind='charge_end', created=5)
        self.assertEqual(self.result()['status'], 'no_trip')
        self.add()
        self.assertEqual(self.result()['distance_km'], 80)
        self.assertEqual(self.result(None)['status'], 'no_trip')

    def test_latest_partial_trip_uses_its_own_observed_endpoints(self):
        self.add()
        self.add(dict(self.trip, partial=True, distance_km=40), created=2)
        self.assertEqual(self.result()['status'], 'available')
        self.assertTrue(self.result()['partial'])
        self.assertAlmostEqual(self.result()['ratio'], 36.63003663)

    def test_rejects_missing_invalid_and_charging_contaminated_data(self):
        cases = [dict(report_v2={'metrics':{'charge_overlap':True}}),
                 dict(report_v2={'quality':{'decoder_changed_mid_session':True}}), dict(soc_delta=None),
                 dict(start_soc=None), dict(end_soc=81, soc_delta=1),
                 dict(end_soc=80, soc_delta=0), dict(distance_km=-1),
                 dict(distance_km=None), dict(distance_km=True), dict(start_soc=101),
                 dict(soc_delta=-10), dict(end_time=1704067200000)]
        for index, changes in enumerate(cases):
            with self.subTest(changes=changes):
                self.add(dict(self.trip, **changes), created=index+1)
                self.assertNotEqual(self.result()['status'], 'available')
                self.assertIsNone(self.result().get('ratio'))

    def test_over_100_is_not_clamped(self):
        self.add(dict(self.trip, distance_km=120))
        self.assertAlmostEqual(self.result()['ratio'], 109.89010989)

    def test_missing_rating_and_missing_database(self):
        self.add()
        self.profile = {}
        self.assertEqual(self.result()['status'], 'no_rating')
        absent = self.path.parent / 'absent.sqlite3'
        self.assertEqual(self.energy.read_attainment(absent,'car-a',{})['status'], 'no_trip')
        self.assertFalse(absent.exists())

    def test_web_state_exposes_selected_trip_without_live_query(self):
        from zeekr_control.web import App
        self.add()
        app = App(self.path.parent / 'session.json', database_path=self.path)
        self.addCleanup(app.close)
        app.vehicle_key = 'car-a'
        app.profile = self.profile
        result = app.state().get('range_attainment', {})
        self.assertEqual(result.get('status'), 'available')
        self.assertAlmostEqual(result['ratio'], 73.26007326)
