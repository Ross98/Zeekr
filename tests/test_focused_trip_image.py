import copy,json,math,struct,tempfile,unittest
from pathlib import Path
from zeekr_control.focused_trip_image import build_geometry,fit_geometry,render_focused_trip_png,FocusedTripImage

class FocusedTripTests(unittest.TestCase):
 def route(self):
  return {'count':5,'gaps':[{}],'segments':[[{'longitude':118+i*.001,'latitude':32+i*.004,'trusted':True,'coordinate_system':'WGS84（社区解释）'} for i in range(3)], [{'longitude':118.005,'latitude':32.025,'trusted':True,'coordinate_system':'WGS84（社区解释）'},{'longitude':118.008,'latitude':32.029,'trusted':True,'coordinate_system':'WGS84（社区解释）'}]]}
 def test_rotation_fits_all_points_and_preserves_spans(self):
  route=self.route();before=copy.deepcopy(route);g=build_geometry(route);f=fit_geometry(g['segments']);self.assertEqual(route,before);self.assertEqual(len(f['segments']),2)
  for x,y in sum(f['segments'],[]):self.assertTrue(48<=x<=908 and 48<=y<=472)
  original=fit_geometry(g['segments'],rotate=False);self.assertGreater(f['scale'],original['scale']);self.assertNotEqual(f['angle'],0)
 def test_uniform_scale_keeps_relative_distances(self):
  g=build_geometry(self.route());f=fit_geometry(g['segments']);a,b=g['segments'][0][:2];aa,bb=f['segments'][0][:2];self.assertAlmostEqual(math.dist(aa,bb),math.dist(a,b)*f['scale'],places=5)
 def test_untrusted_or_unknown_coordinate_fails_closed(self):
  for field,value in [('trusted',False),('coordinate_system','unknown'),('latitude',float('nan'))]:
   route=self.route();route['segments'][0][0][field]=value
   with self.assertRaises(ValueError):build_geometry(route)
 def test_missing_network_is_explicit_and_raw_track_retained(self):
  with tempfile.TemporaryDirectory() as folder:
   g=build_geometry(self.route(),Path(folder));self.assertEqual(g['roads'],[]);self.assertFalse(g['network_available']);self.assertEqual([len(s) for s in g['segments']],[3,2])
 def test_point_limit_and_empty_fail(self):
  for route in [{'segments':[]},{'segments':[[self.route()['segments'][0][0]]*1501]}]:
   with self.assertRaises(ValueError):build_geometry(route)
 def test_output_size_no_network_and_chinese_name(self):
  report={'start_time':1791195900000,'end_time':1791198990000,'start':{'soc':76},'end':{'soc':72},'metrics':{'distance_km':17,'duration_seconds':3090,'estimated_kwh_100km':20.2}}
  image=render_focused_trip_png(report,self.route(),build_geometry(self.route()),'测试起点');self.assertEqual(struct.unpack('>II',image[16:24]),(1068,886));self.assertLess(len(image),2*1024*1024)
 def test_worker_failures_do_not_return_old_map_or_send(self):
  with tempfile.TemporaryDirectory() as folder:
   with self.assertRaises(ValueError):FocusedTripImage(Path(folder)).render_trip({}, {'segments':[]},None)
 def test_glyph_name_cap_and_metric_overflow(self):
  g=build_geometry(self.route());image=render_focused_trip_png({'metrics':{'distance_km':1000000}},self.route(),g,'测试'*100);self.assertLess(len(image),2*1024*1024)

 def test_fixed_copy_glyphs_exist(self):
  from zeekr_control.focused_trip_image import _atlas
  index,_=_atlas()
  for size,text in [(21,'行程里程观测时长电量估算能耗月日:'),(42,'0123456789.→—'),(18,'测试起点…'),(17,'kWh/100km')]:
   for char in text:self.assertIn(str(size)+':'+char,index)
 def test_background_reads_real_roads_without_label_data(self):
  from zeekr_control.road_network import build_network
  with tempfile.TemporaryDirectory() as folder:
   build_network({'elements':[{'type':'node','id':1,'lon':118.,'lat':32.},{'type':'node','id':2,'lon':118.001,'lat':32.004},{'type':'way','id':3,'nodes':[1,2],'tags':{'highway':'primary','name':'背景禁止出现此名称'}}]},Path(folder)/'region.sqlite3')
   g=build_geometry(self.route(),Path(folder));self.assertTrue(g['network_available']);self.assertEqual(len(g['roads']),1);self.assertNotIn('背景禁止出现此名称',json.dumps(g,ensure_ascii=False))

 def test_isolated_trusted_point_kept_without_bridging_gap(self):
  route=self.route();route['segments'].insert(1,[dict(route['segments'][0][-1])]);before=copy.deepcopy(route)
  g=build_geometry(route);self.assertEqual([len(s) for s in g['segments']],[3,1,2]);self.assertEqual(route,before)
  png=render_focused_trip_png({'metrics':{}},route,g,None);self.assertTrue(png.startswith(b'\x89PNG'))
