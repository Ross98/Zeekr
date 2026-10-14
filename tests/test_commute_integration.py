"""Synthetic HTTP and collection integration; no real accounts or senders."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_insights_api as api
from tests.test_monitor import BASE, sample
from zeekr_control.commute_tags import CommuteTags
from zeekr_control.monitor_runtime import Runner
from zeekr_control.personal_store import account_scope
from zeekr_control.storage import save


class CommuteApiTests(unittest.TestCase):
    setUp = api.InsightsApiTests.setUp
    cleanup_server = api.InsightsApiTests.cleanup_server
    get = api.InsightsApiTests.get
    post_ledger = api.InsightsApiTests.post_ledger

    def test_independent_settings_endpoint_is_private_and_does_not_scan_trips(self):
        with patch.object(self.app.trip_tags, 'query', side_effect=AssertionError('Trips must not be scanned')):
            code, result = self.get('/api/insights/commute-rule')
        self.assertEqual(code, 200)
        self.assertEqual(result['commute_rule']['revision'], 0)
        self.assertIn('context', result)
        self.assertFalse(self.app.personal_store.path.exists())
        save(self.path, {'accessToken': 'OTHER-ACCOUNT'})
        self.assertEqual(self.get('/api/insights/commute-rule')[0], 400)

    def test_preview_apply_requires_context_request_key_and_matching_token(self):
        context = self.get('/api/state')[1]['insights_context']
        rule = dict(context=context, action='commute-save', revision=0,
                    home=dict(latitude=31.2, longitude=121.4, radius_m=300),
                    work=dict(latitude=31.21, longitude=121.41, radius_m=300))
        self.assertEqual(self.post_ledger(rule, route='/api/insights/trip-tags')[0], 200)
        payload = dict(context=context, action='commute-preview', revision=1, date='2026-09-20')
        self.assertEqual(self.post_ledger(payload, {'X-Request-Key': ''}, '/api/insights/trip-tags')[0], 403)
        self.assertEqual(self.post_ledger(dict(payload, context='old'), route='/api/insights/trip-tags')[0], 400)
        code, preview = self.post_ledger(payload, route='/api/insights/trip-tags')
        self.assertEqual(code, 200)
        self.assertFalse(preview['applied'])
        self.assertEqual(preview['context'], context)
        self.assertEqual(self.post_ledger(dict(payload, action='commute-apply', token='invalid'), route='/api/insights/trip-tags')[0], 400)
        self.assertEqual(self.post_ledger(dict(payload, action='commute-apply', token=preview['token']), route='/api/insights/trip-tags')[0], 200)


class CommuteCollectionTests(unittest.TestCase):
    def test_runner_tags_finished_trip_without_month_read_or_extra_vehicle_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'private'
            session = {'accessToken': 'synthetic', 'userId': 'synthetic-owner'}
            save(root / 'session.json', session)
            class Client:
                calls = 0
                def __init__(self, session): pass
                def vehicles(self): return [{'vin': 'L6T79X2Z0NP000001'}]
                def status(self, vin):
                    Client.calls += 1
                    return sample(0)
            runner = Runner(root / 'session.json', client_factory=Client, sender=lambda message: self.fail('No notifications'))
            self.addCleanup(runner.insight_worker.close)
            car = hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest()
            commute = CommuteTags(runner.reminders.store, root / 'tracks.sqlite3')
            with patch('zeekr_control.commute_tags.time.time', return_value=(BASE-3600000)/1000):
                commute.update(account_scope(session), car, dict(action='commute-save', revision=0,
                    home=dict(latitude=31.2, longitude=121.4, radius_m=300),
                    work=dict(latitude=31.21, longitude=121.41, radius_m=300)))
            with runner.monitor.tracks.connect() as db:
                summary = dict(start_time=BASE-1200000, end_time=BASE-1000, duration_seconds=1199,
                    distance_km=20, partial=False)
                db.execute('INSERT INTO monitor_events(id,vehicle,kind,summary,message,created) VALUES(?,?,?,?,?,?)',
                    ('synthetic-ended', car, 'trip_end', json.dumps(summary), '', BASE-1000))
                for timestamp, point in ((BASE-1190000, (31.2, 121.4)), (BASE-2000, (31.21, 121.41))):
                    location = dict(latitude=point[0], longitude=point[1], trusted=True, plottable=True, coordinate_system='WGS84（社区解释）')
                    db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES(?,?,?,?,?,?)',
                        (car, str(timestamp), timestamp, timestamp, 30, json.dumps(location)))
            runner.tick(BASE)
            self.assertEqual(Client.calls, 1)
            with runner.reminders.store.connect() as db:
                result = db.execute('SELECT owner,result FROM commute_decisions').fetchone()
            self.assertEqual(result, (account_scope(session), 'matched'))
