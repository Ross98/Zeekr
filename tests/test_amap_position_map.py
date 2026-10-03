import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from zeekr_control.storage import save
from zeekr_control.trip_map import AmapStaticMap

class AmapPositionMapTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  config=Path(self.temp.name)/'amap.json';save(config,{'api_key':'synthetic'})
  self.renderer=AmapStaticMap(config)
  self.location=dict(valid=True,trusted=False,latitude=31.2,longitude=121.4,coordinate_system='WGS84（社区解释）')
 def test_converts_gps_and_marks_candidate_without_changing_trust(self):
  calls=[]
  def request(path,params,binary=False):
   calls.append((path,params))
   return b'\x89PNG\r\n\x1a\nTEST' if binary else dict(status='1',locations='121.404,31.198')
  with patch.object(self.renderer,'_request',side_effect=request):
   self.assertTrue(self.renderer.position(self.location,15).startswith(b'\x89PNG'))
  self.assertEqual(calls[-1][1]['location'],'121.404000,31.198000')
  self.assertIn('0x7e898a',calls[-1][1]['markers']);self.assertFalse(self.location['trusted'])
 def test_invalid_points_zoom_or_response_do_not_draw_fake_map(self):
  with patch.object(self.renderer,'_request',return_value=b'error'):
   for location,zoom in [(dict(self.location,valid=False),15),(dict(self.location,coordinate_system='未知'),15),(self.location,99)]:
    with self.assertRaises(ValueError):self.renderer.position(location,zoom)
   with self.assertRaises(ValueError):self.renderer.position(dict(self.location,coordinate_system='GCJ-02（社区解释）'),15)

class LocationMapCacheTests(unittest.TestCase):
 def test_revision_guard_and_owner_zoom_cache(self):
  import threading
  from types import SimpleNamespace
  from unittest.mock import Mock
  from zeekr_control.web import App
  app=object.__new__(App);app.lock=threading.RLock();app.raw={};app.vehicle_key='car';app.location_maps={}
  app._read_session=Mock(return_value={'userId':'owner-one'});app._restore_snapshot=Mock()
  app.location_map_renderer=SimpleNamespace(position=Mock(return_value=b'\x89PNG\r\n\x1a\nTEST'))
  point=dict(valid=True,trusted=False,latitude=31.2,longitude=121.4,coordinate_system='GCJ-02（社区解释）',updated_at='cached')
  revision=app.location_map_revision(point)
  with patch('zeekr_control.web.parse_location',side_effect=lambda raw:dict(point)):
   with self.assertRaises(ValueError):app.location_map('15','old-revision')
   with self.assertRaises(ValueError):app.location_map('99',revision)
   app.location_map_renderer.position.assert_not_called()
   app.location_map('15',revision);app.location_map('15',revision)
   self.assertEqual(app.location_map_renderer.position.call_count,1)
   app.location_map('16',revision);self.assertEqual(app.location_map_renderer.position.call_count,2)
   app._read_session.return_value={'userId':'owner-two'}
   app.location_map('15',revision);self.assertEqual(app.location_map_renderer.position.call_count,3)
