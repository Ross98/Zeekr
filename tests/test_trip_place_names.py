import json
import sqlite3
import unittest

from tests import test_commute_tags as fixtures


class TripPlaceNameTests(unittest.TestCase):
    setUp=fixtures.CommuteTagTests.setUp
    trip=fixtures.CommuteTagTests.trip
    save_rule=fixtures.CommuteTagTests.save_rule

    def setUp(self):
        fixtures.CommuteTagTests.setUp(self)
        self.trip('a',self.start,(31.2,121.4),(31.21,121.41))

    def places(self,owner='owner',date='2026-09-28'):
        return self.tags.query(owner,'car',date)['place_statistics']

    def rename(self,name='车库',revision=0,**extra):
        p=self.places()['places'][0]
        data=dict(action='place-name-save',date='2026-09-28',place_id=p['id'],place_key=p['name_key'],name=name,revision=revision)
        data.update(extra)
        preview=self.tags.update('owner','car',dict(data,action='place-name-preview'))
        data['preview_token']=preview['preview_token']
        return self.tags.update('owner','car',data)

    def address(self,name='浦东新区·测试园区',trusted=True):
        with sqlite3.connect(self.db) as db:
            raw=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='a'").fetchone()[0])
            raw.update(start_address=name,start_location=dict(latitude=31.2,longitude=121.4,valid=True,trusted=trusted,coordinate_system='WGS84（社区解释）'))
            db.execute("UPDATE monitor_events SET summary=? WHERE id='a'",(json.dumps(raw),))

    def test_current_home_work_names_do_not_require_enabled_rule(self):
        self.save_rule()
        result=self.places()
        self.assertEqual([p['label'] for p in result['places']],['家','公司'])
        self.assertEqual([p['name_source'] for p in result['places']],['commute','commute'])
        self.tags.update('owner','car',dict(action='commute-pause',revision=1))
        self.assertEqual(self.places()['places'][0]['label'],'家')

    def test_cached_address_requires_trust_and_keeps_approximate_suffix(self):
        self.address();p=self.places()['places'][0]
        self.assertEqual(p['label'],'浦东新区·测试园区附近')
        self.assertEqual(p['name_source'],'address')
        self.address(trusted=False)
        self.assertEqual(self.places()['places'][0]['name_source'],'reference')

    def test_cached_road_names_are_filtered_without_rewriting_history(self):
        for name in ('浦东新区·测试路', '测试路南0.2km附近', '浦东新区'):
            with self.subTest(name=name):
                self.address(name)
                before=self.db.read_bytes()
                self.assertEqual(self.places()['places'][0]['name_source'],'reference')
                self.assertEqual(self.db.read_bytes(),before)
        self.address('人民路站')
        self.assertEqual(self.places()['places'][0]['label'],'人民路站附近')

    def test_manual_priority_isolation_persistence_and_clear(self):
        self.save_rule();self.address();self.rename()
        p=self.places()['places'][0]
        self.assertEqual(p['label'],'车库');self.assertEqual(p['name_source'],'manual')
        self.assertNotEqual(self.places('different')['places'][0]['label'],'车库')
        with self.assertRaises(ValueError):self.rename(revision=0)
        self.tags.update('owner','car',dict(action='place-name-clear',date='2026-09-28',place_id=p['id'],place_key=p['name_key'],revision=1))
        self.assertEqual(self.places()['places'][0]['label'],'家')
        self.tags.update('owner','car',dict(action='place-name-undo',revision=2))
        self.assertEqual(self.places()['places'][0]['label'],'车库')

    def test_manual_name_survives_month_change_and_small_drift(self):
        self.rename()
        self.trip('next',self.start+4*86400000,(31.2005,121.4),(31.21,121.41))
        self.assertEqual(self.places(date='2026-10-01')['places'][0]['label'],'车库')

    def test_bad_anchor_and_name_rejected(self):
        for name in ('','a'*41,'a\nb'):
            with self.assertRaises(ValueError):self.rename(name=name)
        with self.assertRaises(ValueError):self.rename(place_key='wrong')
        self.assertFalse(self.tags.store.path.exists())

    def test_manual_name_does_not_extend_beyond_150_m(self):
        self.rename()
        self.trip('next',self.start+4*86400000,(31.202,121.4),(31.21,121.41))
        self.assertEqual(self.places(date='2026-10-01')['places'][0]['name_source'],'reference')

    def test_conflicting_addresses_remain_reference_number(self):
        self.address('测试园区甲')
        self.trip('b',self.start+3600000,(31.2,121.4),(31.21,121.41))
        with sqlite3.connect(self.db) as db:
            raw=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='b'").fetchone()[0])
            raw.update(start_address='测试园区乙',start_location=dict(latitude=31.2,longitude=121.4,valid=True,trusted=True,coordinate_system='WGS84（社区解释）'))
            db.execute("UPDATE monitor_events SET summary=? WHERE id='b'",(json.dumps(raw),))
        self.assertEqual(self.places()['places'][0]['name_source'],'reference')

    def test_cached_address_outside_group_does_not_name_it(self):
        self.address()
        with sqlite3.connect(self.db) as db:
            raw=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='a'").fetchone()[0])
            raw['start_location']['latitude']=32
            db.execute("UPDATE monitor_events SET summary=? WHERE id='a'",(json.dumps(raw),))
        self.assertEqual(self.places()['places'][0]['name_source'],'reference')

    def test_missing_month_is_validation_error_and_no_write(self):
        with self.assertRaises(ValueError):self.rename(date=None)
        self.assertFalse(self.tags.store.path.exists())

    def test_guard_rolls_back_name_write_and_events_unchanged(self):
        before=self.db.read_bytes();p=self.places()['places'][0]
        def guard():raise ValueError('changed session')
        data=dict(action='place-name-preview',date='2026-09-28',place_id=p['id'],place_key=p['name_key'],name='车库',revision=0)
        preview=self.tags.update('owner','car',data)
        with self.assertRaises(ValueError):self.tags.update('owner','car',dict(data,action='place-name-save',preview_token=preview['preview_token']),guard=guard)
        self.assertEqual(self.places()['name_revision'],0)
        self.assertEqual(self.db.read_bytes(),before)
