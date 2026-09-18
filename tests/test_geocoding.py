import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zeekr_control.storage import save


class GeocodingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'private' / 'amap-geocoding.json'
        save(self.config, {'api_key': 'synthetic-key'})
        self.location = {'valid': True, 'trusted': True, 'latitude': 31.0,
                         'longitude': 121.0, 'coordinate_system': 'WGS84（社区解释）'}

    def resolver(self):
        from zeekr_control.geocoding import AmapGeocoder
        return AmapGeocoder(self.config)

    def test_gps_is_converted_before_chinese_address_lookup(self):
        requests = []
        def request(path, params):
            requests.append((path, params))
            if path.endswith('/convert'):
                return {'status': '1', 'locations': '121.004,30.998'}
            self.assertEqual(params['location'], '121.004,30.998')
            return {'status': '1', 'regeocode': {'formatted_address': '上海市浦东新区测试路1号'}}
        resolver = self.resolver()
        with patch.object(resolver, '_request', side_effect=request):
            self.assertEqual(resolver(self.location), '上海市浦东新区测试路1号')
        self.assertEqual(requests[0][1]['coordsys'], 'gps')
        self.assertEqual(requests[0][1]['locations'], '121.000000,31.000000')

    def test_invalid_untrusted_unknown_system_and_missing_key_skip_network(self):
        resolver = self.resolver()
        with patch.object(resolver, '_request', side_effect=AssertionError('unexpected network')):
            for changes in ({'trusted': False}, {'valid': False}, {'coordinate_system': '未知'},
                            {'latitude': float('nan')}, {'longitude': 181}):
                self.assertIsNone(resolver(dict(self.location, **changes)))
            self.config.unlink()
            self.assertIsNone(resolver(self.location))

    def test_gcj_skips_conversion_and_failures_are_nonfatal(self):
        resolver = self.resolver()
        loc = dict(self.location, coordinate_system='GCJ-02（社区解释）')
        with patch.object(resolver, '_request', return_value={'status': '1', 'regeocode': {'formatted_address': '江苏省南京市测试路'}}) as request:
            self.assertEqual(resolver(loc), '江苏省南京市测试路')
            self.assertEqual(request.call_count, 1)
        for result in ({'status': '0'}, {'status': '1', 'regeocode': []},
                       {'status': '1', 'regeocode': {'formatted_address': []}}, []):
            with patch.object(resolver, '_request', return_value=result):
                self.assertIsNone(resolver(loc))
        with patch.object(resolver, '_request', side_effect=TimeoutError()):
            self.assertIsNone(resolver(loc))

    def test_address_is_single_line_and_bounded(self):
        resolver = self.resolver()
        with patch.object(resolver, '_request', return_value={'status': '1', 'regeocode': {'formatted_address': '江苏省\n南京市' + '路' * 200}}):
            result = resolver(dict(self.location, coordinate_system='GCJ-02（社区解释）'))
        self.assertNotIn('\n', result)
        self.assertLessEqual(len(result), 100)
