"""Rated range must remain tied to a configured vehicle, never a global default."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from zeekr_control.profiles import vehicle_profile


class RatedRangeTests(unittest.TestCase):
    def test_invalid_unicode_field_does_not_poison_other_profile_values(self):
        for field in ('name','variant','image_alt','range_source'):
            for bad in ('\ud800','\udfff'):
                with self.subTest(field=field,bad=ascii(bad)):
                    value=dict(name='合成车辆🚗',battery_capacity_kwh=86,range_km=546,range_standard='CLTC')
                    value[field]=bad
                    result=self.profile(value)
                    json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8')
                    self.assertNotEqual(result.get(field),bad)
                    self.assertEqual(result['range_km'],546)
                    self.assertEqual(result['battery_capacity_kwh'],86)
                    if field!='name':self.assertEqual(result['name'],'合成车辆🚗')

    def test_invalid_storage_is_bounded_and_regular_profile_links_still_work(self):
        from zeekr_control.profiles import MAX_PROFILE_BYTES
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'profiles.json'
            for content in (b' '* (MAX_PROFILE_BYTES+1),b'\xff'):
                path.write_bytes(content)
                self.assertNotIn('range_km',vehicle_profile('car-a',1,1,path))
            path.unlink();path.mkdir()
            self.assertEqual(vehicle_profile('car-a',1,1,path)['name'],'车辆 1')
            path.rmdir()
            target=root/'valid.json'
            target.write_text(json.dumps({'single_vehicle':{'range_km':546,'range_standard':'CLTC'}}))
            path.symlink_to(target)
            self.assertEqual(vehicle_profile('car-a',1,1,path)['range_km'],546)

    def test_deep_profile_config_falls_back_without_stopping_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profiles.json'
            path.write_text('['*10000+'0'+']'*10000)
            profile=vehicle_profile('car-a',1,1,path)
            self.assertEqual(profile['name'],'车辆 1')
            self.assertNotIn('battery_capacity_kwh',profile)

    @unittest.skipUnless(hasattr(os,'mkfifo'),'requires FIFO support')
    def test_profile_pipe_does_not_wait_for_a_writer(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profiles.json';os.mkfifo(path,0o600)
            code=('import sys;from zeekr_control.profiles import vehicle_profile;'
                  'assert vehicle_profile("car-a",1,1,sys.argv[1])["name"]=="车辆 1"')
            result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,timeout=2)
            self.assertEqual(result.returncode,0,result.stderr)

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
