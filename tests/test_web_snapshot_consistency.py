"""Cached Web state must follow the accepted snapshot and its session scope."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zeekr_control.client import ApiError
from zeekr_control.snapshots import session_scope
from zeekr_control.storage import load, save
from zeekr_control.web import App
from test_web_server import FakeClient


class WebSnapshotConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'private' / 'session.json'
        self.session = {'accessToken': 'SYNTHETIC-A', 'userId': 'account-a'}
        save(self.path, self.session)
        self.app = App(self.path, client_factory=FakeClient)
        self.addCleanup(self.app.close)
        self.raw = FakeClient({}).status('synthetic')
        self.key = hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest()
        save(self.path.parent / 'monitor-binding.json', {'vehicle_key': self.key})

    def refresh(self, raw):
        with patch.object(FakeClient, 'status', return_value=raw):
            return self.app.refresh(1)

    def test_older_and_missing_time_responses_keep_accepted_state_and_location(self):
        original = self.refresh(self.raw)
        location = self.app.location()
        for timestamp in (self.raw['updateTime'] - 60000, None):
            with self.subTest(timestamp=timestamp):
                incoming = copy.deepcopy(self.raw)
                incoming['updateTime'] = timestamp
                incoming['additionalVehicleStatus']['electricVehicleStatus']['chargeLevel'] = 20
                incoming['position']['latitude'] = 115200000
                refreshed = self.refresh(incoming)
                for result in (refreshed, self.app.state()):
                    self.assertEqual(result['model'], original['model'])
                    self.assertEqual(result['read_time'], original['read_time'])
                    self.assertEqual(result['snapshot_revision'], original['snapshot_revision'])
                self.assertEqual(self.app.location(), location)

    def test_newer_background_snapshot_wins_over_manual_response(self):
        self.refresh(self.raw)
        newer = copy.deepcopy(self.raw)
        newer['updateTime'] += 60000
        newer['additionalVehicleStatus']['electricVehicleStatus']['chargeLevel'] = 80
        self.app.snapshot_store.publish(session_scope(self.session), self.key, newer, newer['updateTime'])
        result = self.refresh(self.raw)
        self.assertEqual(result['model']['metrics']['battery'], '80%')
        self.assertEqual(result['model']['updated_time'], newer['updateTime'])
        self.assertEqual(result['snapshot_revision'], 2)

    def test_same_time_revision_still_updates(self):
        original = self.refresh(self.raw)
        revised = copy.deepcopy(self.raw)
        revised['additionalVehicleStatus']['electricVehicleStatus']['chargeLevel'] = 80
        result = self.refresh(revised)
        self.assertEqual(result['model']['metrics']['battery'], '80%')
        self.assertEqual(result['snapshot_revision'], original['snapshot_revision'] + 1)

    def test_manual_refresh_retains_safe_vehicle_metadata(self):
        vehicle = dict(FakeClient({}).vehicles()[0], colorName='合成蓝')
        with patch.object(FakeClient, 'vehicles', return_value=[vehicle]):
            result = self.refresh(self.raw)
        color = next(field for field in result['model']['fields']
                     if field['path'] == 'vehicleMetadata.colorName')
        self.assertEqual(color['value'], '合成蓝')

    def test_failed_snapshot_write_keeps_previous_vehicle_selection(self):
        original = self.refresh(self.raw)
        with patch.object(self.app.snapshot_store, 'publish', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.app.refresh(2)
        current = self.app.state()
        self.assertEqual(current['vehicle'], original['vehicle'])
        self.assertEqual(current['field_reviews']['vehicle'], original['field_reviews']['vehicle'])
        self.assertEqual(current['profile'], original['profile'])
        self.assertEqual(current['model'], original['model'])

    def test_changed_session_clears_cached_model_profile_and_selection(self):
        self.refresh(self.raw)
        self.app.history_selections['old-selection'] = {'private': 'old-session'}
        save(self.path, {'accessToken': 'SYNTHETIC-B', 'userId': 'account-b'})
        result = self.app.state()
        for name in ('model', 'profile', 'snapshot_revision', 'read_time', 'refresh_result'):
            self.assertIsNone(result[name], name)
        self.assertEqual(result['vehicles'], [])
        self.assertIsNone(result['field_reviews']['vehicle'])
        self.assertEqual(self.app.history_selections, {})
        self.assertIsNone(self.app.location().get('latitude'))
        self.assertEqual(self.app.vehicle_parameters()['counts']['missing'], 217)

    def test_new_session_same_revision_restores_its_own_snapshot(self):
        original = self.refresh(self.raw)
        session = {'accessToken': 'SYNTHETIC-B', 'userId': 'account-b'}
        newer = copy.deepcopy(self.raw)
        newer['updateTime'] += 60000
        newer['additionalVehicleStatus']['electricVehicleStatus']['chargeLevel'] = 80
        self.app.snapshot_store.publish(session_scope(session), self.key, newer, newer['updateTime'])
        save(self.path, session)
        result = self.app.state()
        self.assertEqual(result['snapshot_revision'], original['snapshot_revision'])
        self.assertEqual(result['model']['metrics']['battery'], '80%')
        self.assertEqual(result['read_time'], newer['updateTime'])

    def test_logout_and_unreadable_session_clear_cached_state(self):
        for unreadable in (False, True):
            with self.subTest(unreadable=unreadable):
                save(self.path, self.session)
                self.refresh(self.raw)
                if unreadable:
                    self.path.write_text('invalid json')
                else:
                    self.path.unlink()
                result = self.app.state()
                self.assertFalse(result['authenticated'])
                self.assertIsNone(result['model'])
                self.assertIsNone(result['profile'])
                self.assertIsNone(result['read_time'])

    def test_location_request_detects_session_change_without_state_poll(self):
        self.refresh(self.raw)
        save(self.path, {'accessToken': 'SYNTHETIC-B', 'userId': 'account-b'})
        self.assertIsNone(self.app.location().get('latitude'))

    def test_inflight_response_cannot_be_published_under_replacement_session(self):
        self.refresh(self.raw)
        replacement = {'accessToken': 'SYNTHETIC-B', 'userId': 'account-b'}

        def change_session(vin):
            save(self.path, replacement)
            return self.raw

        with patch.object(FakeClient, 'status', side_effect=change_session):
            with self.assertRaises(ApiError):
                self.app.refresh(1)
        self.assertIsNone(self.app.snapshot_store.read(session_scope(replacement), self.key))
        self.assertIsNone(self.app.state()['model'])
        self.assertEqual(load(self.path), replacement)
