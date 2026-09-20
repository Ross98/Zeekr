import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from zeekr_control.personal_store import PersonalStore
from zeekr_control.tracks import day_bounds


class TripTagTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.trip_tags import TripTags
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'tracks.sqlite3'
        self.store=PersonalStore(self.root/'personal.sqlite3');self.tags=TripTags(self.store,self.db)
        self.start,_=day_bounds('2026-09-20')
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE monitor_events(id TEXT PRIMARY KEY,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
            for identity,distance,delta,partial,vehicle,kind in [('a',40,-10,False,'car','trip_end'),
                    ('b',20,-5,False,'car','trip_end'),('partial',100,-20,True,'car','trip_end'),
                    ('short',2,-1,False,'car','trip_end'),('other',50,-10,False,'other','trip_end'),
                    ('charge',0,10,False,'car','charge_end')]:
                data=dict(start_time=self.start,end_time=self.start+3600000,duration_seconds=3600,
                          distance_km=distance,soc_delta=delta,start_soc=70,end_soc=70+delta,partial=partial,
                          battery_capacity_kwh=86,vin='PRIVATE',position={'secret':'PRIVATE'})
                db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',(identity,vehicle,kind,json.dumps(data),self.start))
        self.db.chmod(0o600)

    def save(self,event='a',tags=None,revision=0,**extra):
        return self.tags.update('owner','car',dict(action='save',event_id=event,tags=tags or ['通勤'],
                    note='测试备注',revision=revision,**extra))

    def query(self):return self.tags.query('owner','car','2026-09-20')

    def test_readonly_projection_and_unknown_not_zero(self):
        result=self.query()
        self.assertEqual(len(result['events']),4)
        self.assertFalse(self.store.path.exists())
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertEqual(result['groups'],[])

    def test_custom_tags_are_trimmed_deduplicated_and_persisted(self):
        self.save(tags=[' 通勤 ','接娃','通勤'])
        self.assertEqual(next(r['tags'] for r in self.query()['events'] if r['id']=='a'),['通勤','接娃'])
        from zeekr_control.trip_tags import TripTags
        reopened=TripTags(PersonalStore(self.store.path),self.db).query('owner','car','2026-09-20')
        self.assertEqual(reopened['revision'],1)

    def test_group_comparison_keeps_partial_out_of_metrics(self):
        self.save();self.save('b',revision=1);self.save('partial',revision=2)
        group=self.query()['groups'][0]
        self.assertEqual(group['count'],3);self.assertEqual(group['complete_count'],2)
        self.assertEqual(group['distance_km']['mean'],30)
        self.assertEqual(group['distance_km']['median'],30)
        self.assertEqual(group['soc_consumed']['mean'],7.5)
        self.assertAlmostEqual(group['efficiency']['value'],21.5)
        self.assertEqual(group['efficiency']['samples'],2)

    def test_efficiency_uses_only_same_eligible_energy_distance_pairs(self):
        self.save();self.save('short',revision=1)
        group=self.query()['groups'][0]
        self.assertEqual(group['complete_count'],2)
        self.assertEqual(group['efficiency']['samples'],1)
        self.assertAlmostEqual(group['efficiency']['value'],21.5)

    def test_multi_tag_membership_is_explicit_and_not_additive(self):
        self.save(tags=['通勤','接娃'])
        self.assertEqual([g['tag'] for g in self.query()['groups']],['接娃','通勤'])
        self.assertEqual([g['count'] for g in self.query()['groups']],[1,1])
        self.assertEqual(len(self.query()['events']),4)

    def test_edit_delete_undo_and_clear_tags(self):
        result=self.save();self.save(tags=['高速'],revision=1,id=result['id'])
        self.assertEqual(self.query()['groups'][0]['tag'],'高速')
        self.tags.update('owner','car',dict(action='delete',id=result['id'],revision=2))
        self.assertEqual(self.query()['groups'],[])
        self.tags.update('owner','car',dict(action='undo',revision=3))
        self.assertEqual(self.query()['groups'][0]['tag'],'高速')
        self.tags.update('owner','car',dict(action='save',event_id='a',tags=[],note='',revision=4))
        self.assertEqual(self.query()['groups'],[])

    def test_validation_foreign_event_charge_and_stale_write(self):
        for event in ('other','charge','missing'):
            with self.assertRaises(ValueError):self.save(event)
        for tags in ('commute',[None],['x'*25],['a']*11):
            with self.assertRaises(ValueError):self.save(tags=tags)
        self.save()
        with self.assertRaises(ValueError):self.save(revision=0)
        with self.assertRaises(ValueError):self.save('b',revision=1,id='wrong-id')

    def test_owner_vehicle_and_month_scope(self):
        self.save()
        self.assertEqual(self.tags.query('other','car','2026-09-20')['groups'],[])
        self.assertEqual(self.tags.query('owner','other','2026-09-20')['groups'],[])
        self.assertEqual(self.tags.query('owner','car','2026-08-20')['events'],[])


if __name__=='__main__':unittest.main()
