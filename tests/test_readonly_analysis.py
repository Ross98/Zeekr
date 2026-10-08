"""Slow historical analysis must not serialize the live state read."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from zeekr_control.storage import save
from zeekr_control.snapshots import session_scope
from zeekr_control.web import App


class ReadonlyAnalysisTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'private' / 'session.json'
        self.session = {'userId': 'synthetic-owner', 'accessToken': 'SYNTHETIC'}
        save(self.path, self.session)
        self.app = App(self.path)
        self.addCleanup(self.app.close)
        self.app.snapshot_store.publish(session_scope(self.session), 'synthetic-car',
            {'updateTime': 1791388800000}, 1791388800000)
        save(self.path.parent / 'monitor-binding.json', {'vehicle_key': 'synthetic-car'})
        self.app.state()

    def test_state_completes_while_calendar_is_still_computing(self):
        entered, release, state_done = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def slow(*args, **kwargs):
            entered.set()
            if not release.wait(5): raise AssertionError('analysis release timed out')
            return {}
        def analysis():
            try: self.app.insights('calendar', '2026-10-08')
            except Exception as error: errors.append(error)
        def state():
            self.app.state(); state_done.set()
        with patch.object(self.app.usage_calendar, 'query', side_effect=slow):
            worker = threading.Thread(target=analysis); worker.start()
            self.assertTrue(entered.wait(2))
            reader = threading.Thread(target=state); reader.start()
            try: self.assertTrue(state_done.wait(1), 'state waits for historical analysis lock')
            finally: release.set(); worker.join(3); reader.join(3)
        self.assertEqual(errors, [])

    def test_account_change_during_analysis_discards_result(self):
        def change(*args, **kwargs):
            save(self.path, {'userId': 'other', 'accessToken': 'OTHER'})
            return {'private_result': 'old-account'}
        with patch.object(self.app.usage_calendar, 'query', side_effect=change):
            with self.assertRaisesRegex(ValueError, '切换'):
                self.app.insights('calendar', '2026-10-08')

    def test_sampling_policy_comes_from_runtime_constants(self):
        from zeekr_control.sampling import DEFAULT_INTERVAL, MIN_INTERVAL, MAX_INTERVAL
        policy = self.app.state()['recording']['policy']
        self.assertEqual((policy['default_interval'], policy['min_interval'], policy['max_interval']),
                         (DEFAULT_INTERVAL, MIN_INTERVAL, MAX_INTERVAL))
        self.assertEqual(policy['parking_mode'], 'same_as_normal')

    def test_charging_query_does_not_own_application_lock(self):
        def read(*args):
            acquired = []
            def state():
                with self.app.lock: acquired.append(True)
            thread = threading.Thread(target=state)
            thread.start(); thread.join(1)
            self.assertEqual(acquired, [True], 'charging read holds application lock')
            return {}
        with patch.object(self.app.charging_analytics, 'series', side_effect=read):
            self.app.charging_series('current', 'power-soc')

    def test_query_retries_once_then_rejects_changed_data(self):
        from zeekr_control.web import AnalysisChanged
        with patch.object(self.app, '_analysis_revision', side_effect=[1, 2, 2, 3]), \
             patch.object(self.app.usage_calendar, 'query', return_value={}) as query:
            with self.assertRaises(AnalysisChanged):
                self.app.insights('calendar', '2026-10-08')
            self.assertEqual(query.call_count, 2)

    def test_query_capacity_is_bounded_and_returns_after_error(self):
        from zeekr_control.web import AnalysisBusy
        for _ in range(2): self.app.analysis_slots.acquire()
        try:
            with self.assertRaises(AnalysisBusy): self.app.insights('calendar', '2026-10-08')
        finally:
            for _ in range(2): self.app.analysis_slots.release()
        with patch.object(self.app.usage_calendar, 'query', side_effect=ValueError):
            with self.assertRaises(ValueError): self.app.insights('calendar', '2026-10-08')
        for _ in range(2): self.assertTrue(self.app.analysis_slots.acquire(blocking=False))
        for _ in range(2): self.app.analysis_slots.release()

    def test_commute_place_change_retries_analysis(self):
        from zeekr_control.commute_tags import CommuteTags
        context=self.app._read_context()
        rules=CommuteTags(self.app.personal_store,self.app.database_path)
        calls=[]
        def read(*args,**kwargs):
            before=rules.rule(context.owner,context.vehicle)['revision']
            calls.append(before)
            if len(calls)==1:
                rules.update(context.owner,context.vehicle,dict(action='commute-save',revision=0,
                    home=dict(latitude=31.2,longitude=121.4,radius_m=100),
                    work=dict(latitude=31.3,longitude=121.5,radius_m=100)))
            return {'rule':before}
        with patch.object(self.app.usage_calendar,'query',side_effect=read):
            result=self.app.insights('calendar','2026-10-08')
        self.assertEqual(calls,[0,1])
        self.assertEqual(result['rule'],1)
