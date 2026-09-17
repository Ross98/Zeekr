"""Rated range must remain tied to a configured vehicle, never a global default."""
import json
import tempfile
import unittest
from pathlib import Path
from zeekr_control.profiles import vehicle_profile


class RatedRangeTests(unittest.TestCase):
    def profile(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            path.write_text(json.dumps({'vehicles': {'car-a': value}}))
            return vehicle_profile('car-a', 1, 2, path)

    def test_configured_vehicle_exposes_rated_range(self):
        result = self.profile({'range_km': 546, 'range_standard': 'CLTC', 'range_source': '车型配置资料'})
        self.assertEqual(result.get('range_km'), 546)
        self.assertEqual(result.get('range_standard'), 'CLTC')

    def test_invalid_or_incomplete_rating_stays_unknown(self):
        for value in [None, True, 0, -1, float('inf'), float('nan'), '546', 10**400]:
            with self.subTest(value=value):
                self.assertIsNone(self.profile({'range_km': value, 'range_standard': 'CLTC'}).get('range_km'))
        self.assertIsNone(self.profile({'range_km': 546}).get('range_km'))
        self.assertIsNone(self.profile({}).get('range_km'))

    def test_rating_does_not_leak_to_other_vehicles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profiles.json'
            path.write_text(json.dumps({'single_vehicle': {'range_km': 546, 'range_standard': 'CLTC'},
                                        'vehicles': {'car-a': {'range_km': 741, 'range_standard': 'CLTC'}}}))
            self.assertEqual(vehicle_profile('car-a', 1, 2, path)['range_km'], 741)
            self.assertIsNone(vehicle_profile('car-b', 2, 2, path).get('range_km'))
