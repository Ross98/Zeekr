"""Preview expiry uses real SQLite lock contention and synthetic records only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from itertools import product
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from zeekr_control.monitor import Monitor
from zeekr_control.trip_management import TripRecordManager
from zeekr_control.charge_management import ChargeRecordManager


class RecordPreviewExpiryTests(unittest.TestCase):
    @contextmanager
    def fixture(self,kind,action='trash'):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'tracks.sqlite3';monitor=Monitor(path);now=[1000.0]
            summary=dict(start_time=1704067200000,end_time=1704067800000,duration_seconds=600,
                         distance_km=10,start_soc=80,end_soc=70,soc_delta=-10,partial=False)
            if kind=='charge_end':summary.update(distance_km=0,start_soc=40,end_soc=60,soc_delta=20)
            with monitor.tracks.connect() as db:
                db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                           ('record','car',kind,json.dumps(summary),'synthetic',1704067800000))
            factory=TripRecordManager if kind=='trip_end' else ChargeRecordManager
            manager=factory(path,clock=lambda:now[0])
            plan=manager.preview('car','trash',['record'],0,'owner')
            if action=='restore':
                manager.execute(plan['token'],'owner')
                plan=manager.preview('car','restore',['record'],1,'owner')
            yield manager,path,now,plan

    def test_preview_expiring_while_waiting_for_write_lock_cannot_commit(self):
        connect=sqlite3.connect
        for kind,action in product(('trip_end','charge_end'),('trash','restore')):
            with self.subTest(kind=kind,action=action),self.fixture(kind,action) as (manager,path,now,plan):
                before=path.read_bytes();now[0]=1299.0;attempting=threading.Event()
                blocker=connect(path);blocker.execute('BEGIN IMMEDIATE')
                def tracked_connect(*args,**kwargs):
                    db=connect(*args,**kwargs)
                    db.set_trace_callback(lambda sql:attempting.set() if sql=='BEGIN IMMEDIATE' else None)
                    return db
                try:
                    with ThreadPoolExecutor(max_workers=1) as pool,patch('sqlite3.connect',side_effect=tracked_connect):
                        future=pool.submit(manager.execute,plan['token'],'owner')
                        try:
                            self.assertTrue(attempting.wait(2),'execute did not reach SQLite lock')
                            now[0]=1300.0
                        finally:blocker.rollback()
                        with self.assertRaisesRegex(ValueError,'预览.*过期'):
                            future.result(timeout=3)
                finally:blocker.close()
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(manager.revision('car'),plan['revision'])

    def test_preview_expiring_during_final_guard_rolls_back_all_changes(self):
        for kind,action in product(('trip_end','charge_end'),('trash','restore')):
            with self.subTest(kind=kind,action=action),self.fixture(kind,action) as (manager,path,now,plan):
                before=path.read_bytes();now[0]=1299.0
                def guard():now[0]=1300.0
                with self.assertRaisesRegex(ValueError,'预览.*过期'):
                    manager.execute(plan['token'],'owner',guard=guard)
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(manager.revision('car'),plan['revision'])

    def test_preview_still_valid_immediately_before_expiry_can_commit(self):
        for kind,action in product(('trip_end','charge_end'),('trash','restore')):
            with self.subTest(kind=kind,action=action),self.fixture(kind,action) as (manager,path,now,plan):
                now[0]=1299.0
                def guard():now[0]=1299.999
                result=manager.execute(plan['token'],'owner',guard=guard)
                self.assertEqual(result['revision'],plan['revision']+1)
                self.assertEqual(manager.revision('car'),plan['revision']+1)
