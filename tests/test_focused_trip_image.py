import copy,json,math,struct,tempfile,unittest,subprocess,signal
from unittest.mock import patch
from pathlib import Path
from zeekr_control.focused_trip_image import build_geometry,fit_geometry,render_focused_trip_png,FocusedTripImage

class FocusedTripTests(unittest.TestCase):
 def test_image_endpoint_captions_preserve_provenance_without_false_map_pins(self):
  from zeekr_control.focused_trip_image import Surface
  report={'partial':True,'metrics':{},'image_places':{
   'start':{'name':'测试家园','reference':{'source':'commute_rule'}},
   'end':{'name':'测试公司','reference':{'source':'saved_place','position_source':'historical'}}}}
  calls=[];original=Surface.text
  def capture(surface,x,y,text,*args,**kwargs):
   calls.append((x,y,str(text)));return original(surface,x,y,text,*args,**kwargs)
  with patch.object(Surface,'text',capture):render_focused_trip_png(report,self.route(),build_geometry(self.route()))
  text=[r[2] for r in calls]
  self.assertTrue(any('测试家园' in t and '通勤推定' in t and '非精确定位' in t for t in text))
  self.assertTrue(any('测试公司' in t and '参考定位' in t for t in text))
  self.assertNotIn('起点名称未记录',text)
  self.assertFalse(any(y>=114 and ('测试家园' in t or '测试公司' in t) for x,y,t in calls))

 def test_long_endpoint_names_fit_without_truncating_qualifier(self):
  from zeekr_control.focused_trip_image import Surface,place_caption
  surface=Surface(1068,886,(0,0,0))
  value=place_caption(surface,'起点',{'name':'测试地点'*40,'reference':{'source':'commute_rule'}},460)
  self.assertLessEqual(surface.text_width(value,18),460)
  self.assertIn('通勤推定',value);self.assertIn('非精确定位',value)

 def test_decimal_and_colon_share_numeric_baseline(self):
  from zeekr_control.focused_trip_image import _atlas
  index,masks=_atlas()
  for size in (17,21,35,42):
   def rows(char):
    offset,w,h,_=index[str(size)+':'+char]
    return [y for y in range(h) if any(masks[offset+y*w:offset+(y+1)*w])]
   digit,dot=rows('8'),rows('.')
   self.assertGreater(min(dot), (min(digit)+max(digit))/2)
   self.assertLessEqual(abs(max(dot)-max(digit)),2)

 def test_background_budget_is_shared_across_map_cells_and_networks(self):
  import sqlite3
  with tempfile.TemporaryDirectory() as folder:
   self.corner_network(folder)
   p=Path(folder)/'region.sqlite3'
   with sqlite3.connect(p) as db:
    coords=db.execute('SELECT coords FROM roads LIMIT 1').fetchone()[0]
    bounds=db.execute('SELECT minx,maxx,miny,maxy FROM road_index LIMIT 1').fetchone()
    for i in range(2,10004):
     db.execute('INSERT INTO roads VALUES (?,?,?,?,?,?,?)',(i,i*10,i*10+1,0,'',100,coords))
     db.execute('INSERT INTO road_index VALUES (?,?,?,?,?)',(i,)+bounds)
   from zeekr_control.road_network import build_network
   build_network({'elements':[{'type':'node','id':900001,'lon':121.1,'lat':31.1},
     {'type':'node','id':900002,'lon':121.101,'lat':31.101},
     {'type':'way','id':900003,'nodes':[900001,900002],'tags':{'highway':'primary'}}]},Path(folder)/'z-region.sqlite3')
   route=self.corner_route();route['segments'][0].append(dict(route['segments'][0][-1],longitude=121.101,latitude=31.101))
   geometry=build_geometry(route,folder)
   self.assertTrue(geometry['background_limited'])
   self.assertLessEqual(len(geometry['roads']),10000)
   self.assertLessEqual(sum(map(len,geometry['roads'])),60000)
   self.assertTrue(any(road[-1][0]>geometry['segments'][0][-1][0]-1 for road in geometry['roads']))

 def test_partial_matching_and_limited_background_are_explicit(self):
  from zeekr_control.focused_trip_image import Surface
  route=self.route();geometry=build_geometry(route)
  geometry.update(matched=[geometry['segments'][0]],fallback=[geometry['segments'][1]],background_limited=True)
  text=[];original=Surface.text
  def capture(surface,x,y,value,*args,**kwargs):
   text.append(str(value));return original(surface,x,y,value,*args,**kwargs)
  with patch.object(Surface,'text',capture):render_focused_trip_png({'metrics':{}},route,geometry)
  self.assertIn('底图已简化',text)
  self.assertIn('实线：路网推断',text)
  self.assertIn('虚线：采样连线',text)

 def corner_route(self):
  points=[dict(state_time=1704067200000+i*60000,observed_time=1704067200000+i*60000,
               longitude=lon,latitude=lat,trusted=True,plottable=True,
               coordinate_system='WGS84（社区解释）')
          for i,(lon,lat) in enumerate([(121.0002,31),(121.001,31.0008)])]
  return dict(observations=points,segments=[points],count=2,gaps=[])
 def corner_network(self,folder):
  from zeekr_control.road_network import build_network
  build_network({'elements':[{'type':'node','id':1,'lon':121,'lat':31},
    {'type':'node','id':2,'lon':121.001,'lat':31},
    {'type':'node','id':3,'lon':121.001,'lat':31.001},
    {'type':'way','id':1,'nodes':[1,2,3],'tags':{'highway':'residential','oneway':'yes'}}]},Path(folder)/'region.sqlite3')
 def test_image_uses_road_corner_instead_of_cutting_across_it(self):
  with tempfile.TemporaryDirectory() as folder:
   self.corner_network(folder);route=self.corner_route();before=copy.deepcopy(route)
   geometry=build_geometry(route,folder)
   self.assertEqual(route,before);self.assertEqual(geometry['matching_status'],'matched')
   self.assertEqual(geometry['fallback'],[])
   self.assertTrue(any(len(line)>=3 for line in geometry['matched']))
   for a,b in zip(geometry['segments'][0][0],geometry['matched'][0][0]):self.assertAlmostEqual(a,b)
   for a,b in zip(geometry['segments'][0][-1],geometry['matched'][-1][-1]):self.assertAlmostEqual(a,b)
 def test_image_matching_never_bridges_source_segments(self):
  with tempfile.TemporaryDirectory() as folder:
   self.corner_network(folder);route=self.corner_route()
   first,last=route['observations'];middle=dict(first,longitude=121.0004,state_time=first['state_time']+10000)
   other=dict(last,latitude=31.0006,state_time=last['state_time']-10000)
   route['observations']=[first,middle,other,last];route['segments']=[[first,middle],[other,last]]
   geometry=build_geometry(route,folder)
   self.assertEqual(geometry['fallback'],[])
   self.assertEqual(len(geometry['matched']),2)
   self.assertTrue(all(len(s)==2 for s in geometry['matched']))
 def test_image_unconnected_oneway_retains_raw_fallback(self):
  with tempfile.TemporaryDirectory() as folder:
   self.corner_network(folder);route=self.corner_route();route['observations'].reverse()
   for i,p in enumerate(route['observations']):p['state_time']=1704067200000+i*60000
   geometry=build_geometry(route,folder)
   self.assertEqual(geometry['matched'],[])
   self.assertEqual(geometry['fallback'],geometry['segments'])
 def test_image_partial_matching_keeps_unmatched_endpoints_and_gap(self):
  with tempfile.TemporaryDirectory() as folder:
   self.corner_network(folder);route=self.corner_route()
   first,last=route['observations'];outside=dict(first,longitude=121.01,latitude=31.01,state_time=first['state_time']-60000)
   isolated=dict(last,state_time=last['state_time']+60000)
   route['observations']=[outside,first,last,isolated];route['segments']=[[outside,first,last],[isolated]]
   before=copy.deepcopy(route);geometry=build_geometry(route,folder)
   self.assertEqual(route,before);self.assertEqual(geometry['matching_status'],'partial')
   self.assertEqual(geometry['fallback'],[geometry['segments'][0][:2]])
   self.assertEqual([len(s) for s in geometry['segments']],[3,1])
 def test_image_missing_network_keeps_every_raw_edge(self):
  with tempfile.TemporaryDirectory() as folder:
   geometry=build_geometry(self.corner_route(),folder)
   self.assertEqual(geometry['matched'],[]);self.assertEqual(geometry['fallback'],geometry['segments'])
   self.assertEqual(geometry['matching_status'],'unavailable')
 def test_worker_wall_budget_handles_monitor_cpu_throttling(self):
  with patch('zeekr_control.focused_trip_image.subprocess.run') as run:
   run.return_value=subprocess.CompletedProcess([],0,b'\x89PNG\r\n\x1a\n',b'')
   FocusedTripImage('/tmp/synthetic-roads').render_trip({},self.route())
   self.assertEqual(run.call_args.kwargs['timeout'],45)
 def test_worker_failure_reasons_are_safe_and_retryable_when_transient(self):
  from zeekr_control.focused_trip_image import ImagePreparationError
  cases=[(subprocess.TimeoutExpired('worker',45),'行程图片超时',True),
         (subprocess.CompletedProcess([],1,b'',b'memory'),'行程图片内存不足',True),
         (subprocess.CompletedProcess([],1,b'',b'route'),'行程图片轨迹或输入无效',False),
         (subprocess.CompletedProcess([],-signal.SIGXCPU,b'',b''),'行程图片CPU时间超限',True),
         (subprocess.CompletedProcess([],-9,b'',b'private-secret'),'行程图片工作进程中断',True)]
  for result,message,retryable in cases:
   with self.subTest(message=message),patch('zeekr_control.focused_trip_image.subprocess.run') as run:
    if isinstance(result,Exception):run.side_effect=result
    else:run.return_value=result
    with self.assertRaises(ImagePreparationError) as caught:FocusedTripImage('/tmp/synthetic-roads').render_trip({},self.route())
    self.assertEqual(str(caught.exception),message);self.assertEqual(caught.exception.retryable,retryable)
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
  for size,text in [(21,'行程里程观测时长电量估算能耗月日:'),(42,'0123456789.→—'),(18,'测试起点…'),(17,'kWh/100km实线：路网推断虚线：采样连线部分匹配未'),(13,'底图已简化')]:
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


class SurfaceRasterTests(unittest.TestCase):
 def test_circle_matches_legacy_pixels_at_edges_and_fractional_centres(self):
  from zeekr_control.focused_trip_image import Surface
  def legacy(surface,x,y,r,color):
   for yy in range(max(0,int(y-r-1)),min(surface.height,int(y+r+2))):
    half=math.sqrt(max(0,(r+.5)**2-(yy-y)**2))
    for xx in range(max(0,int(x-half-1)),min(surface.width,int(x+half+2))):
     alpha=max(0,min(1,r+.5-math.hypot(xx-x,yy-y)))
     if alpha:surface.blend(xx,yy,color,alpha)
  old=Surface(40,30,(123,72,19));new=Surface(40,30,(123,72,19))
  for x,y in ((0,0),(-2.4,15),(39.9,29.9),(15.25,16.75),(20,15)):
   for radius in (.1,.5,1,1.5,2,2.5,4.5,11,14):
    legacy(old,x,y,radius,(0,102,80));new.circle(x,y,radius,(0,102,80))
    self.assertEqual(new.data,old.data)
