import unittest
from zeekr_control.trip_place_names import current_location_name

class CurrentLocationNameTests(unittest.TestCase):
    def setUp(self):
        self.location=dict(valid=True,trusted=True,latitude=31.2,longitude=121.4,coordinate_system='WGS84（社区解释）')
    def test_manual_name_wins_and_distant_names_are_not_used(self):
        regions=[dict(id='manual',body=dict(name='公园',latitude=31.2,longitude=121.4,radius_m=150))]
        self.assertEqual(current_location_name(self.location,regions,{},{}),'公园附近')
        self.assertIsNone(current_location_name(dict(self.location,latitude=32),regions,{},{}))
    def test_untrusted_or_other_coordinate_system_has_no_name(self):
        cached={('a','end'):dict(label='道路附近',point=(31.2,121.4))}
        for update in [dict(trusted=False),dict(valid=False),dict(coordinate_system='GCJ-02（社区解释）')]:
            self.assertIsNone(current_location_name(dict(self.location,**update),[],{},cached))
        self.assertIsNone(current_location_name(self.location,[],{},cached))
    def test_manual_road_name_is_preserved_but_automatic_road_is_rejected(self):
        regions=[dict(id='manual',body=dict(name='测试路',latitude=31.2,longitude=121.4,radius_m=150))]
        cached={('a','end'):dict(label='测试路南0.2km附近',point=(31.2,121.4)),
                ('b','end'):dict(label='测试商场附近',point=(31.2001,121.4))}
        self.assertEqual(current_location_name(self.location,regions,{},cached),'测试路附近')
        self.assertEqual(current_location_name(self.location,[],{},cached),'测试商场附近')

    def test_commute_overlap_is_ambiguous_and_deleted_rule_ignored(self):
        point=dict(latitude=31.2,longitude=121.4,radius_m=300)
        self.assertEqual(current_location_name(self.location,[],dict(home=point),{}),'家附近')
        self.assertIsNone(current_location_name(self.location,[],dict(home=point,work=point),{}))
        self.assertIsNone(current_location_name(self.location,[],dict(home=point,deleted=True),{}))

class LandmarkEstimateTests(unittest.TestCase):
    def test_estimate_uses_nearest_landmark_without_changing_trust(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from zeekr_control.geocoding import AmapGeocoder
        from zeekr_control.storage import save
        with tempfile.TemporaryDirectory() as root:
            config=Path(root)/'amap-geocoding.json';save(config,dict(api_key='synthetic'))
            resolver=AmapGeocoder(config)
            location=dict(valid=True,trusted=False,latitude=31.2,longitude=121.4,coordinate_system='GCJ-02（社区解释）')
            response=dict(status='1',regeocode=dict(pois=[dict(name='测试公园',distance='120'),dict(name='远处车站',distance='900')]))
            with patch.object(resolver,'_request',return_value=response) as request:
                self.assertIsNone(resolver(location));request.assert_not_called()
                self.assertEqual(resolver(location,estimate=True),'测试公园')
                self.assertEqual(request.call_args.args[1]['extensions'],'all')
            self.assertFalse(location['trusted'])

class LocationApiCacheTests(unittest.TestCase):
    def test_estimates_are_cached_and_isolated_by_owner(self):
        import threading
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from zeekr_control.web import App
        app=object.__new__(App)
        app.lock=threading.RLock();app.raw={};app.read_at=0;app.vehicle_key='car'
        app._read_session=Mock(return_value=dict(userId='owner-one'))
        app._restore_snapshot=Mock();app.location_names={}
        app.location_geocoder=Mock(return_value='测试公园')
        app.trip_tags=SimpleNamespace(places=SimpleNamespace(tracks=SimpleNamespace(path=Mock(exists=Mock(return_value=False)))),
            place_names=SimpleNamespace(regions=Mock(return_value=[])),commute=SimpleNamespace(rule=Mock(return_value={})))
        location=dict(valid=True,trusted=False,latitude=31.2,longitude=121.4,coordinate_system='WGS84（社区解释）')
        with patch('zeekr_control.web.parse_location',side_effect=lambda raw:dict(location)):
            self.assertEqual(app.location()['approximate_name'],'测试公园附近')
            self.assertEqual(app.location()['approximate_name'],'测试公园附近')
            self.assertEqual(app.location_geocoder.call_count,1)
            app._read_session.return_value=dict(userId='owner-two')
            app.location();self.assertEqual(app.location_geocoder.call_count,2)
        self.assertFalse(location['trusted'])
