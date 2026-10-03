import json
import math
import sqlite3
import unittest
from tests import test_commute_tags as fixtures


class RemainingDashboardTests(unittest.TestCase):
    trip=fixtures.CommuteTagTests.trip
    def setUp(self):
        fixtures.CommuteTagTests.setUp(self)
        self.trip('out',self.start,(31.2,121.4),(31.21,121.41))
        self.trip('near',self.start+3600000,(31.2+math.degrees(100/6371000),121.4),(31.21,121.41))
        self.trip('back',self.start+7200000,(31.21,121.41),(31.2,121.4))

    def name_payload(self,**extra):
        p=self.tags.query('owner','car','2026-09-28')['place_statistics']['places'][0]
        return dict(action='place-name-preview',date='2026-09-28',place_id=p['id'],place_key=p['name_key'],
                    name='家',radius_m=50,revision=0,**extra)

    def test_naming_preview_shrink_and_stale_protection(self):
        payload=self.name_payload()
        preview=self.tags.update('owner','car',payload)
        self.assertEqual(preview['affected_count'],2)
        self.assertFalse(self.tags.store.path.exists(),'preview never writes')
        with self.assertRaises(ValueError):self.tags.update('owner','car',dict(payload,action='place-name-save'))
        self.tags.update('owner','car',dict(payload,action='place-name-save',preview_token=preview['preview_token']))
        result=self.tags.query('owner','car','2026-09-28')
        events={r['id']:r for r in result['events']}
        self.assertNotEqual(events['out']['start_place'],events['near']['start_place'])
        places={p['id']:p for p in result['place_statistics']['places']}
        self.assertEqual(places[events['out']['start_place']]['label'],'家')
        self.assertNotEqual(places[events['near']['start_place']]['label'],'家')
        p=places[events['out']['start_place']]
        edit=dict(payload,place_id=p['id'],place_key=p['name_key'],revision=1,name='车库')
        check=self.tags.update('owner','car',edit)
        self.trip('later',self.start+10800000,(31.2,121.4),(31.21,121.41))
        with self.assertRaises(ValueError):self.tags.update('owner','car',dict(edit,action='place-name-save',preview_token=check['preview_token']))

    def test_routes_metric_samples_direction_and_read_only(self):
        from zeekr_control.travel_insights import TravelInsights
        with sqlite3.connect(self.db) as db:
            complete=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='out'").fetchone()[0])
            complete['battery_capacity_kwh']=86
            db.execute("UPDATE monitor_events SET summary=? WHERE id='out'",(json.dumps(complete),))
            data=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='near'").fetchone()[0])
            data.update(partial=True,distance_km=None,battery_capacity_kwh=86)
            db.execute("UPDATE monitor_events SET summary=? WHERE id='near'",(json.dumps(data),))
        before=self.db.read_bytes()
        result=TravelInsights(self.tags.store,self.db).routes('owner','car','2026-09-28')
        self.assertEqual(sorted(r['count'] for r in result['routes']),[1,2])
        direction=next(r for r in result['routes'] if r['count']==2)
        self.assertEqual(direction['distance_km']['samples'],1)
        self.assertEqual(direction['duration_seconds']['samples'],2)
        self.assertEqual(direction['estimated_kwh']['samples'],2)
        self.assertEqual(direction['partial_count'],1)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertNotIn('latitude',json.dumps(result))
        self.assertFalse(self.tags.store.path.exists())

    def test_review_actual_unknown_pending_and_owner_isolation(self):
        from zeekr_control.travel_insights import TravelInsights
        from zeekr_control.charge_ledger import ChargeLedger
        with sqlite3.connect(self.db) as db:
            body=dict(start_time=self.start,end_time=self.start+3600000,duration_seconds=3600,start_soc=20,end_soc=40,soc_delta=20,partial=True,battery_capacity_kwh=86)
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',('charge','car','charge_end',json.dumps(body),self.start))
        ledger=ChargeLedger(self.tags.store,self.db)
        ledger.update('owner','car',dict(action='save',revision=0,date='2026-09-28',source='public',amount='0',event_id='charge'))
        ledger.update('owner','car',dict(action='save',revision=1,date='2026-09-28',source='public',amount='',parking_fee='2'))
        result=TravelInsights(self.tags.store,self.db).review('owner','car','2026-09-28')
        self.assertEqual(result['costs']['actual_cents'],200)
        self.assertEqual(result['costs']['unknown_charge_count'],1)
        self.assertEqual(result['pending_count'],0)
        other=TravelInsights(self.tags.store,self.db).review('different','car','2026-09-28')
        self.assertIsNone(other['costs']['actual_cents'])
        self.assertEqual(other['pending_count'],1)

    def test_overlapping_name_preview_reports_conflict_and_payload_changes_rejected(self):
        payload=self.name_payload()
        preview=self.tags.update('owner','car',payload)
        with self.assertRaises(ValueError):self.tags.update('owner','car',dict(payload,action='place-name-save',name='篡改',preview_token=preview['preview_token']))
        self.tags.update('owner','car',dict(payload,action='place-name-save',preview_token=preview['preview_token']))
        result=self.tags.query('owner','car','2026-09-28')
        events={r['id']:r for r in result['events']};p=next(p for p in result['place_statistics']['places'] if p['id']==events['near']['start_place'])
        second=dict(action='place-name-preview',date='2026-09-28',place_id=p['id'],place_key=p['name_key'],name='商场',radius_m=100,revision=1)
        preview=self.tags.update('owner','car',second)
        self.assertEqual(preview['conflicts'][0]['name'],'家')
        second['radius_m']=25
        self.assertEqual(self.tags.update('owner','car',second)['conflicts'],[])
