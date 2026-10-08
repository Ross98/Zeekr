import unittest

from zeekr_control.place_regions import RegionIndex, contains, overlaps, validate_polygon
from zeekr_control.trip_places import cluster_endpoints
from zeekr_control.trip_place_names import current_location_name
from tests import test_trip_place_names as fixtures


POLYGON = [[31.199, 121.399], [31.199, 121.405], [31.205, 121.405], [31.205, 121.402], [31.201, 121.402], [31.201, 121.399]]


def body(vertices=POLYGON, name='园区'):
    return dict(name=name, shape='polygon', vertices=vertices, latitude=vertices[0][0], longitude=vertices[0][1])


class RegionGeometryTests(unittest.TestCase):
    def test_concave_polygon_includes_edges_not_bounding_box(self):
        region=body()
        self.assertTrue(contains(region, (31.200,121.400)))
        self.assertTrue(contains(region, (31.204,121.403)))
        self.assertTrue(contains(region, (31.201,121.400)))
        self.assertFalse(contains(region, (31.204,121.400)))
        self.assertFalse(contains(region, (31.198,121.400)))

    def test_antimeridian_polygon_and_boundary(self):
        region=body([[1,179.999],[1,-179.999],[1.002,-179.999],[1.002,179.999]])
        validate_polygon(region['vertices'])
        self.assertTrue(contains(region,(1.001,180)))
        self.assertTrue(contains(region,(1.001,-179.999)))
        self.assertFalse(contains(region,(1.001,179.998)))

    def test_invalid_shapes_rejected(self):
        invalid = [[], [[31,121],[31,122]], [[31,121],[31,121],[32,122]],
                   [[31,121],[32,122],[31,122],[32,121]],
                   [[31,121],[31,122],[31,123]],
                   [[float('nan'),121],[31,122],[32,121]],
                   [[True,121],[31,122],[32,121]], POLYGON*20]
        for polygon in invalid:
            with self.subTest(polygon=polygon), self.assertRaises(ValueError):
                validate_polygon(polygon)

    def test_polygon_and_circle_conflicts_include_crossing_edges(self):
        self.assertTrue(overlaps(body(), body([[31.2,121.4],[31.2,121.406],[31.202,121.406],[31.202,121.4]])))
        self.assertFalse(overlaps(body(), body([[32,122],[32,123],[33,123],[33,122]])))
        self.assertTrue(overlaps(body(), dict(latitude=31.2011,longitude=121.400,radius_m=25)))
        self.assertFalse(overlaps(body(), dict(latitude=31.204,longitude=121.400,radius_m=25)))

    def test_large_named_polygon_is_one_group_with_shared_arrivals_departures(self):
        region=dict(id='region',body=body())
        rows=[dict(event_id='a',side='start',time=1,point=(31.200,121.400)),
              dict(event_id='b',side='end',time=2,point=(31.204,121.403))]
        result=cluster_endpoints(rows,[region])
        self.assertEqual(len(result['places']),1)
        self.assertEqual(result['places'][0]['name_region_id'],'region')
        self.assertEqual((result['places'][0]['departures'],result['places'][0]['arrivals']),(1,1))

    def test_polygon_claims_whole_circle_when_circle_centre_is_inside(self):
        regions=[dict(id='circle',body=dict(name='旧圆形',latitude=31.2,longitude=121.4,radius_m=150)),
                 dict(id='polygon',body=body())]
        index=RegionIndex(regions)
        self.assertEqual(index.pick((31.2,121.4))['id'],'polygon')
        self.assertEqual(index.pick((31.1989,121.4))['id'],'polygon')
        rows=[dict(event_id='a',side='start',time=1,point=(31.2,121.4)),
              dict(event_id='a',side='end',time=2,point=(31.1989,121.4))]
        result=cluster_endpoints(rows,regions)
        self.assertEqual([p['name_region_id'] for p in result['places']],['polygon'])
        self.assertEqual((result['places'][0]['departures'],result['places'][0]['arrivals']),(1,1))
        location=dict(valid=True,trusted=True,latitude=31.2,longitude=121.4,coordinate_system='WGS84（社区解释）')
        self.assertEqual(current_location_name(location,regions,{},{}),'园区附近')

    def test_circle_edge_overlap_does_not_claim_circle_with_centre_outside(self):
        regions=[dict(id='circle',body=dict(name='边界外圆形',latitude=31.1989,longitude=121.4,radius_m=50)),
                 dict(id='polygon',body=body())]
        point=(31.1991,121.4)
        self.assertTrue(contains(body(),point))
        self.assertEqual(RegionIndex(regions).pick(point)['id'],'circle')
        result=cluster_endpoints([dict(event_id='a',side='start',time=1,point=point)],regions)
        self.assertEqual(result['places'][0]['name_region_id'],'circle')

    def test_unnamed_fixed_circle_uses_anchor_not_each_observation(self):
        region=dict(id='polygon',body=body())
        for first,second,expected in [(31.1989,31.1991,None),(31.1991,31.1989,'polygon')]:
            with self.subTest(anchor=first):
                rows=[dict(event_id='a',side='start',time=1,point=(first,121.4)),
                      dict(event_id='b',side='end',time=2,point=(second,121.4))]
                result=cluster_endpoints(rows,[region])
                self.assertEqual(len(result['places']),1)
                self.assertEqual(result['places'][0]['name_region_id'],expected)

    def test_current_location_accepts_legacy_region_without_id(self):
        location=dict(valid=True,trusted=True,latitude=31.200,longitude=121.400,coordinate_system='WGS84（社区解释）')
        regions=[dict(body=dict(name='旧地点',latitude=31.200,longitude=121.400,radius_m=150))]
        self.assertEqual(current_location_name(location,regions,{},{}),'旧地点附近')

    def test_ambiguous_polygon_does_not_silently_choose_name(self):
        regions=[dict(id='a',body=body()),dict(id='b',body=body(name='其他地点'))]
        location=dict(valid=True,trusted=True,latitude=31.200,longitude=121.400,coordinate_system='WGS84（社区解释）')
        self.assertIsNone(current_location_name(location,regions,dict(deleted=True),{}))


class RegionNamingTests(unittest.TestCase):
    setUp=fixtures.TripPlaceNameTests.setUp
    trip=fixtures.TripPlaceNameTests.trip
    places=fixtures.TripPlaceNameTests.places
    rename=fixtures.TripPlaceNameTests.rename

    def payload(self, **extra):
        p=self.places()['places'][0]
        return dict(action='place-name-preview',date='2026-09-28',place_id=p['id'],place_key=p['name_key'],name='园区',shape='polygon',vertices=POLYGON,revision=0,**extra)

    def save_polygon(self):
        payload=self.payload()
        preview=self.tags.update('owner','car',payload)
        self.tags.update('owner','car',dict(payload,action='place-name-save',preview_token=preview['preview_token']))
        return preview

    def test_save_polygon_names_future_month_and_preserves_source(self):
        before=self.db.read_bytes()
        self.save_polygon()
        self.assertEqual(before,self.db.read_bytes())
        self.trip('next',self.start+4*86400000,(31.204,121.403),(31.21,121.41))
        place=self.places(date='2026-10-01')['places'][0]
        self.assertEqual(place['label'],'园区')
        self.assertEqual(place['name_shape'],'polygon')
        self.assertNotEqual(self.places('other',date='2026-10-01')['places'][0]['label'],'园区')

    def test_daily_and_current_location_share_polygon_names(self):
        from zeekr_control.daily_timeline import DailyTimeline
        self.save_polygon()
        self.trip('far',self.start+3600000,(31.204,121.403),(31.21,121.41))
        class Archive:
            def iter_records(self,*args):return iter(())
        timeline=DailyTimeline(self.db,Archive(),self.tags.store)
        records=timeline.query('scope','car','2026-09-28',owner='owner')['records']
        far=next(r for r in records if r['id']=='far')
        self.assertEqual(far['start_place']['label'],'园区')
        location=dict(valid=True,trusted=True,latitude=31.204,longitude=121.403,coordinate_system='WGS84（社区解释）')
        self.assertEqual(current_location_name(location,self.tags.place_names.regions('owner','car'),{},{}),'园区附近')
        parked=timeline._parking_place(location,[],self.tags.place_names.regions('owner','car'))
        self.assertEqual(parked['label'],'园区')

    def test_edit_preserves_region_identity_and_preview_accounts_for_old_area(self):
        self.save_polygon()
        region=self.places()['name_regions'][0]
        vertices=[[31.203,121.4025],[31.203,121.404],[31.205,121.404],[31.205,121.4025]]
        payload=dict(action='place-name-preview',date='2026-09-28',region_id=region['id'],
                     name='园区新范围',shape='polygon',vertices=vertices,revision=1)
        preview=self.tags.update('owner','car',payload)
        self.assertEqual(preview['affected_count'],1)
        self.assertFalse(preview['affected'][0]['within_range'])
        self.tags.update('owner','car',dict(payload,action='place-name-save',preview_token=preview['preview_token']))
        self.assertEqual(self.places()['name_regions'][0]['id'],region['id'])
        self.assertEqual(self.places()['places'][0]['name_source'],'reference')
        self.tags.update('owner','car',dict(action='place-name-undo',revision=2))
        self.assertEqual(self.places()['places'][0]['label'],'园区')

    def test_polygon_preview_is_readonly_and_shape_change_invalidates_token(self):
        payload=self.payload()
        preview=self.tags.update('owner','car',payload)
        self.assertFalse(self.tags.store.path.exists())
        changed=[list(p) for p in POLYGON];changed[0][0]-=.0001
        with self.assertRaises(ValueError):
            self.tags.update('owner','car',dict(payload,vertices=changed,action='place-name-save',preview_token=preview['preview_token']))

    def test_polygon_over_circle_can_save_and_names_trip_without_deleting_circle(self):
        self.rename('已有车库')
        self.trip('outside',self.start+3600000,(31.1989,121.4),(31.21,121.41))
        payload=self.payload();payload.update(place_id=None,place_key=None,revision=1)
        preview=self.tags.update('owner','car',payload)
        self.assertEqual(preview['conflicts'][0]['name'],'已有车库')
        self.assertEqual(preview['affected_count'],2,'preview must include circle-centre membership')
        self.tags.update('owner','car',dict(payload,action='place-name-save',preview_token=preview['preview_token']))
        self.assertEqual(self.places()['places'][0]['label'],'园区')
        self.assertEqual(len(self.places()['name_regions']),2)
        self.assertEqual(self.places()['places'][0]['departures'],2,'whole circle belongs to polygon by centre')
        self.trip('next',self.start+4*86400000,(31.2,121.4),(31.21,121.41))
        self.assertEqual(self.places(date='2026-10-01')['places'][0]['label'],'园区')
        self.tags.update('owner','car',dict(action='place-name-undo',revision=2))
        self.assertEqual(self.places()['places'][0]['label'],'已有车库')

    def test_circle_over_polygon_can_save_without_overriding_polygon(self):
        self.save_polygon()
        payload=dict(action='place-name-preview',date='2026-09-28',name='圆形车库',shape='circle',
                     place_id=None,place_key=None,revision=1)
        self.tags.store.change('owner','car','place_names','save','circle',
                               dict(name='原车库',latitude=31.2,longitude=121.4,radius_m=50),1)
        payload.update(region_id='circle',radius_m=100,revision=2)
        preview=self.tags.update('owner','car',payload)
        self.tags.update('owner','car',dict(payload,action='place-name-save',preview_token=preview['preview_token']))
        self.assertEqual(self.places()['places'][0]['label'],'园区')
        self.assertEqual(next(r for r in self.places()['name_regions'] if r['id']=='circle')['name'],'圆形车库')

    def test_circle_to_polygon_preserves_original_centre_for_membership(self):
        self.tags.store.change('owner','car','place_names','save','circle',
                               dict(name='原圆形',latitude=31.1991,longitude=121.4,radius_m=150),0)
        vertices=[[31.19905,121.3999],[31.19905,121.4001],[31.19915,121.4001],[31.19915,121.3999]]
        payload=dict(action='place-name-preview',date='2026-09-28',region_id='circle',name='精确区域',
                     shape='polygon',vertices=vertices,revision=1)
        preview=self.tags.update('owner','car',payload)
        self.assertEqual(preview['affected_count'],1)
        self.tags.update('owner','car',dict(payload,action='place-name-save',preview_token=preview['preview_token']))
        self.assertEqual(self.places()['places'][0]['label'],'精确区域')
        self.assertEqual((self.places()['places'][0]['latitude'],self.places()['places'][0]['longitude']),(31.1991,121.4))
        payload.update(action='place-name-preview',shape='circle',radius_m=150,revision=2)
        preview=self.tags.update('owner','car',payload)
        self.tags.update('owner','car',dict(payload,action='place-name-save',preview_token=preview['preview_token']))
        region=self.places()['name_regions'][0]
        self.assertEqual((region['latitude'],region['longitude']),(31.1991,121.4))

    def test_two_overlapping_polygons_still_block_save(self):
        self.save_polygon()
        payload=self.payload();payload.update(place_id=None,place_key=None,revision=1)
        preview=self.tags.update('owner','car',payload)
        self.assertEqual(preview['conflicts'][0]['shape'],'polygon')
        with self.assertRaises(ValueError):
            self.tags.update('owner','car',dict(payload,action='place-name-save',preview_token=preview['preview_token']))

    def test_regions_remain_manageable_in_empty_month_and_undo(self):
        self.save_polygon()
        stats=self.places(date='2026-08-01')
        region=stats['name_regions'][0]
        payload=dict(action='place-name-clear',date='2026-08-01',region_id=region['id'],revision=1)
        self.tags.update('owner','car',payload)
        self.assertEqual(self.places()['places'][0]['name_source'],'reference')
        self.tags.update('owner','car',dict(action='place-name-undo',revision=2))
        self.assertEqual(self.places()['places'][0]['label'],'园区')
