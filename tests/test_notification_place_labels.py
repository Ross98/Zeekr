"""Saved labels are local, owner-scoped evidence; no network or real vehicles."""
import json
import sqlite3
import unittest

import test_commute_tags as fixtures
import test_charging_places as charging
from zeekr_control.notification_places import NotificationPlaces


class NotificationPlaceLabelTests(unittest.TestCase):
    setUp=fixtures.CommuteTagTests.setUp
    trip=fixtures.CommuteTagTests.trip

    def service(self):
        return NotificationPlaces(self.db, self.tags.store)

    def label(self, name='自定义车库', identity='home', **changes):
        body=dict(name=name,latitude=31.2,longitude=121.4,radius_m=150)
        body.update(changes)
        store=self.tags.store
        return store.change('owner','car','place_names','save',identity,body,
                            store.read('owner','car','place_names')['revision'])

    def event(self, trusted=True):
        self.trip('out',self.start,(31.2,121.4),(31.21,121.41))
        with sqlite3.connect(self.db) as db:
            data=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='out'").fetchone()[0])
        data['start_location']=dict(valid=True,plottable=True,trusted=trusted,
            latitude=31.2,longitude=121.4,coordinate_system='WGS84（社区解释）')
        return data

    def test_manual_label_beats_external_address_and_is_owner_vehicle_scoped(self):
        self.label();data=self.event()
        result=self.service().resolve('owner','car','trip_end',data,'out')
        self.assertEqual(result['start']['name'],'自定义车库')
        self.assertEqual(result['start']['reference']['source'],'saved_place')
        self.assertEqual(self.service().resolve('other','car','trip_end',data,'out'),{})
        self.assertEqual(self.service().resolve('owner','other','trip_end',data,'out'),{})

    def test_untrusted_endpoint_uses_shared_boundary_sample_without_promoting_gps(self):
        self.label();data=self.event(trusted=False)
        result=self.service().resolve('owner','car','trip_end',data,'out')
        self.assertEqual(result['start']['name'],'自定义车库')
        self.assertEqual(result['start']['reference']['position_source'],'boundary_sample')
        self.assertIs(data['start_location']['trusted'],False)

    def test_untrusted_start_cannot_borrow_future_sample(self):
        self.label();data=self.event(trusted=False)
        self.assertEqual(self.service().resolve('owner','car','trip_start',data,'out'),{})

    def test_saved_label_preserves_age_of_historical_reference(self):
        from zeekr_control.notification_location import reference_suffix
        self.label();data=self.event(trusted=False)
        point=dict(valid=True,plottable=True,trusted=True,latitude=31.2,longitude=121.4,
                   coordinate_system='WGS84（社区解释）')
        with sqlite3.connect(self.db) as db:
            stamp=self.start-60000
            db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',
                       ('car','previous',stamp,stamp,60,json.dumps(point)))
        reference=self.service().resolve('owner','car','trip_end',data,'out')['start']['reference']
        self.assertEqual(reference['position_source'],'historical')
        self.assertIn('1分钟前可信定位',reference_suffix(reference))

    def test_charge_inference_qualifier_is_not_replaced_by_a_manual_name(self):
        from zeekr_control.notification_location import reference_suffix
        reference=dict(source='saved_charge_place',scope='region',position_source='stationary_between_trips',position_reference=True)
        self.assertIn('停车证据推断',reference_suffix(reference))

    def test_deleted_and_conflicting_polygon_labels_are_not_guessed(self):
        self.label();data=self.event()
        self.tags.store.change('owner','car','place_names','delete','home',None,1)
        self.assertEqual(self.service().resolve('owner','car','trip_end',data,'out'),{})
        ring=[[31.199,121.399],[31.201,121.399],[31.201,121.401],[31.199,121.401]]
        self.label('区域甲','a',shape='polygon',vertices=ring)
        self.label('区域乙','b',shape='polygon',vertices=ring)
        self.assertEqual(self.service().resolve('owner','car','trip_end',data,'out'),{})


class NotificationChargeLabelTests(unittest.TestCase):
    setUp=charging.ChargingPlaceTests.setUp
    add=charging.ChargingPlaceTests.add
    charge=charging.ChargingPlaceTests.charge
    observe=charging.ChargingPlaceTests.observe
    review=charging.ChargingPlaceTests.review
    proposal=charging.ChargingPlaceTests.proposal

    def confirm(self,scope='single',**extra):
        places=self.review().places
        data=dict(self.proposal(scope),**extra)
        plan=places.preview('owner','car',data)
        places.update('owner','car',dict(data,action='save',token=plan['token']))

    def resolve(self,identity='charge',kind='charge_end',owner='owner',vehicle='car'):
        with sqlite3.connect(self.db) as db:
            data=json.loads(db.execute('SELECT summary FROM monitor_events WHERE id=?',(identity,)).fetchone()[0])
        return NotificationPlaces(self.db,self.review().places.store).resolve(owner,vehicle,kind,data,identity)

    def test_single_confirmation_without_gps_stays_on_one_charge(self):
        self.charge();self.charge('other')
        self.confirm(latitude=None,longitude=None,station_name='我标注的充电站')
        result=self.resolve()['start']
        self.assertEqual(result['name'],'测试广场 · 我标注的充电站')
        self.assertTrue(result['reference']['label_only'])
        self.assertEqual(self.resolve('other'),{})
        self.assertEqual(self.resolve(owner='other'),{})
        self.assertEqual(self.resolve(vehicle='other'),{})

    def test_place_confirmation_can_name_next_charge_start_but_single_cannot(self):
        start=self.charge();self.observe(start);self.observe(start+60000)
        self.confirm(scope='place')
        self.charge('next',day='2026-09-16');self.observe(start+86400000)
        result=self.resolve('next','charge_start')['start']
        self.assertEqual(result['name'],'测试广场')
        self.assertEqual(result['reference']['scope'],'place')

    def test_unconfirmed_reference_candidate_is_not_adopted(self):
        start=self.charge();self.observe(start-60000)
        self.assertEqual(self.resolve(),{})
