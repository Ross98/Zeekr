"""Synthetic trash/restore transactions and shared read visibility."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.monitor import Monitor
from zeekr_control.events import EventStore
from zeekr_control.trips import TripStore
from zeekr_control.usage_events import UsageEvents
from zeekr_control.trip_management import TripRecordManager
from test_trips import TripFixtures, MIDNIGHT, sample
import test_web_server as web_base


class ManagementTests(TripFixtures, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tracks.sqlite3'
        self.monitor = Monitor(self.path)
        self.now = 1000
        self.manager = TripRecordManager(self.path, clock=lambda: self.now)
        self.event('one')
        self.event('two', end=MIDNIGHT+120000)
        self.event('other', vehicle='car-b')

    def query(self, status='active', **kw):
        return self.manager.query('car-a', '2024-01-01', '2024-01-02', status, **kw)

    def preview(self, ids=None, action='trash', owner='owner', revision=None):
        return self.manager.preview('car-a', action, ids or ['one'],
                                    self.manager.revision('car-a') if revision is None else revision, owner)

    def change(self, ids=None, action='trash'):
        plan = self.preview(ids, action)
        return self.manager.execute(plan['token'], 'owner', guard=lambda: None)

    def test_reads_and_preview_do_not_migrate_or_mutate_old_database(self):
        before = self.path.read_bytes()
        self.assertEqual(self.query()['revision'], 0)
        result = self.preview()
        self.assertEqual(result['count'], 1)
        self.assertEqual(before, self.path.read_bytes())
        encoded = json.dumps(result)
        for private in ('PRIVATE', 'latitude', 'car-a', 'report_v2'):
            self.assertNotIn(private, encoded)

    def test_batch_restore_persists_and_all_readers_exclude(self):
        for offset in (-60000, 0, 60000):
            self.monitor.tracks.record('car-a', sample(MIDNIGHT+offset), MIDNIGHT+offset, 180)
        with self.monitor.tracks.connect() as db:
            original = db.execute('SELECT id,summary,message FROM monitor_events ORDER BY id').fetchall()
        self.change(['one','two'])
        self.assertEqual(self.query()['items'], [])
        self.assertEqual(len(self.query('trash')['items']), 2)
        self.assertEqual(TripRecordManager(self.path).revision('car-a'), 1)
        self.assertEqual(EventStore(self.path).query('car-a','2024-01-02','trip_end')['events'], [])
        self.assertIsNone(EventStore(self.path).latest('car-a')['trip_end'])
        self.assertEqual(UsageEvents(self.path).between('car-a', MIDNIGHT, MIDNIGHT+86400000)['events'], [])
        from zeekr_control.vehicle_research import VehicleResearch
        from zeekr_control.archive_reader import ArchiveReader
        research = VehicleResearch(ArchiveReader(self.path.parent/'snapshot-archive'), self.path,
                                   clock=lambda:MIDNIGHT+86400000)
        self.assertEqual(research.query('owner','car-a','2024-01-02','2024-01-02')['event_conditions']['total'],0)
        with self.assertRaises(ValueError):
            UsageEvents(self.path).get('car-a','one')
        with self.assertRaises(ValueError):
            TripStore(self.path).bounds('car-a','one','2024-01-02')
        self.assertGreater(self.monitor.tracks.day('car-a','2024-01-02')['count'], 0)
        self.change(['one','two'], 'restore')
        self.assertEqual(len(self.query()['items']), 2)
        self.assertEqual(len(UsageEvents(self.path).between('car-a', MIDNIGHT, MIDNIGHT+86400000)['events']), 2)
        self.assertEqual(TripStore(self.path).bounds('car-a','one','2024-01-02'), (MIDNIGHT-60000, MIDNIGHT+60000))
        with self.monitor.tracks.connect() as db:
            self.assertEqual(original, db.execute('SELECT id,summary,message FROM monitor_events ORDER BY id').fetchall())
            self.assertEqual(db.execute("SELECT delivery FROM monitor_events WHERE id='one'").fetchone()[0], 'cancelled')
            self.assertEqual(db.execute('SELECT count(*) FROM trip_record_audit').fetchone()[0], 2)

    def test_invalid_batch_is_atomic_and_scoped_to_ended_current_vehicle(self):
        with self.monitor.tracks.connect() as db:
            db.execute("UPDATE monitor_events SET kind='charge_end' WHERE id='two'")
        for ids in (['one','other'], ['one','two'], ['one','missing'], ['one','current'], ['one','one'], ['one']*101):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.preview(ids)
        self.assertEqual(self.manager.revision('car-a'), 0)
        self.assertEqual(len(self.query()['items']), 1)

    def test_stale_revision_changed_row_expiry_replay_and_owner_rejected(self):
        first = self.preview()
        self.change(['two'])
        with self.assertRaises(ValueError):
            self.manager.execute(first['token'], 'owner')
        with self.assertRaises(ValueError):
            self.preview(revision=0)
        plan = self.preview()
        with self.monitor.tracks.connect() as db:
            db.execute("UPDATE monitor_events SET delivery='sent' WHERE id='one'")
        with self.assertRaises(ValueError):
            self.manager.execute(plan['token'], 'owner')
        plan = self.preview()
        with self.assertRaises(ValueError):
            self.manager.execute(plan['token'], 'someone-else')
        plan = self.preview()
        self.now += 301
        with self.assertRaises(ValueError):
            self.manager.execute(plan['token'], 'owner')
        plan = self.preview()
        self.manager.execute(plan['token'], 'owner')
        with self.assertRaises(ValueError):
            self.manager.execute(plan['token'], 'owner')

    def test_commit_guard_rolls_back_schema_and_pending_delivery(self):
        plan = self.preview()
        def fail():
            raise ValueError('account switched')
        with self.assertRaises(ValueError):
            self.manager.execute(plan['token'], 'owner', guard=fail)
        self.assertEqual(len(self.query()['items']), 2)
        with self.monitor.tracks.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='trip_record_trash'").fetchone())
            self.assertEqual(db.execute("SELECT delivery FROM monitor_events WHERE id='one'").fetchone()[0], 'pending')

    def test_sending_refused_pending_cancelled_and_restore_never_resends(self):
        with self.monitor.tracks.connect() as db:
            db.execute("UPDATE monitor_events SET delivery='sending' WHERE id='one'")
        with self.assertRaises(ValueError):
            self.preview()
        with self.monitor.tracks.connect() as db:
            db.execute("UPDATE monitor_events SET delivery='pending' WHERE id='one'")
        self.change()
        self.change(action='restore')
        sent = []
        self.monitor.deliver(lambda *args: sent.append(args), now=MIDNIGHT+86400000)
        with self.monitor.tracks.connect() as db:
            self.assertEqual(db.execute("SELECT delivery FROM monitor_events WHERE id='one'").fetchone()[0], 'cancelled')

    def test_malformed_records_manageable_and_pagination_stable(self):
        with self.monitor.tracks.connect() as db:
            db.execute("UPDATE monitor_events SET summary='not json' WHERE id='one'")
        first = self.query(limit=1)
        second = self.query(limit=1, cursor=first['next_cursor'])
        self.assertEqual([first['items'][0]['id'], second['items'][0]['id']], ['two','one'])
        self.assertTrue(second['items'][0]['issue'])
        self.change()
        self.assertEqual(self.query('trash')['items'][0]['id'], 'one')

    def test_broken_numeric_values_remain_manageable_without_browser_invalid_dates(self):
        with self.monitor.tracks.connect() as db:
            db.execute("UPDATE monitor_events SET summary=? WHERE id='one'",
                       (json.dumps({'start_time':1e100,'end_time':10**400,'distance_km':10**400,
                                    'start_soc':{'secret':'PRIVATE'},'partial':False}),))
        item = self.preview()['items'][0]
        self.assertIsNone(item['start_time'])
        self.assertIsNone(item['end_time'])
        self.assertIsNone(item['distance_km'])
        self.assertNotIn('PRIVATE',json.dumps(item))
        self.change()

    def test_missing_database_read_stays_missing_and_invalid_inputs_reject(self):
        missing = TripRecordManager(self.path.with_name('missing.sqlite3'))
        self.assertEqual(missing.query('car-a','2024-01-01','2024-01-02')['items'], [])
        self.assertFalse(missing.path.exists())
        for args in (('bad','2024-01-02'), ('2024-01-02','2024-01-01'), ('2020-01-01','2024-01-02')):
            with self.assertRaises(ValueError):
                self.manager.query('car-a', *args)
        with self.assertRaises(ValueError):
            self.query(status='invalid')

    def test_energy_and_future_report_baselines_skip_trash(self):
        from zeekr_control.energy import read_attainment
        from zeekr_control.report_history import _candidates
        with self.monitor.tracks.connect() as db:
            report = {'schema_version':2,'decoder_version':'test','partial':False,
                      'end_time':MIDNIGHT+60000,'quality':{}}
            value = json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='one'").fetchone()[0])
            value['report_v2'] = report
            db.execute("UPDATE monitor_events SET summary=? WHERE id='one'", (json.dumps(value),))
            db.execute('INSERT INTO report_metric_index VALUES(?,?,?,?,?,?,?)',
                       ('one','car-a','trip_end',report['end_time'],'test',0,'{}'))
            self.assertEqual(len(_candidates(db,'car-a','trip_end',MIDNIGHT+999999,'test')[0]), 1)
        self.change(['one','two'])
        self.assertEqual(read_attainment(self.path,'car-a',{})['status'], 'no_trip')
        with self.monitor.tracks.connect() as db:
            self.assertEqual(_candidates(db,'car-a','trip_end',MIDNIGHT+999999,'test')[0], [])


class ManagementWebTests(TripFixtures, unittest.TestCase):
    setUp = web_base.WebServerTests.setUp
    cleanup = web_base.WebServerTests.cleanup
    request = web_base.WebServerTests.request
    post = web_base.WebServerTests.post

    def setup_trips(self):
        self.post('/api/refresh', {'vehicle':1})
        self.monitor = Monitor(self.app.database_path)
        self.event('one', self.app.vehicle_key)
        self.event('two', self.app.vehicle_key)
        self.context = self.request('GET','/api/state')[1]['insights_context']

    def test_api_preview_execute_csrf_scope_and_statistics_restore(self):
        self.setup_trips()
        from zeekr_control.personal_store import account_scope
        from zeekr_control.storage import load
        owner = account_scope(load(self.app.session_path))
        self.app.trip_tags.update(owner,self.app.vehicle_key,
            {'action':'save','event_id':'one','tags':['通勤'],'note':'留存','revision':0})
        personal_before = self.app.personal_store.path.read_bytes()
        path = '/api/trips/manage?start=2024-01-01&end=2024-01-02'
        code, listing = self.request('GET',path)
        self.assertEqual(code,200)
        data = {'context':self.context,'action':'trash','ids':['one','two'],'revision':listing['revision']}
        self.assertEqual(self.request('POST','/api/trips/manage/preview',data,{'Content-Type':'application/json'})[0],403)
        code, plan = self.post('/api/trips/manage/preview',data)
        self.assertEqual(code,200,plan)
        code, result = self.post('/api/trips/manage/execute',{'context':self.context,'token':plan['token']})
        self.assertEqual(code,200,result)
        self.assertEqual(self.request('GET','/api/tracks?date=2024-01-02&trip=one')[0],400)
        self.assertEqual(self.request('GET','/api/state')[1]['trip_records_revision'],1)
        for action,count in [('trash',0),('restore',2)]:
            if action == 'restore':
                plan = self.post('/api/trips/manage/preview',dict(data,action='restore',revision=1))[1]
                self.assertEqual(self.post('/api/trips/manage/execute',{'context':self.context,'token':plan['token']})[0],200)
            report = self.app.insights('report','month','2024-01-02')
            self.assertEqual(report['current']['totals']['trip_count'], count)
            self.assertEqual(len(self.app.insights('calendar','2024-01-02')['events']), count)
            tags = self.app.insights('trip-tags','2024-01-02')
            self.assertEqual(len(tags['events']), count)
            self.assertEqual(len(tags['groups']), int(count>0))
            self.assertEqual(self.app.insights('ledger','2024-01-02')['cost_per_km']['distance_samples'], count)
        self.assertEqual(self.app.personal_store.path.read_bytes(), personal_before)
        self.assertEqual(self.request('GET','/api/trips/manage?start=2024-01-01&end=2024-01-02&status=trash')[1]['items'],[])

    def test_account_switch_and_unverified_binding_reject_mutation(self):
        from zeekr_control.storage import save
        self.setup_trips()
        data = {'context':self.context,'action':'trash','ids':['one'],'revision':0}
        plan = self.post('/api/trips/manage/preview',data)[1]
        save(self.app.session_path,{'accessToken':'DIFFERENT','userId':'new-owner'})
        self.assertEqual(self.post('/api/trips/manage/execute',{'context':self.context,'token':plan['token']})[0],400)
        self.assertEqual(self.post('/api/trips/manage/preview',data)[0],400)
        self.assertEqual(self.request('GET','/api/trips/manage?start=2024-01-01&end=2024-01-02')[0],400)

    def test_session_file_changes_at_commit_roll_back(self):
        from zeekr_control.storage import save
        self.setup_trips()
        plan = self.post('/api/trips/manage/preview',{'context':self.context,'action':'trash','ids':['one'],'revision':0})[1]
        original_schema = self.app.trip_manager._schema
        def switch(db):
            original_schema(db)
            save(self.app.session_path,{'accessToken':'DIFFERENT','userId':'new-owner'})
        with patch.object(self.app.trip_manager,'_schema',side_effect=switch):
            self.assertEqual(self.post('/api/trips/manage/execute',{'context':self.context,'token':plan['token']})[0],400)
        with self.monitor.tracks.connect() as db:
            self.assertEqual(db.execute("SELECT delivery FROM monitor_events WHERE id='one'").fetchone()[0],'pending')
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='trip_record_trash'").fetchone())


if __name__ == '__main__':
    unittest.main()
