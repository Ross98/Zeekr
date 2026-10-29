"""Guarded date-scoped historical splits; all data synthetic."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from zeekr_control.monitor import Monitor
from test_monitor import BASE, sample


class TripSplitRepairTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.trip_split_repair import build_plan, apply_plan
        self.build_plan,self.apply_plan=build_plan,apply_plan
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.root.chmod(0o700)
        replay=Monitor(self.root/'replay'/'tracks.sqlite3')
        for second,km,soc,moving in [(0,100,80,False),(20,101,80,True),(40,110,77,False),
                (100,110,77,False),(120,110,77,True),(140,111,76,True),
                (160,116,72,False),(220,116,72,False)]:
            raw=sample(second,km=km,soc=soc,speed=20 if moving else 0,
                       engine='engine_on' if moving else 'engine_off',ready=int(moving))
            raw['additionalVehicleStatus']['drivingBehaviourStatus']={'gearAutoStatus':3 if moving else 0}
            replay.observe('car',raw,BASE+second*1000,battery_capacity_kwh=86)
        with replay.tracks.connect() as db:
            db.row_factory=sqlite3.Row
            self.parts=[dict(r) for r in db.execute("SELECT * FROM monitor_events WHERE kind='trip_end' ORDER BY created")]
        live=Monitor(self.root/'tracks.sqlite3');self.live=live
        first=json.loads(self.parts[0]['summary']);last=json.loads(self.parts[1]['summary'])
        first.pop('segmentation_policy',None)
        first.update(end_time=last['end_time'],end_soc=last['end_soc'],soc_delta=-8,
                     distance_km=16,duration_seconds=(last['end_time']-first['start_time'])/1000)
        with live.tracks.connect() as db:
            live._event(db,'car','trip_end',first,BASE+900000)
            old=copy.deepcopy(first);old.update(start_time=BASE-86400000+20000,end_time=BASE-86400000+160000)
            live._event(db,'car','trip_end',old,BASE-86400000+900000)
            db.execute("UPDATE monitor_events SET delivery='uncertain',attempts=1,error='通知响应未确认'")
            db.execute("UPDATE monitor_event_alerts SET delivery='sent',sent_at=1")
        self.plan=self.build_plan(self.root/'tracks.sqlite3','car','2024-01-01',self.parts)

    def test_split_preserves_earlier_rows_and_sent_alert_and_no_replay(self):
        with self.live.tracks.connect() as db:
            before=db.execute('SELECT * FROM monitor_events WHERE created<?',(BASE,)).fetchall()
            alert=db.execute('SELECT * FROM monitor_event_alerts WHERE event_id=?',(self.parts[0]['id'],)).fetchone()
        self.assertTrue(self.apply_plan(self.root,self.plan,self.root/'backup'))
        with self.live.tracks.connect() as db:
            self.assertEqual(before,db.execute('SELECT * FROM monitor_events WHERE created<?',(BASE,)).fetchall())
            self.assertEqual(alert,db.execute('SELECT * FROM monitor_event_alerts WHERE event_id=?',(self.parts[0]['id'],)).fetchone())
            rows=db.execute('SELECT summary,delivery FROM monitor_events WHERE created>=?',(BASE,)).fetchall()
            self.assertEqual(len(rows),2)
            self.assertEqual(sum(json.loads(r[0])['distance_km'] for r in rows),16)
            self.assertEqual({r[1] for r in rows},{'uncertain','local'})
            self.assertEqual(db.execute("SELECT count(*) FROM monitor_event_media WHERE delivery='pending'").fetchone()[0],1) # older only
        self.assertFalse(self.apply_plan(self.root,self.plan,self.root/'second-backup'))

    def test_changed_source_aborts_before_modification(self):
        with self.live.tracks.connect() as db:db.execute("UPDATE monitor_events SET error='changed' WHERE id=?",(self.parts[0]['id'],))
        with self.assertRaises(ValueError):self.apply_plan(self.root,self.plan,self.root/'backup')

    def test_plan_rejects_changed_totals_or_out_of_window_boundaries(self):
        for change in ('distance_km','start_time'):
            parts=copy.deepcopy(self.parts);body=json.loads(parts[0]['summary'])
            body[change]=999 if change=='distance_km' else BASE-1
            parts[0]['summary']=json.dumps(body)
            with self.assertRaises(ValueError):self.build_plan(self.root/'tracks.sqlite3','car','2024-01-01',parts)

    def test_active_trip_or_sending_record_blocks_apply(self):
        with self.live.tracks.connect() as db:db.execute("UPDATE monitor_events SET delivery='sending' WHERE id=?",(self.parts[0]['id'],))
        with self.assertRaises(ValueError):self.apply_plan(self.root,self.plan,self.root/'backup')

    def test_active_trip_overlap_blocks_even_without_a_send(self):
        with self.live.tracks.connect() as db:
            db.execute('INSERT OR REPLACE INTO monitor_state VALUES(?,?)',('car',json.dumps({'last':None,'trip':{'start':{'time':BASE+1000}},'charge':None})))
        with self.assertRaises(ValueError):self.apply_plan(self.root,self.plan,self.root/'backup')

    def test_failed_write_rolls_back_all_segments(self):
        with self.live.tracks.connect() as db:
            before=db.execute('SELECT * FROM monitor_events ORDER BY id').fetchall()
            db.execute("CREATE TRIGGER reject_split BEFORE INSERT ON monitor_events BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.apply_plan(self.root,self.plan,self.root/'backup')
        with self.live.tracks.connect() as db:
            self.assertEqual(before,db.execute('SELECT * FROM monitor_events ORDER BY id').fetchall())

    def test_account_context_change_blocks_repair(self):
        from zeekr_control.trip_split_repair import digest
        plan=copy.deepcopy(self.plan);plan['context']={'owner':'old','session':'old'}
        plan['id']=digest({k:v for k,v in plan.items() if k!='id'})
        with self.assertRaises(ValueError):self.apply_plan(self.root,plan,self.root/'backup')

    def test_manual_annotation_blocks_unsafe_automatic_remap(self):
        with sqlite3.connect(self.root/'personal.sqlite3') as db:
            db.execute('CREATE TABLE records(owner,vehicle,body,deleted)')
            db.execute('INSERT INTO records VALUES(?,?,?,0)',('owner','car',json.dumps({'event_id':self.parts[0]['id']})))
        (self.root/'personal.sqlite3').chmod(0o600)
        with self.assertRaises(ValueError):self.apply_plan(self.root,self.plan,self.root/'backup')


if __name__=='__main__':unittest.main()
