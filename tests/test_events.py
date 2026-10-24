import json
import tempfile
from pathlib import Path
import unittest

from zeekr_control.monitor import Monitor


class EventStoreTests(unittest.TestCase):
    def test_missing_storage_is_not_created_and_private_readonly_file_stays_readable(self):
        from zeekr_control.events import EventStore
        missing=self.path.parent/'missing'/'events.sqlite3';store=EventStore(missing)
        self.assertEqual(store.query('vehicle-a','2024-01-02','trip_end')['events'],[])
        self.assertEqual(store.latest('vehicle-a'),dict(trip_end=None,charge_end=None))
        self.assertFalse(missing.parent.exists())
        self.add('valid','vehicle-a','trip_end',1704126600000,distance_km=12)
        self.path.chmod(0o400);before=self.path.read_bytes()
        store=EventStore(self.path)
        self.assertEqual(store.query('vehicle-a','2024-01-02','trip_end')['events'][0]['distance_km'],12)
        self.assertEqual(store.latest('vehicle-a')['trip_end']['id'],'valid')
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.path.stat().st_mode & 0o777,0o400)

    def test_event_reads_reject_unsafe_storage_without_repairing_it(self):
        import os
        import shutil
        from zeekr_control.events import EventStore
        self.add('valid','vehicle-a','trip_end',1704126600000,distance_km=12)
        for fault in ('file_mode','parent_mode','file_link','parent_link','hardlink','broken_link'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);target=root/'target.sqlite3';shutil.copyfile(self.path,target);target.chmod(0o600)
                path=root/'events.sqlite3'
                if fault in ('file_link','broken_link'):
                    path.symlink_to(target if fault=='file_link' else root/'missing.sqlite3')
                elif fault=='hardlink':os.link(target,path)
                elif fault=='parent_link':
                    private=root/'private';private.mkdir(mode=0o700)
                    shutil.copyfile(target,private/'events.sqlite3');(private/'events.sqlite3').chmod(0o600)
                    alias=root/'alias';alias.symlink_to(private,target_is_directory=True);path=alias/'events.sqlite3'
                else:
                    shutil.copyfile(target,path);path.chmod(0o644 if fault=='file_mode' else 0o600)
                    if fault=='parent_mode':root.chmod(0o755)
                before=target.read_bytes();mode=path.lstat().st_mode;parent_mode=path.parent.stat().st_mode
                store=EventStore(path)
                with self.assertRaises(OSError):store.query('vehicle-a','2024-01-02','trip_end')
                with self.assertRaises(OSError):store.latest('vehicle-a')
                self.assertEqual(target.read_bytes(),before)
                self.assertEqual(path.lstat().st_mode,mode)
                self.assertEqual(path.parent.stat().st_mode,parent_mode)

    def test_latest_pair_uses_one_read_snapshot_during_concurrent_insert(self):
        import sqlite3
        from unittest.mock import patch
        from zeekr_control.events import EventStore,public_event
        self.add('old-trip','vehicle-a','trip_end',1704126600000,created=1)
        self.add('old-charge','vehicle-a','charge_end',1704126600000,created=1)
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('UPDATE monitor_events SET created=created+1')
        def publish(identity,kind,summary):
            if identity=='old-trip':
                with sqlite3.connect(self.path) as writer:
                    writer.execute("INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) SELECT 'new-'||id,vehicle,kind,summary,message,created+100 FROM monitor_events")
            return public_event(identity,kind,summary)
        with patch('zeekr_control.events.public_event',side_effect=publish):
            result=EventStore(self.path).latest('vehicle-a')
        self.assertEqual(result['trip_end']['id'],'old-trip')
        self.assertEqual(result['charge_end']['id'],'old-charge')
        result=EventStore(self.path).latest('vehicle-a')
        self.assertEqual(result['trip_end']['id'],'new-old-trip')
        self.assertEqual(result['charge_end']['id'],'new-old-charge')

    def test_deeply_nested_bad_summary_does_not_hide_valid_history_or_latest(self):
        from zeekr_control.events import EventStore
        self.add('valid','vehicle-a','trip_end',1704126600000,created=1,distance_km=12)
        encoded='{"end_time":1704126660000,"unexpected":'+('['*10000)+'0'+(']'*10000)+'}'
        with self.monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                ('deep','vehicle-a','trip_end',encoded,'PRIVATE',2))
        before=self.path.read_bytes()
        store=EventStore(self.path)
        self.assertEqual([row['id'] for row in store.query('vehicle-a','2024-01-02','trip_end')['events']],['valid'])
        self.assertEqual(store.latest('vehicle-a')['trip_end']['id'],'valid')
        self.assertEqual(self.path.read_bytes(),before)

    def test_huge_charge_detail_scalar_is_unknown_without_breaking_other_values(self):
        from zeekr_control.events import EventStore
        self.add('charge','vehicle-a','charge_end',1704126600000,
            report_v2={'schema_version':2,'start':{'soc':40,'charging_parameters':{'chargeUAct':10**400}},
                       'end':{'soc':80},'metrics':{'sampled_peak_kw':10**400,'average_power_kw':6.5}})
        result=EventStore(self.path).query('vehicle-a','2024-01-02','charge_end')['events'][0]['charging_details']
        self.assertIsNone(result['metrics']['sampled_peak_kw'])
        self.assertEqual(result['metrics']['average_power_kw'],6.5)
        rows={row['key']:row for row in result['start']['parameters']}
        self.assertIsNone(rows['chargeUAct']['value'])

    def test_oversized_summary_is_skipped_consistently_with_bounded_event_reader(self):
        from zeekr_control.events import EventStore
        from zeekr_control.usage_events import MAX_SUMMARY_BYTES
        self.add('valid','vehicle-a','trip_end',1704126600000,created=1,distance_km=12)
        self.add('oversized','vehicle-a','trip_end',1704126660000,created=2,
                 unexpected='x'*MAX_SUMMARY_BYTES)
        before=self.path.read_bytes()
        store=EventStore(self.path)
        self.assertEqual([row['id'] for row in store.query('vehicle-a','2024-01-02','trip_end')['events']],['valid'])
        self.assertEqual(store.latest('vehicle-a')['trip_end']['id'],'valid')
        self.assertEqual(self.path.read_bytes(),before)

    def test_public_event_uses_validated_scalars_and_completeness(self):
        from zeekr_control.events import public_event
        summary={'start_time':1704067200000,'end_time':1704067260000,'duration_seconds':999,
                 'distance_km':-5,'start_soc':80,'end_soc':70,'soc_delta':5,'partial':False,
                 'report_v2':{'partial':True}}
        result=public_event('event','trip_end',summary)
        self.assertTrue(result['partial'])
        self.assertIsNone(result['distance_km'])
        self.assertIsNone(result['duration_seconds'])
        self.assertIsNone(result['soc_delta'])
        self.assertEqual(result['start_soc'],80)
        self.assertEqual(result['end_soc'],70)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tracks.sqlite3'
        self.monitor = Monitor(self.path)

    def add(self, event_id, vehicle, kind, end_time, created=None, **values):
        summary = {'start_time': end_time - 60000, 'end_time': end_time,
                   'duration_seconds': 60, 'partial': False, **values,
                   'start_location': {'latitude': 31}, 'end_address': 'SECRET'}
        with self.monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                       (event_id, vehicle, kind, json.dumps(summary), 'PRIVATE MESSAGE', created or end_time))

    def test_query_filters_vehicle_kind_and_beijing_end_date(self):
        from zeekr_control.events import EventStore
        # 2024-01-01 16:30 UTC = 2024-01-02 00:30 China time.
        self.add('a', 'vehicle-a', 'trip_end', 1704126600000, distance_km=12.3,
                 start_soc=80, end_soc=70, soc_delta=-10)
        self.add('b', 'vehicle-b', 'trip_end', 1704126600000, distance_km=99)
        self.add('c', 'vehicle-a', 'charge_end', 1704126600000)
        result = EventStore(self.path).query('vehicle-a', '2024-01-02', 'trip_end')
        self.assertEqual([item['id'] for item in result['events']], ['a'])
        self.assertEqual(result['events'][0]['distance_km'], 12.3)
        self.assertNotIn('location', str(result))
        self.assertNotIn('SECRET', str(result))
        self.assertNotIn('message', str(result))

    def test_charge_range_includes_both_days_and_paginates(self):
        from zeekr_control.events import EventStore
        # Beijing Jan 1 midnight through Jan 3 midnight.
        for name, stamp in [('before', 1704038399999), ('first', 1704038400000),
                            ('last', 1704211199999), ('after', 1704211200000)]:
            self.add(name, 'vehicle-a', 'charge_end', stamp)
        self.add('other', 'vehicle-b', 'charge_end', 1704038400000)
        store = EventStore(self.path)
        first = store.query('vehicle-a', '2024-01-01', 'charge_end', end_date='2024-01-02', limit=1)
        self.assertEqual([row['id'] for row in first['events']], ['last'])
        second = store.query('vehicle-a', '2024-01-01', 'charge_end', end_date='2024-01-02',
                             limit=1, cursor=first['next_cursor'])
        self.assertEqual([row['id'] for row in second['events']], ['first'])
        self.assertIsNone(second['next_cursor'])
        with self.assertRaises(ValueError):
            store.query('vehicle-a', '2024-01-02', 'charge_end', end_date='2024-01-01')

    def test_cursor_paginates_stably(self):
        from zeekr_control.events import EventStore
        for index in range(3):
            self.add(str(index), 'vehicle-a', 'trip_end', 1704126600000 + index, created=10 + index)
        store = EventStore(self.path)
        first = store.query('vehicle-a', '2024-01-02', 'trip_end', limit=2)
        self.assertEqual([item['id'] for item in first['events']], ['2', '1'])
        second = store.query('vehicle-a', '2024-01-02', 'trip_end', cursor=first['next_cursor'], limit=2)
        self.assertEqual([item['id'] for item in second['events']], ['0'])

    def test_paging_survives_new_insert_and_removed_cursor_row(self):
        from zeekr_control.events import EventStore
        store=EventStore(self.path)
        for kind in ('trip_end','charge_end'):
            with self.subTest(kind=kind):
                prefix=kind+'-'
                for name,created in (('top',30),('boundary',20),('old',10)):
                    self.add(prefix+name,'vehicle-a',kind,1704126600000,created=created)
                first=store.query('vehicle-a','2024-01-02',kind,limit=2)
                self.assertEqual([row['id'] for row in first['events']],
                                 [prefix+'top',prefix+'boundary'])
                self.assertIsNotNone(first['next_cursor'])
                self.add(prefix+'newest','vehicle-a',kind,1704126600000,created=40)
                self.add(prefix+'late','vehicle-a',kind,1704126600000,created=15)
                with self.monitor.tracks.connect() as db:
                    db.execute('DELETE FROM monitor_events WHERE id=?',(prefix+'boundary',))
                second=store.query('vehicle-a','2024-01-02',kind,limit=2,cursor=first['next_cursor'])
                self.assertEqual([row['id'] for row in second['events']],
                                 [prefix+'late',prefix+'old'])
                self.assertIsNone(second['next_cursor'])
                refreshed=store.query('vehicle-a','2024-01-02',kind)
                self.assertEqual([row['id'] for row in refreshed['events']],
                                 [prefix+'newest',prefix+'top',prefix+'late',prefix+'old'])

    def test_fractional_created_times_and_ties_paginate_without_dropping_records(self):
        from zeekr_control.events import EventStore
        for name,created in (('integer',12),('fractional-a',11.5),('fractional-b',11.5),('older',10)):
            self.add(name,'vehicle-a','trip_end',1704126600000,created=created,distance_km=10)
        store=EventStore(self.path);cursor=None;identities=[]
        for index in range(5):
            result=store.query('vehicle-a','2024-01-02','trip_end',limit=1,cursor=cursor)
            identities.extend(row['id'] for row in result['events'])
            cursor=result['next_cursor']
            if cursor is None:break
        self.assertEqual(identities,['integer','fractional-b','fractional-a','older'])
        self.assertIsNone(cursor)

    def test_cursor_outside_sqlite_numeric_range_is_rejected(self):
        from zeekr_control.events import _cursor, _decode
        with self.assertRaisesRegex(ValueError,'游标无效'):_decode(_cursor(10**100,'event'))

    def test_charge_details_projection_does_not_expose_private_report(self):
        from zeekr_control.events import EventStore
        self.add('charge', 'vehicle-a', 'charge_end', 1704126600000,
                 report_v2={'schema_version': 2, 'start': {'soc': 52, 'location': 'SECRET'},
                            'end': {'soc': 80}, 'metrics': {'sampled_peak_kw': 6.5},
                            'render': {'message': 'SECRET'}})
        result = EventStore(self.path).query('vehicle-a', '2024-01-02', 'charge_end')
        self.assertEqual(result['events'][0]['charging_details']['metrics']['sampled_peak_kw'], 6.5)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('report_v2', json.dumps(result))

    def test_latest_returns_each_completed_kind_for_one_vehicle(self):
        from zeekr_control.events import EventStore
        self.add('old-trip', 'vehicle-a', 'trip_end', 1000, created=1, distance_km=1)
        self.add('new-trip', 'vehicle-a', 'trip_end', 2000, created=2, distance_km=2)
        self.add('charge', 'vehicle-a', 'charge_end', 3000, created=3, start_soc=20, end_soc=80)
        self.add('other', 'vehicle-b', 'trip_end', 4000, created=4)
        result = EventStore(self.path).latest('vehicle-a')
        self.assertEqual(result['trip_end']['id'], 'new-trip')
        self.assertEqual(result['charge_end']['id'], 'charge')
        self.assertNotIn('location', str(result))

    def test_latest_ignores_undated_empty_summary_without_hiding_previous_event(self):
        from zeekr_control.events import EventStore
        self.add('valid','vehicle-a','trip_end',1704126600000,created=1,distance_km=12)
        self.add('damaged','vehicle-a','trip_end',1704126660000,created=2)
        for summary in ({},{'end_time':None},{'end_time':10**400}):
            with self.subTest(summary=summary):
                with self.monitor.tracks.connect() as db:
                    db.execute("UPDATE monitor_events SET summary=? WHERE id='damaged'",(json.dumps(summary),))
                result=EventStore(self.path).latest('vehicle-a')
                self.assertEqual(result['trip_end']['id'],'valid')
                self.assertEqual(result['trip_end']['distance_km'],12)
