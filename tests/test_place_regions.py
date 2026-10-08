import unittest

from zeekr_control.place_regions import contains, overlaps, validate_polygon
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

    def test_polygon_overlap_preview_blocks_save(self):
        self.rename('已有车库')
        payload=self.payload();payload.update(place_id=None,place_key=None,revision=1)
        preview=self.tags.update('owner','car',payload)
        self.assertEqual(preview['conflicts'][0]['name'],'已有车库')
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
