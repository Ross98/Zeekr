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
            self.assertEqual(params['extensions'], 'all')
            self.assertEqual(params['radius'], 300)
            return {'status': '1', 'regeocode': {'formatted_address': '上海市浦东新区测试路1号', 'pois': [{'name': '测试商场', 'distance': '80', 'type': '购物服务;商场'}]}}
        resolver = self.resolver()
        with patch.object(resolver, '_request', side_effect=request):
            self.assertEqual(resolver(self.location), '测试商场')
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
            self.assertIsNone(resolver(loc))
            self.assertEqual(request.call_count, 1)
        for result in ({'status': '0'}, {'status': '1', 'regeocode': []},
                       {'status': '1', 'regeocode': {'formatted_address': []}}, []):
            with patch.object(resolver, '_request', return_value=result):
                self.assertIsNone(resolver(loc))
        with patch.object(resolver, '_request', side_effect=TimeoutError()):
            self.assertIsNone(resolver(loc))

    def test_address_is_single_line_and_bounded(self):
        resolver = self.resolver()
        with patch.object(resolver, '_request', return_value={'status': '1', 'regeocode': {'addressComponent': {'building': {'name': '测试\n' + '大' * 200 + '厦'}}}}):
            result = resolver(dict(self.location, coordinate_system='GCJ-02（社区解释）'))
        self.assertNotIn('\n', result)
        self.assertLessEqual(len(result), 100)

    def test_structured_address_prefers_neighborhood_without_unit_details(self):
        resolver = self.resolver()
        result = {'status': '1', 'regeocode': {
            'formatted_address': '上海市浦东新区测试路123号测试园区2号楼301室',
            'addressComponent': {'province': '上海市', 'city': [], 'district': '浦东新区',
                'neighborhood': {'name': '测试园区2号楼301室'},
                'building': {'name': '测试大厦'},
                'streetNumber': {'street': '测试路', 'number': '123号'}}}}
        with patch.object(resolver, '_request', return_value=result):
            self.assertEqual(resolver(dict(self.location, coordinate_system='GCJ-02（社区解释）')),
                             '测试园区')

    def test_structured_address_uses_building_but_rejects_road_and_district(self):
        resolver = self.resolver()
        for component, expected in (
            ({'district': '浦东新区', 'building': {'name': '测试大厦3栋'}}, '测试大厦'),
            ({'district': '浦东新区', 'neighborhood': {'name': []}, 'building': [],
              'streetNumber': {'street': '测试路', 'number': '123号'}}, None),
            ({'district': '浦东新区'}, None),
            ({'district': [], 'streetNumber': {'street': '测试路'}}, None)):
            with self.subTest(component=component), patch.object(resolver, '_request', return_value={
                    'status': '1', 'regeocode': {'addressComponent': component}}):
                self.assertEqual(resolver(dict(self.location, coordinate_system='GCJ-02（社区解释）')), expected)

    def test_formatted_only_address_removes_province_city_house_number_and_unit(self):
        resolver = self.resolver()
        for address, expected in (
            ('上海市浦东新区测试路123号2号楼301室', None),
            ('江苏省南京市江宁区测试小区2栋1单元', '测试小区'),
            ('北京市海淀区中关村北二条3号', None)):
            with self.subTest(address=address), patch.object(resolver, '_request', return_value={
                    'status': '1', 'regeocode': {'formatted_address': address}}):
                self.assertEqual(resolver(dict(self.location, coordinate_system='GCJ-02（社区解释）')), expected)

    def test_named_places_with_number_in_name_are_not_mistaken_for_house_numbers(self):
        resolver = self.resolver()
        for regeocode, expected in (
            ({'addressComponent': {'district': '浦东新区', 'neighborhood': {'name': '一号公馆2栋'}}},
             '一号公馆'),
            ({'formatted_address': '江苏省南京市江宁区三号桥路123号'}, None)):
            with self.subTest(expected=expected), patch.object(resolver, '_request', return_value={
                    'status': '1', 'regeocode': regeocode}):
                self.assertEqual(resolver(dict(self.location, coordinate_system='GCJ-02（社区解释）')), expected)
