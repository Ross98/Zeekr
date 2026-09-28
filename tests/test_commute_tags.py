import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.personal_store import PersonalStore
from zeekr_control.trip_tags import TripTags
from zeekr_control.tracks import day_bounds


class CommuteTagTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.db = root / 'tracks.sqlite3'
        self.tags = TripTags(PersonalStore(root / 'personal.sqlite3'), self.db)
        self.start, _ = day_bounds('2026-09-28')
        root.chmod(0o700)
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE monitor_events(id TEXT PRIMARY KEY,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
            db.execute('CREATE TABLE observations(id INTEGER PRIMARY KEY,vehicle TEXT,cache_key TEXT,state_time INTEGER,observed_time INTEGER,gap_seconds INTEGER,location TEXT)')
        self.db.chmod(0o600)

    def trip(self, identity, start, origin, destination, vehicle='car', trusted=True):
        end = start + 1200000
        data = dict(start_time=start,end_time=end,duration_seconds=1200,distance_km=20,
                    start_soc=80,end_soc=75,soc_delta=-5,partial=False)
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',(identity,vehicle,'trip_end',json.dumps(data),end))
            for index,(time,point) in enumerate(((start+30000,origin),(end-30000,destination))):
                location=dict(latitude=point[0],longitude=point[1],trusted=trusted,plottable=True,
                              coordinate_system='WGS84（社区解释）')
                db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',
                           (vehicle,f'{identity}-{index}',time,time,30,json.dumps(location)))

    def save_rule(self, **extra):
        with patch('zeekr_control.commute_tags.time.time',return_value=(self.start+3600000)/1000):
            payload=dict(action='commute-save',revision=0,
                home={'latitude':31.2,'longitude':121.4,'radius_m':300},
                work={'latitude':31.21,'longitude':121.41,'radius_m':300})
            payload.update(extra)
            return self.tags.update('owner','car',payload)

    def test_future_outbound_and_return_are_tagged_once(self):
        result=self.save_rule()
        effective=result['effective_at']
        self.trip('out',effective+1000,(31.2,121.4),(31.21,121.41))
        self.trip('back',effective+2000000,(31.21,121.41),(31.2,121.4))
        first=self.tags.query('owner','car','2026-09-28')
        second=self.tags.query('owner','car','2026-09-28')
        self.assertEqual([r['tags'] for r in first['events']],[['通勤'],['通勤']])
        self.assertTrue(all(r['automatic_commute'] for r in first['events']))
        self.assertEqual(first['events'],second['events'])
        self.assertEqual(first['groups'][0]['count'],2)

    def test_manual_exclusion_survives_rule_edit(self):
        effective=self.save_rule()['effective_at']
        self.trip('out',effective+1000,(31.2,121.4),(31.21,121.41))
        self.assertEqual(self.tags.query('owner','car','2026-09-28')['events'][0]['tags'],['通勤'])
        self.tags.update('owner','car',dict(action='commute-exclude',event_id='out'))
        self.assertEqual(self.tags.query('owner','car','2026-09-28')['events'][0]['tags'],[])
        self.assertEqual(self.tags.query('other','car','2026-09-28')['events'][0]['tags'],[])

    def test_outside_and_untrusted_do_not_get_tag(self):
        effective=self.save_rule()['effective_at']
        self.trip('far',effective+1000,(31.2,121.4),(31.23,121.41))
        self.trip('bad',effective+2000000,(31.2,121.4),(31.21,121.41),trusted=False)
        rows=self.tags.query('owner','car','2026-09-28')['events']
        self.assertEqual([r['tags'] for r in rows],[[],[]])

    def test_trip_before_rule_is_not_backfilled(self):
        self.trip('old',self.start+1000,(31.2,121.4),(31.21,121.41))
        self.save_rule()
        self.assertEqual(self.tags.query('owner','car','2026-09-28')['events'][0]['tags'],[])

    def test_rule_edit_keeps_prior_decision_and_manual_label(self):
        effective=self.save_rule()['effective_at']
        self.trip('out',effective+1000,(31.2,121.4),(31.21,121.41))
        self.tags.query('owner','car','2026-09-28')
        self.tags.update('owner','car',dict(action='save',event_id='out',tags=['接娃'],note='记录',revision=0))
        self.tags.update('owner','car',dict(action='commute-save',revision=1,
            home=dict(latitude=32,longitude=120,radius_m=300),
            work=dict(latitude=32.1,longitude=120.1,radius_m=300)))
        row=self.tags.query('owner','car','2026-09-28')['events'][0]
        self.assertEqual(row['tags'],['接娃','通勤'])
        self.assertEqual(row['manual_tags'],['接娃'])
        self.assertEqual(row['note'],'记录')

    def test_new_rule_version_applies_only_to_later_trips(self):
        effective=self.save_rule()['effective_at']
        self.trip('first',effective+1000,(31.2,121.4),(31.21,121.41))
        changed=self.tags.update('owner','car',dict(action='commute-save',revision=1,
            home=dict(latitude=32,longitude=120,radius_m=300),
            work=dict(latitude=32.1,longitude=120.1,radius_m=300)))
        self.trip('later',changed['effective_at']+1000,(31.2,121.4),(31.21,121.41))
        rows={r['id']:r for r in self.tags.query('owner','car','2026-09-28')['events']}
        self.assertEqual(rows['first']['tags'],['通勤'])
        self.assertEqual(rows['later']['tags'],[])

    def test_missing_boundary_sample_cannot_use_middle_point(self):
        effective=self.save_rule()['effective_at']
        self.trip('late',effective+1000,(31.2,121.4),(31.21,121.41))
        with sqlite3.connect(self.db) as db:
            db.execute('UPDATE observations SET state_time=state_time+? WHERE cache_key=?',(190000,'late-0'))
        row=self.tags.query('owner','car','2026-09-28')['events'][0]
        self.assertEqual(row['tags'],[])
        self.assertEqual(row['commute_reason'],'insufficient')

    def test_old_personal_database_stays_readable_by_version_one_code(self):
        with self.tags.store.connect(write=True) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
        self.save_rule()
        with sqlite3.connect(self.tags.store.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='commute_rule_versions'").fetchone())

    def test_overlapping_home_and_work_circles_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'过近'):
            self.save_rule(work=dict(latitude=31.204,longitude=121.4,radius_m=300))

    def test_pause_and_delete_affect_only_future_trips(self):
        effective=self.save_rule()['effective_at']
        self.trip('before-pause',effective+1000,(31.2,121.4),(31.21,121.41))
        with patch('zeekr_control.commute_tags.time.time',return_value=(self.start+3*3600000)/1000):
            paused=self.tags.update('owner','car',dict(action='commute-pause',revision=1))
        self.trip('paused',paused['effective_at']+1000,(31.2,121.4),(31.21,121.41))
        with patch('zeekr_control.commute_tags.time.time',return_value=(self.start+6*3600000)/1000):
            resumed=self.tags.update('owner','car',dict(action='commute-resume',revision=2))
        self.trip('resumed',resumed['effective_at']+1000,(31.2,121.4),(31.21,121.41))
        with patch('zeekr_control.commute_tags.time.time',return_value=(self.start+9*3600000)/1000):
            deleted=self.tags.update('owner','car',dict(action='commute-delete',revision=3))
        self.trip('deleted',deleted['effective_at']+1000,(31.2,121.4),(31.21,121.41))
        rows={r['id']:r for r in self.tags.query('owner','car','2026-09-28')['events']}
        self.assertEqual({name:row['tags'] for name,row in rows.items()},
                         {'before-pause':['通勤'],'paused':[],'resumed':['通勤'],'deleted':[]})

    def test_session_guard_rolls_back_rule_and_decision(self):
        def changed(): raise ValueError('账号已切换')
        with self.assertRaisesRegex(ValueError,'账号已切换'):
            with patch('zeekr_control.commute_tags.time.time',return_value=(self.start+3600000)/1000):
                self.tags.update('owner','car',dict(action='commute-save',revision=0,
                    home=dict(latitude=31.2,longitude=121.4,radius_m=300),
                    work=dict(latitude=31.21,longitude=121.41,radius_m=300)),guard=changed)
        self.assertEqual(self.tags.commute.rule('owner','car')['revision'],0)
        effective=self.save_rule()['effective_at']
        self.trip('out',effective+1000,(31.2,121.4),(31.21,121.41))
        with self.assertRaisesRegex(ValueError,'账号已切换'):
            self.tags.query('owner','car','2026-09-28',guard=changed)
        with self.tags.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM commute_decisions').fetchone()[0],0)


if __name__=='__main__': unittest.main()
