"""Synthetic timeline and correction contracts; no gateway or owner data."""
import unittest
from unittest.mock import Mock
from tests import test_commute_tags as fixtures
from zeekr_control.daily_timeline import DailyTimeline


class TimelineTests(unittest.TestCase):
    trip=fixtures.CommuteTagTests.trip
    def setUp(self):
        fixtures.CommuteTagTests.setUp(self)
        self.trip('a', self.start+3600000, (31.2,121.4), (31.21,121.41))
        self.archive=Mock()
        self.archive.iter_records.return_value=iter([])
        self.timeline=DailyTimeline(self.db,self.archive,self.tags.store)

    def day(self, owner='owner', vehicle='car', **extra):
        return self.timeline.query('scope',vehicle,'2026-09-28',owner=owner,**extra)

    def test_summary_positions_opt_in_and_unknown_coverage(self):
        result=self.day()
        self.assertEqual(result['summary']['distance_km'],20)
        self.assertEqual(result['summary']['duration_seconds'],1200)
        self.assertIsNone(result['summary']['actual_cents'])
        self.assertNotIn('position', result['records'][0])
        self.assertEqual(result['coverage']['coverage'],'missing')
        self.assertTrue(self.day(positions=True)['records'][0]['position'])

    def test_cross_midnight_shown_without_apportioning_distance(self):
        self.trip('night',self.start-600000,(31.2,121.4),(31.21,121.41))
        result=self.day()
        self.assertEqual(len(result['records']),2)
        self.assertEqual(result['summary']['distance_km'],40)
        previous=self.timeline.query('scope','car','2026-09-27',owner='owner')
        self.assertEqual(len(previous['records']),1)
        self.assertIsNone(previous['summary']['distance_km'])

    def correction(self, action='reject', remember=False, name=None):
        data=dict(date='2026-09-28',record_id='a',side='end',action=action,remember=remember,revision=0)
        if name is not None:data['name']=name
        plan=self.timeline.update('owner','car',dict(data,operation='preview'),scope='scope')
        return self.timeline.update('owner','car',dict(data,operation='save',preview_token=plan['preview_token']),scope='scope')

    def test_reject_keeps_fact_and_is_scoped_undoable(self):
        self.correction()
        self.assertEqual(len(self.day()['records']),1)
        self.assertEqual(self.day()['records'][0]['end_place']['decision'],'rejected')
        self.assertNotEqual(self.day(owner='other')['records'][0]['end_place']['decision'],'rejected')
        self.assertEqual(self.day(vehicle='other')['records'],[])
        self.timeline.update('owner','car',dict(operation='undo',revision=1),scope='scope')
        self.assertNotEqual(self.day()['records'][0]['end_place']['decision'],'rejected')

    def test_manual_survives_reread_and_stale_preview_rejected(self):
        self.correction('assign',name='测试停车场')
        self.assertEqual(self.day()['records'][0]['end_place']['label'],'测试停车场')
        with self.assertRaises(ValueError):self.correction('assign',name='过期修改')

    def test_remembered_rejection_and_single_rejection(self):
        self.trip('b',self.start+4000000,(31.2,121.4),(31.21,121.41))
        self.correction(remember=True)
        self.assertTrue(all(r['end_place']['decision']=='rejected' for r in self.day()['records']))

    def test_preview_guard_rolls_back(self):
        data=dict(date='2026-09-28',record_id='a',side='end',action='assign',name='停车场',revision=0,operation='preview')
        preview=self.timeline.update('owner','car',data,scope='scope')
        def guard():raise ValueError('account changed')
        with self.assertRaises(ValueError):self.timeline.update('owner','car',dict(data,operation='save',preview_token=preview['preview_token']),scope='scope',guard=guard)
        self.assertEqual(self.day()['correction_revision'],0)

    def test_year_uses_same_totals_and_has_no_positions(self):
        result=self.timeline.year('scope','car','2026',owner='owner')
        self.assertEqual(result['totals']['distance_km'],20)
        self.assertEqual(len(result['months']),12)
        self.assertNotIn('position',str(result))

    def test_zero_unknown_start_and_deleted_events(self):
        import json,sqlite3
        with sqlite3.connect(self.db) as db:
            data=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='a'").fetchone()[0])
            data.update(start_time=None,duration_seconds=None,distance_km=0)
            db.execute("UPDATE monitor_events SET summary=? WHERE id='a'",(json.dumps(data),))
        result=self.day()
        self.assertEqual(result['summary']['distance_km'],0)
        self.assertIsNone(result['summary']['duration_seconds'])
        self.assertEqual(result['records'][0]['start_place']['source'],'unknown')
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE trip_record_trash(vehicle TEXT,event_id TEXT)')
            db.execute("INSERT INTO trip_record_trash VALUES('car','a')")
        self.assertEqual(self.day()['records'],[])
        with sqlite3.connect(self.db) as db:db.execute('DELETE FROM trip_record_trash')
        self.assertEqual(len(self.day()['records']),1)

    def test_name_confirm_guard_unknown_and_monthly_correction(self):
        with self.assertRaises(ValueError):self.correction('confirm')
        self.correction('assign',name='合成地标')
        calendar=self.timeline.calendar.query('scope','car','2026-09-28',owner='owner')
        self.assertEqual(calendar['events'][0]['end_label'],'合成地标')
        annual=self.timeline.year('scope','car','2026',owner='owner')
        self.assertEqual(annual['frequent_places'][0]['label'],'合成地标')

    def test_history_pagination_and_stale_cursor(self):
        for index in range(36):self.trip(f'row-{index}',self.start+index*1800000,(31.2,121.4),(31.21,121.41))
        key=self.day()['records'][0]['end_place']['key']
        page=self.timeline.history('scope','car','2026-09-01','2026-09-28',key,owner='owner')
        self.assertEqual(len(page['records']),30)
        self.assertTrue(page['next_cursor'])
        following=self.timeline.history('scope','car','2026-09-01','2026-09-28',key,page['next_cursor'],owner='owner')
        self.assertEqual(len(following['records']),7)
        self.correction('assign',name='新名称')
        with self.assertRaises(ValueError):self.timeline.history('scope','car','2026-09-01','2026-09-28',key,page['next_cursor'],owner='owner')

    def test_history_keeps_nearby_manually_named_places_separate(self):
        from zeekr_control.trip_place_names import anchor_key
        nearby=(31.2105,121.41)
        self.trip('nearby',self.start+7200000,(31.2,121.4),nearby)
        keys=[]
        for revision,(point,name) in enumerate([((31.21,121.41),'车库'),(nearby,'商店')]):
            key=anchor_key(dict(latitude=point[0],longitude=point[1]));keys.append(key)
            self.tags.store.change('owner','car','place_names','save',key,
                                   dict(name=name,latitude=point[0],longitude=point[1],radius_m=25),revision)
        self.assertEqual({r['end_place']['label'] for r in self.day()['records']},{'车库','商店'})
        for key,identity in zip(keys,['a','nearby']):
            result=self.timeline.history('scope','car','2026-09-01','2026-09-28',key,owner='owner')
            self.assertEqual([r['id'] for r in result['records']],[identity])

    def test_history_respects_explicit_assignment_to_another_place(self):
        from zeekr_control.trip_place_names import anchor_key
        self.trip('b',self.start+7200000,(31.2,121.4),(31.21,121.41))
        original_key=self.day()['records'][0]['end_place']['key']
        target=anchor_key(dict(latitude=31.3,longitude=121.5))
        self.tags.store.change('owner','car','place_names','save',target,
                               dict(name='指定车库',latitude=31.3,longitude=121.5,radius_m=25),0)
        data=dict(date='2026-09-28',record_id='a',side='end',action='assign',target_key=target,revision=0)
        preview=self.timeline.update('owner','car',dict(data,operation='preview'),scope='scope')
        self.timeline.update('owner','car',dict(data,operation='save',preview_token=preview['preview_token']),scope='scope')
        assigned=self.timeline.history('scope','car','2026-09-01','2026-09-28',target,owner='owner')
        self.assertEqual([r['id'] for r in assigned['records']],['a'])
        original=self.timeline.history('scope','car','2026-09-01','2026-09-28',original_key,owner='owner')
        self.assertEqual([r['id'] for r in original['records']],['b'])

    def test_history_still_reconciles_automatic_anchors_across_days(self):
        self.trip('earlier',self.start-86400000+3600000,(31.2,121.4),(31.2105,121.41))
        key=self.day()['records'][0]['end_place']['key']
        result=self.timeline.history('scope','car','2026-09-01','2026-09-28',key,owner='owner')
        self.assertEqual([r['id'] for r in result['records']],['earlier','a'])

    def test_assign_existing_place_tracks_its_name_and_manual_beats_rejection(self):
        from zeekr_control.trip_place_names import anchor_key
        key=anchor_key(dict(latitude=31.21,longitude=121.41))
        self.tags.store.change('owner','car','place_names','save',key,dict(name='既有车库',latitude=31.21,longitude=121.41,radius_m=150),0)
        result=self.day()
        self.assertEqual(result['known_places'][0]['key'],key)
        data=dict(date='2026-09-28',record_id='a',side='end',action='assign',target_key=key,revision=0)
        preview=self.timeline.update('owner','car',dict(data,operation='preview'),scope='scope')
        self.timeline.update('owner','car',dict(data,operation='save',preview_token=preview['preview_token']),scope='scope')
        self.assertEqual(self.day()['records'][0]['end_place']['label'],'既有车库')
        self.tags.store.change('owner','car','place_names','save',key,dict(name='改名后车库',latitude=31.21,longitude=121.41,radius_m=150),1)
        self.assertEqual(self.day()['records'][0]['end_place']['label'],'改名后车库')

    def test_rejected_candidate_does_not_hide_new_manual_name(self):
        from zeekr_control.trip_place_names import anchor_key
        self.correction(remember=True)
        key=anchor_key(dict(latitude=31.21,longitude=121.41))
        self.tags.store.change('owner','car','place_names','save',key,dict(name='人工命名车库',latitude=31.21,longitude=121.41,radius_m=150),0)
        p=self.day()['records'][0]['end_place']
        self.assertEqual(p['label'],'人工命名车库')
        self.assertEqual(p['source'],'manual')

    def test_cross_month_arrival_is_counted_once_in_year(self):
        from zeekr_control.tracks import day_bounds
        from zeekr_control.trip_place_names import anchor_key
        begin=day_bounds('2026-10-01')[0]-600000
        self.trip('cross-month',begin,(31.2,121.4),(31.21,121.41))
        key=anchor_key(dict(latitude=31.21,longitude=121.41))
        self.tags.store.change('owner','car','place_names','save',key,dict(name='车库',latitude=31.21,longitude=121.41,radius_m=150),0)
        result=self.timeline.year('scope','car','2026',owner='owner')
        self.assertEqual(result['frequent_places'][0]['arrivals'],2)
        self.assertEqual(result['totals']['distance_km'],40)


class RecallApiTests(unittest.TestCase):
    from tests.test_insights_api import InsightsApiTests as _fixture
    setUp=_fixture.setUp
    cleanup_server=_fixture.cleanup_server
    get=_fixture.get
    post_ledger=_fixture.post_ledger

    def test_read_validation_and_write_context(self):
        self.assertEqual(self.get('/api/timeline?date=bad')[0],400)
        self.assertEqual(self.get('/api/year-review?year=bad')[0],400)
        self.assertEqual(self.get('/api/place-history?start=2026-09-01&end=2026-09-30&key=bad')[0],400)
        code,result=self.get('/api/timeline?date=2026-09-20')
        self.assertEqual(code,200)
        self.assertEqual(result['records'],[])
        self.assertNotIn('position',json_dump(result))
        payload=dict(operation='undo',revision=0,context=result['context'])
        self.assertEqual(self.post_ledger(payload,{'X-Request-Key':''},'/api/place-corrections')[0],403)
        self.assertEqual(self.post_ledger(dict(payload,context='stale'),route='/api/place-corrections')[0],400)


def json_dump(value):
    import json
    return json.dumps(value)


class RecallEvidenceTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        import tempfile
        from zeekr_control.storage import save
        from zeekr_control.web import App
        from tests.recall_fixture import populate
        from zeekr_control.personal_store import account_scope
        from zeekr_control.snapshots import session_scope
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        path=Path(tmp.name)/'private'/'session.json';session=dict(accessToken='SYNTHETIC-ONLY',userId='recall-test');save(path,session)
        def forbidden(_):raise AssertionError('No gateway')
        self.app=App(path,client_factory=forbidden);self.addCleanup(self.app.close)
        populate(self.app,session)
        self.app._restore_snapshot(session)
        self.owner=account_scope(session);self.scope=session_scope(session)
        self.timeline=self.app.daily_timeline

    def test_parking_uses_saved_place_even_without_trips(self):
        import sqlite3
        from zeekr_control.trip_place_names import anchor_key
        vehicle=self.app.vehicle_key
        key=anchor_key(dict(latitude=31.21,longitude=121.41))
        self.app.personal_store.change(self.owner,vehicle,'place_names','save',key,
                                      dict(name='停车车库',latitude=31.21,longitude=121.41,radius_m=25),0)
        with sqlite3.connect(self.app.database_path) as db:db.execute('DELETE FROM monitor_events')
        day=self.timeline.query(self.scope,vehicle,'2026-09-20',owner=self.owner)
        self.assertTrue(day['records'])
        self.assertTrue(all(r['end_place']['label']=='停车车库' for r in day['records']))
        month=self.timeline.calendar.query(self.scope,vehicle,'2026-09-20',owner=self.owner)
        self.assertTrue(month['totals']['parking_places'])
        self.assertTrue(all(p['key']==key for p in month['totals']['parking_places']))
        foreign=self.timeline.query(self.scope,vehicle,'2026-09-20',owner='other')
        self.assertTrue(all(r['end_place']['label']!='停车车库' for r in foreign['records']))

    def test_parking_does_not_borrow_name_outside_saved_radius(self):
        import json,sqlite3
        from zeekr_control.trip_place_names import anchor_key
        from zeekr_control.tracks import day_bounds
        vehicle=self.app.vehicle_key;self.db=self.app.database_path
        point=(31.2105,121.41)
        start=day_bounds('2026-09-20')[0]+7*3600000;end=start+1200000
        with sqlite3.connect(self.db) as db:
            summary=dict(start_time=start,end_time=end,duration_seconds=1200,distance_km=20,partial=False)
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                       ('nearby-shop',vehicle,'trip_end',json.dumps(summary),'SYNTHETIC',end))
            for stamp,position in ((start+30000,(31.2,121.4)),(end-30000,point)):
                location=dict(latitude=position[0],longitude=position[1],trusted=True,plottable=True,
                              coordinate_system='WGS84（社区解释）')
                db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',
                           (vehicle,'nearby-shop-'+str(stamp),stamp,stamp,30,json.dumps(location)))
            db.execute("DELETE FROM monitor_events WHERE id!='nearby-shop'")
        key=anchor_key(dict(latitude=point[0],longitude=point[1]))
        self.app.personal_store.change(self.owner,vehicle,'place_names','save',key,
                                      dict(name='附近商店',latitude=point[0],longitude=point[1],radius_m=25),0)
        day=self.timeline.query(self.scope,vehicle,'2026-09-20',owner=self.owner)
        parked=[r for r in day['records'] if r['type']=='parking']
        self.assertTrue(parked)
        self.assertTrue(all(r['end_place']['label']!='附近商店' for r in parked))
        month=self.timeline.calendar.query(self.scope,vehicle,'2026-09-20',owner=self.owner)
        self.assertTrue(all(p['label']!='附近商店' for p in month['totals']['parking_places']))

    def test_parking_charge_overlap_and_fact_preservation(self):
        from zeekr_control.usage_events import UsageEvents
        vehicle=self.app.vehicle_key
        before=UsageEvents(self.app.database_path).between(vehicle,0,32503680000000)['events']
        result=self.timeline.query(self.scope,vehicle,'2026-09-20',owner=self.owner,positions=True)
        self.assertEqual([r['type'] for r in result['records']],['trip','parking','charge','parking','trip','parking'])
        parking=next(r for r in result['records'] if r['type']=='parking')
        self.assertEqual(parking['duration_seconds'],39*60)
        data=dict(date='2026-09-20',record_id=parking['id'],side='end',action='reject',revision=0)
        plan=self.timeline.update(self.owner,vehicle,dict(data,operation='preview'),scope=self.scope)
        self.timeline.update(self.owner,vehicle,dict(data,operation='save',preview_token=plan['preview_token']),scope=self.scope)
        after=self.timeline.query(self.scope,vehicle,'2026-09-20',owner=self.owner)
        self.assertEqual(len(after['records']),len(result['records']))
        revised=next(r for r in after['records'] if r['id']==parking['id'])
        self.assertEqual(revised['end_place']['decision'],'rejected')
        self.assertEqual(UsageEvents(self.app.database_path).between(vehicle,0,32503680000000)['events'],before)
        self.assertNotIn('position',json_dump(after))
        self.assertNotIn('latitude',json_dump(after))

    def test_month_length_history_and_overnight_identity(self):
        vehicle=self.app.vehicle_key
        day=self.timeline.query(self.scope,vehicle,'2026-09-20',owner=self.owner)
        key=next(r for r in day['records'] if r['type']=='trip')['start_place']['key']
        result=self.timeline.history(self.scope,vehicle,'2026-08-21','2026-09-20',key,owner=self.owner)
        self.assertGreaterEqual(result['count'],1)
        before=self.timeline.query(self.scope,vehicle,'2026-09-18',owner=self.owner)
        after=self.timeline.query(self.scope,vehicle,'2026-09-19',owner=self.owner)
        a=[r for r in before['records'] if r['type']=='parking' and r['cross_midnight']]
        b=[r for r in after['records'] if r['type']=='parking' and r['cross_midnight']]
        self.assertEqual(len(a),1)
        self.assertEqual(a[0]['id'],b[0]['id'])
        self.assertEqual(a[0]['duration_seconds'],b[0]['duration_seconds'])
