"""Manual review API uses synthetic vehicles and temporary persistent storage."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from zeekr_control.web import App, make_server
from zeekr_control.web_model import build_model

PATH = 'additionalVehicleStatus.climateStatus.steerWhlHeatingSts'


class FieldReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = App(Path(self.temp.name) / 'session.json')
        self.app.vehicle_key = 'synthetic-vehicle-a'
        self.app.model = build_model({'updateTime': 1704067200000,
            'additionalVehicleStatus': {'climateStatus': {'steerWhlHeatingSts': 0}}})
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app.close()
        self.temp.cleanup()

    def request(self, data=None, authorized=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        headers = {'Content-Type': 'application/json'}
        if authorized:
            headers.update({'Origin': f'http://127.0.0.1:{self.server.server_port}',
                            'X-Request-Key': self.app.request_key})
        conn.request('GET' if data is None else 'POST', '/api/state' if data is None else '/api/field-reviews',
                     None if data is None else json.dumps(data), headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    def payload(self, **changes):
        data = {'vehicle': 'synthetic-vehicle-a', 'revision': 0, 'action': 'save',
                'path': PATH, 'scope': 'value', 'raw': '0', 'status': 'confirmed',
                'meaning': '关闭', 'unit': '', 'conversion': '', 'observation': '车机显示关闭',
                'scene': '停车', 'note': '', 'observed_at': 1704067200000}
        data.update(changes)
        return data

    def test_save_survives_new_app_and_keeps_system_evidence(self):
        before = self.app.model
        code, result = self.request(self.payload())
        self.assertEqual(code, 200)
        self.assertEqual(result['records'][0]['meaning'], '关闭')
        other = App(self.app.session_path)
        other.vehicle_key = self.app.vehicle_key
        try:
            self.assertEqual(other.state()['field_reviews']['records'], result['records'])
        finally:
            other.close()
        self.assertEqual(self.app.model, before)
        self.assertEqual(self.request()[1]['field_reviews']['revision'], 1)

    def test_vehicle_isolation_and_reject_stale_vehicle(self):
        self.assertEqual(self.request(self.payload())[0], 200)
        self.app.vehicle_key = 'synthetic-vehicle-b'
        self.assertEqual(self.request()[1]['field_reviews']['records'], [])
        self.assertEqual(self.request(self.payload(revision=1))[0], 400)
        self.assertEqual(self.request(self.payload(vehicle='synthetic-vehicle-b'))[0], 200)

    def test_values_are_independent_and_delete_only_selected_mapping(self):
        self.assertEqual(self.request(self.payload())[0], 200)
        code, result = self.request(self.payload(revision=1, raw='1', meaning='开启'))
        self.assertEqual(code, 200)
        self.assertEqual({r['raw'] for r in result['records']}, {'0', '1'})
        code, result = self.request(self.payload(revision=2, action='delete'))
        self.assertEqual(code, 200)
        self.assertEqual([r['raw'] for r in result['records']], ['1'])

    def test_concurrent_edit_does_not_overwrite(self):
        self.assertEqual(self.request(self.payload())[0], 200)
        code, result = self.request(self.payload(meaning='错误覆盖'))
        self.assertEqual(code, 400)
        self.assertIn('更新', result['error'])
        self.assertEqual(self.request()[1]['field_reviews']['records'][0]['meaning'], '关闭')

    def test_validation_and_request_protection(self):
        for changes in ({'path': 'position.latitude'}, {'meaning': ''}, {'status': 'bogus'},
                        {'raw': '未知'}, {'scope': 'bogus'}, {'observed_at': True},
                        {'note': 'x' * 1201}, {'revision': True}):
            with self.subTest(changes=changes):
                self.assertEqual(self.request(self.payload(**changes))[0], 400)
        self.assertEqual(self.request(self.payload(), authorized=False)[0], 403)

    def test_full_length_chinese_notes_can_be_saved(self):
        code, result = self.request(self.payload(note='核实' * 600, observation='观察' * 300))
        self.assertEqual(code, 200)
        self.assertEqual(result['records'][0]['note'], '核实' * 600)

    def test_missing_vehicle_and_invalid_types_are_rejected(self):
        for changes in ({'path': []}, {'scope': []}, {'status': []}, {'raw': 0},
                        {'observed_at': -1}, {'scope': 'field', 'raw': 'open'}):
            self.assertEqual(self.request(self.payload(**changes))[0], 400)
        self.app.vehicle_key = None
        self.assertEqual(self.request(self.payload())[0], 400)

    def test_numeric_field_rule_and_not_applicable(self):
        code, result = self.request(self.payload(scope='field', meaning='加热档位', unit='档', conversion='原值'))
        self.assertEqual(code, 200)
        self.assertEqual(result['records'][0]['scope'], 'field')
        code, result = self.request(self.payload(scope='field', revision=1, status='na', meaning='', note='本车不适用'))
        self.assertEqual(code, 200)
        self.assertEqual(len(result['records']), 1)
        self.assertEqual(result['records'][0]['status'], 'na')


if __name__ == '__main__':
    unittest.main()
