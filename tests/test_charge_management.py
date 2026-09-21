"""Synthetic charge-event recycle-bin behavior; no owner data."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from zeekr_control.events import EventStore
from zeekr_control.monitor import Monitor
from zeekr_control.usage_events import UsageEvents
from test_trips import MIDNIGHT
import test_web_server as web_base
from unittest.mock import patch


class ChargeManagementContractTests(unittest.TestCase):
    def test_charge_record_manager_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('zeekr_control.charge_management'))


class ChargeManagementTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.charge_management import ChargeRecordManager
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tracks.sqlite3'
        self.monitor = Monitor(self.path)
        self.now = 1000
        self.manager = ChargeRecordManager(self.path, clock=lambda: self.now)
        self.event('charge-one', MIDNIGHT + 3600000)
        self.event('charge-two', MIDNIGHT + 7200000, delivery='sent')
        self.event('trip', MIDNIGHT + 10800000, kind='trip_end')

    def event(self, identity, end, *, kind='charge_end', delivery='pending', vehicle='car-a'):
        summary = {'start_time': end - 1800000, 'end_time': end, 'duration_seconds': 1800,
                   'start_soc': 40, 'end_soc': 64, 'soc_delta': 24, 'partial': False,
                   'battery_capacity_kwh': 86}
        with self.monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created,delivery) '
                       'VALUES (?,?,?,?,?,?,?)',
                       (identity, vehicle, kind, json.dumps(summary), 'PRIVATE', end, delivery))

    def query(self, status='active'):
        return self.manager.query('car-a', '2024-01-02', '2024-01-02', status)

    def change(self, identity='charge-one', action='trash'):
        plan = self.manager.preview('car-a', action, [identity], self.manager.revision('car-a'), 'owner')
        return self.manager.execute(plan['token'], 'owner')

    def test_trash_restore_preserves_raw_event_and_all_shared_readers_follow_visibility(self):
        before = self.path.read_bytes()
        self.assertEqual([r['id'] for r in self.query()['items']], ['charge-two', 'charge-one'])
        self.change()
        self.assertNotEqual(before, self.path.read_bytes())
        self.assertEqual([r['id'] for r in self.query()['items']], ['charge-two'])
        self.assertEqual([r['id'] for r in self.query('trash')['items']], ['charge-one'])
        self.assertEqual([r['id'] for r in UsageEvents(self.path).between(
            'car-a', MIDNIGHT, MIDNIGHT + 86400000)['events']], ['trip', 'charge-two'])
        self.assertEqual([r['id'] for r in EventStore(self.path).query(
            'car-a', '2024-01-02', 'charge_end')['events']], ['charge-two'])
        with self.monitor.tracks.connect() as db:
            row = db.execute("SELECT kind,summary,message,delivery FROM monitor_events WHERE id='charge-one'").fetchone()
            self.assertEqual(row[:3], ('charge_end', json.dumps({'start_time': MIDNIGHT + 1800000,
                'end_time': MIDNIGHT + 3600000, 'duration_seconds': 1800, 'start_soc': 40,
                'end_soc': 64, 'soc_delta': 24, 'partial': False, 'battery_capacity_kwh': 86}), 'PRIVATE'))
            self.assertEqual(row[3], 'cancelled')
        self.change(action='restore')
        self.assertEqual(len(self.query()['items']), 2)
        self.assertEqual(self.query('trash')['items'], [])
        with self.monitor.tracks.connect() as db:
            deliveries = dict(db.execute("SELECT id,delivery FROM monitor_events WHERE id IN ('charge-one','charge-two')"))
        self.assertEqual(deliveries, {'charge-one':'cancelled','charge-two':'sent'})

    def test_sending_notification_cannot_be_trashed(self):
        self.event('charge-sending', MIDNIGHT + 14400000, delivery='sending')
        with self.assertRaises(ValueError):
            self.change('charge-sending')

    def test_scope_revision_and_preview_are_charge_only(self):
        preview = self.manager.preview('car-a', 'trash', ['charge-one'], 0, 'owner')
        self.assertEqual(preview['count'], 1)
        self.assertNotIn('PRIVATE', json.dumps(preview))
        for identities in (['trip'], ['missing'], ['charge-one', 'charge-one']):
            with self.subTest(identities=identities), self.assertRaises(ValueError):
                self.manager.preview('car-a', 'trash', identities, 0, 'owner')
        self.manager.execute(preview['token'], 'owner')
        self.assertEqual(self.manager.revision('car-a'), 1)
        with self.assertRaises(ValueError):
            self.manager.preview('car-a', 'trash', ['charge-two'], 0, 'owner')

    def test_direct_charging_detail_and_statistics_exclude_trash(self):
        from zeekr_control.charging_analytics import ChargingAnalytics
        analytics = ChargingAnalytics(self.path)
        self.assertEqual(analytics.session('car-a', 'charge-one')['id'], 'charge-one')
        before = analytics.statistics('car-a', 7, 'all', MIDNIGHT + 12*3600000)
        self.assertEqual({r['id'] for r in before['records']}, {'charge-one', 'charge-two'})
        self.change()
        with self.assertRaises(ValueError):
            analytics.session('car-a', 'charge-one')
        after = analytics.statistics('car-a', 7, 'all', MIDNIGHT + 12*3600000)
        self.assertEqual([r['id'] for r in after['records']], ['charge-two'])


class ChargeManagementWebTests(unittest.TestCase):
    setUp = web_base.WebServerTests.setUp
    cleanup = web_base.WebServerTests.cleanup
    request = web_base.WebServerTests.request
    post = web_base.WebServerTests.post

    def test_browser_asset_is_served_and_loaded(self):
        code, html = self.request('GET','/')
        self.assertEqual(code,200)
        self.assertIn('/charge-management.js',html)
        self.assertEqual(self.request('GET','/charge-management.js')[0],200)

    def setup_charges(self):
        self.post('/api/refresh', {'vehicle': 1})
        monitor = Monitor(self.app.database_path)
        for identity, offset in (('charge-one', 3600000), ('charge-two', 7200000)):
            end = MIDNIGHT + offset
            summary = {'start_time': end-1800000, 'end_time': end, 'duration_seconds': 1800,
                       'start_soc': 40, 'end_soc': 64, 'soc_delta': 24, 'partial': False,
                       'battery_capacity_kwh': 86}
            with monitor.tracks.connect() as db:
                db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                           (identity, self.app.vehicle_key, 'charge_end', json.dumps(summary), 'PRIVATE', end))
        self.context = self.request('GET', '/api/state')[1]['insights_context']

    def test_api_preview_execute_excludes_charge_everywhere_and_restores(self):
        self.setup_charges()
        path = '/api/charging/manage?start=2024-01-02&end=2024-01-02'
        code, listing = self.request('GET', path)
        self.assertEqual(code, 200)
        self.assertEqual(len(listing['items']), 2)
        data = {'context': self.context, 'action': 'trash', 'ids': ['charge-one'],
                'revision': listing['revision'], 'with_linked_bills': False}
        code, plan = self.post('/api/charging/manage/preview', data)
        self.assertEqual(code, 200, plan)
        code, result = self.post('/api/charging/manage/execute',
                                 {'context': self.context, 'token': plan['token']})
        self.assertEqual(code, 200, result)
        self.assertEqual(self.request('GET', '/api/state')[1]['charge_records_revision'], 1)
        self.assertEqual(self.request('GET', '/api/charging/session?id=charge-one')[0], 400)
        stats = self.request('GET', '/api/charging/statistics?days=7&mode=all')[1]
        self.assertNotIn('charge-one', [row['id'] for row in stats['records']])
        ledger = self.app.insights('ledger', '2024-01-02')
        self.assertNotIn('charge-one', [row['id'] for row in ledger['events']])
        trash = self.request('GET', path+'&status=trash')[1]
        restore = self.post('/api/charging/manage/preview', dict(data, action='restore', revision=1))[1]
        self.assertEqual(trash['items'][0]['id'], 'charge-one')
        self.assertEqual(self.post('/api/charging/manage/execute',
                                   {'context': self.context, 'token': restore['token']})[0], 200)
        self.assertEqual(self.request('GET', '/api/charging/session?id=charge-one')[0], 200)

    def test_linked_bill_is_preserved_by_default_and_can_be_trashed_together(self):
        from zeekr_control.personal_store import account_scope
        from zeekr_control.storage import load
        self.setup_charges()
        owner = account_scope(load(self.app.session_path))
        self.app.charge_ledger.update(owner, self.app.vehicle_key,
            {'action':'save','date':'2024-01-02','source':'public','unit_price':'1.0000',
             'event_id':'charge-one','revision':0})
        path = '/api/charging/manage?start=2024-01-02&end=2024-01-02'
        listing = self.request('GET', path)[1]
        data = {'context':self.context,'action':'trash','ids':['charge-one'],
                'revision':listing['revision'],'with_linked_bills':False}
        plan = self.post('/api/charging/manage/preview', data)[1]
        self.assertEqual([row['event_id'] for row in plan['linked_bills']], ['charge-one'])
        self.post('/api/charging/manage/execute', {'context':self.context,'token':plan['token']})
        ledger = self.app.insights('ledger', '2024-01-02')
        self.assertEqual(len(ledger['entries']), 1)
        self.assertTrue(ledger['entries'][0]['source_event_removed'])
        self.assertIsNone(ledger['entries'][0]['estimated_cents'])
        kept = ledger['entries'][0]
        self.app.charge_ledger.update(owner, self.app.vehicle_key,
            {'action':'save','id':kept['id'],'date':kept['date'],'source':kept['source'],
             'amount':'8.00','event_id':kept['source_event_id'],'revision':ledger['revision']})
        ledger = self.app.insights('ledger', '2024-01-02')
        self.assertEqual(ledger['entries'][0]['actual_cents'], 800)
        self.assertTrue(ledger['entries'][0]['source_event_removed'])

        # A second linked bill can be moved to the ledger recycle bin in the same previewed action.
        self.app.charge_ledger.update(owner, self.app.vehicle_key,
            {'action':'save','date':'2024-01-02','source':'home','amount':'12.00',
             'event_id':'charge-two','revision':ledger['revision']})
        listing = self.request('GET', path)[1]
        ledger = self.app.insights('ledger', '2024-01-02')
        data.update(ids=['charge-two'], revision=listing['revision'], with_linked_bills=True,
                    ledger_revision=ledger['revision'])
        plan = self.post('/api/charging/manage/preview', data)[1]
        self.assertTrue(plan['with_linked_bills'])
        self.post('/api/charging/manage/execute', {'context':self.context,'token':plan['token']})
        ledger = self.app.insights('ledger', '2024-01-02')
        self.assertEqual([row['source_event_id'] for row in ledger['trash']], ['charge-two'])
        trash_listing = self.request('GET', path+'&status=trash')[1]
        restore_data = {'context':self.context,'action':'restore','ids':['charge-two'],
                        'revision':trash_listing['revision'],'with_linked_bills':True,
                        'ledger_revision':ledger['revision']}
        restore = self.post('/api/charging/manage/preview',restore_data)[1]
        self.assertEqual([row['event_id'] for row in restore['linked_bills']],['charge-two'])
        self.post('/api/charging/manage/execute',{'context':self.context,'token':restore['token']})
        ledger = self.app.insights('ledger','2024-01-02')
        self.assertEqual([row['source_event_id'] for row in ledger['entries']],['charge-two','charge-one'])

    def test_linked_bill_failure_rolls_back_event_trash(self):
        from zeekr_control.personal_store import account_scope
        from zeekr_control.storage import load
        self.setup_charges()
        owner = account_scope(load(self.app.session_path))
        self.app.charge_ledger.update(owner, self.app.vehicle_key,
            {'action':'save','date':'2024-01-02','source':'public','amount':'5.00',
             'event_id':'charge-one','revision':0})
        listing = self.request('GET','/api/charging/manage?start=2024-01-02&end=2024-01-02')[1]
        ledger = self.app.insights('ledger','2024-01-02')
        data = {'context':self.context,'action':'trash','ids':['charge-one'],'revision':listing['revision'],
                'with_linked_bills':True,'ledger_revision':ledger['revision']}
        plan = self.post('/api/charging/manage/preview',data)[1]
        with patch.object(self.app.charge_ledger,'batch_change',side_effect=ValueError('write failed')):
            self.assertEqual(self.post('/api/charging/manage/execute',
                {'context':self.context,'token':plan['token']})[0],400)
        self.assertEqual(len(self.request('GET','/api/charging/manage?start=2024-01-02&end=2024-01-02')[1]['items']),2)


if __name__ == '__main__':
    unittest.main()
