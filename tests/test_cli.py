"""Offline tests: identifiers and observations are synthetic, never owner records."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zeekr_control.cli import main
from zeekr_control.storage import save


class CliTests(unittest.TestCase):
    def test_missing_session_exit_and_no_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                result = main(['vehicles'], Path(directory) / 'session.json')
            self.assertEqual(result, 1)
            self.assertNotIn('Traceback', output.getvalue())
            self.assertIn('尚未登录', output.getvalue())

    def test_json_output_redacts_credentials_and_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            save(path, {'accessToken': 'secret', 'userId': 'u', 'clientId': 'c'})
            output = io.StringIO()
            with patch('zeekr_control.client.transport', return_value={}), \
                 patch('zeekr_control.cli.Client.vehicles', return_value=[{
                     'vin': 'L1234567890123456', 'accessToken': 'TOKEN-SECRET',
                     'nested': {'mobile': '13800000000', 'longitude': 123.456},
                 }]), contextlib.redirect_stdout(output):
                self.assertEqual(main(['vehicles'], path), 0)
            text = output.getvalue()
            for private in ('TOKEN-SECRET', 'L1234567890123456', '13800000000', '123.456'):
                self.assertNotIn(private, text)

    def test_full_output_still_hides_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            save(path, {'accessToken': 'secret', 'userId': 'u'})
            output = io.StringIO()
            with patch('zeekr_control.cli.Client.vehicles', return_value=[{
                'vin': 'L1234567890123456', 'jwtToken': 'TOKEN-SECRET'}]), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(main(['vehicles', '--full'], path), 0)
            self.assertIn('L1234567890123456', output.getvalue())
            self.assertNotIn('TOKEN-SECRET', output.getvalue())

    def test_noninteractive_login_never_requests_sms(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('sys.stdin.isatty', return_value=False), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['login'], Path(directory) / 'session.json'), 1)

    def test_single_shared_vehicle_status_uses_its_vin(self):
        from zeekr_control.client import Client
        from test_client import Transport, ok
        wire = Transport(ok({'list': [{'vehicle': {'vin': 'L1234567890123456'}}]}),
                         ok({'vehicleStatus': {'electricVehicleStatus': {'chargeLevel': 0}}}))
        client = Client({'accessToken': 'a', 'userId': 'u', 'clientId': 'c'}, wire)
        with tempfile.TemporaryDirectory() as directory, \
             patch('zeekr_control.cli.Client', return_value=client), \
             contextlib.redirect_stdout(io.StringIO()) as output, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['status', '--json'], Path(directory) / 'session.json'), 0)
        self.assertIn('"chargeLevel": 0', output.getvalue())
        self.assertIn('/status/L1234567890123456?', wire.calls[1][1])

    def test_redaction_preserves_driving_sections(self):
        from zeekr_control.cli import redact
        data = {'drivingSafetyStatus': {'centralLockingStatus': '1', 'vin': 'private'},
                'drivingBehaviourStatus': {'speed': '0'}}
        result = redact(data)
        self.assertEqual(result['drivingSafetyStatus']['centralLockingStatus'], '1')
        self.assertEqual(result['drivingSafetyStatus']['vin'], '[hidden]')
        self.assertEqual(result['drivingBehaviourStatus'], {'speed': '0'})

    def test_vehicle_hardware_identifiers_hidden_recursively(self):
        from zeekr_control.cli import redact
        fields = ('iccid', 'iccId', 'imsi', 'imei', 'msisdn', 'temId', 'ihuId', 'id',
                  'loginUid', 'serialNumber', 'matCode', 'engineNo', 'deviceId')
        result = redact({'nested': [{key: 'private' for key in fields}]})
        self.assertEqual(set(result['nested'][0].values()), {'[hidden]'})
        self.assertEqual(redact({'iccid': 'private'}, full=True)['iccid'], 'private')
