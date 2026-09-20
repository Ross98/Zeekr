"""Owner-confirmed AC activity and conservative counterexamples; synthetic only."""
import tempfile
import unittest
from pathlib import Path

from test_monitor import BASE, sample
from zeekr_control.monitor import Monitor
from zeekr_control.vehicle_state import decode


def ac_sample(seconds=0, **changes):
    raw = sample(seconds, speed=0, engine='engine_off', ready=0, soc=50,
                 code=0, charger=2, plug=3, voltage=220, current=16)
    raw['basicVehicleStatus']['speedValidity'] = 'false'
    electric = raw['additionalVehicleStatus']['electricVehicleStatus']
    electric.update(chargeLidAcStatus=1, chargeLidDcAcStatus=2,
                    dcChargeSts=0, dcChargePileUAct=360, dcChargePileIAct=0,
                    bookChargeSts=0, timeToFullyCharged=120)
    electric.update(changes)
    return raw


class AcChargingTests(unittest.TestCase):
    def test_confirmed_ac_combination_ignores_residual_dc_voltage(self):
        point = decode(ac_sample())
        self.assertIs(point['charging'], True)
        self.assertEqual(point['charging_mode'], 'ac')
        self.assertEqual(point['charging_phase'], 'active')
        self.assertIsNone(point['speed'])

    def test_confirmed_ac_combination_accepts_numeric_strings(self):
        raw = ac_sample()
        electric = raw['additionalVehicleStatus']['electricVehicleStatus']
        electric.update({key: str(value) for key, value in electric.items()})
        point = decode(raw)
        self.assertIs(point['charging'], True)
        self.assertEqual(point['charging_mode'], 'ac')

    def test_each_required_ac_evidence_must_match(self):
        counterexamples = {
            'chargeLidAcStatus': (None, 2, 99),
            'chargeLidDcAcStatus': (None, 1, 99),
            'chargeSts': (None, 1, 99),
            'chargerState': (None, 0, 24, 99),
            'statusOfChargerConnection': (None, 0, 1, 99),
            'dcChargeSts': (None, 10, 12),
            'dcChargePileIAct': (None, -1, 1),
            'chargeUAct': (None, 0, -1, 1501),
            'chargeIAct': (None, 0, -1, 2001),
        }
        for key, values in counterexamples.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    point = decode(ac_sample(**{key: value}))
                    self.assertIsNone(point['charging'])
                    self.assertIsNone(point['charging_mode'])

    def test_invalid_electrical_values_do_not_enable_ac_activity(self):
        for key in ('chargeUAct', 'chargeIAct', 'dcChargeSts',
                    'dcChargePileUAct', 'dcChargePileIAct'):
            for value in (True, False, '', 'bad', float('nan'), float('inf'), [], {}):
                with self.subTest(key=key, value=value):
                    self.assertIsNone(decode(ac_sample(**{key: value}))['charging'])

    def test_drive_ready_or_valid_motion_conflicts_with_ac_activity(self):
        for changes in ({'speed': 30, 'speedValidity': True},
                        {'engineStatus': 'engine_on'}, {'engineStatus': 'engine_running'}):
            with self.subTest(changes=changes):
                raw = ac_sample()
                raw['basicVehicleStatus'].update(changes)
                self.assertIsNone(decode(raw)['charging'])
                self.assertIsNone(decode(raw)['charging_mode'])
        self.assertIsNone(decode(ac_sample(ptReady=1))['charging'])

    def test_generic_idle_or_stop_cannot_override_ac_current_or_invalid_fields(self):
        for code in (0, 'stopped', 'finished', 'complete'):
            for changes in ({'chargeIAct': 16}, {'chargeIAct': -1},
                            {'chargeIAct': 'bad'}, {'chargeIAct': 0, 'chargeUAct': 'bad'}):
                with self.subTest(code=code, changes=changes):
                    raw = ac_sample(chargeSts=code, chargerState=0,
                                    statusOfChargerConnection=0, **changes)
                    self.assertIsNone(decode(raw)['charging'])

    def test_zero_current_is_unknown_and_does_not_end_or_restart_ac_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            monitor = Monitor(Path(temporary) / 'private' / 'tracks.sqlite3')
            for seconds, current in ((0, 16), (60, 0), (120, 16)):
                monitor.observe('synthetic-ac', ac_sample(seconds, chargeIAct=current),
                                BASE + seconds * 1000)
            self.assertEqual([event['kind'] for event in monitor.events()], ['charge_start'])
            self.assertIsNotNone(monitor.status('synthetic-ac')['charge'])
            self.assertIsNone(decode(ac_sample(chargeIAct=0))['charging'])

    def test_owner_confirmed_ac_finished_combination_is_stopped(self):
        raw = ac_sample(chargerState=4, statusOfChargerConnection=1,
                        chargeUAct=0, chargeIAct=0)
        point = decode(raw)
        self.assertIs(point['charging'], False)
        self.assertEqual(point['charging_phase'], 'stopped')
        self.assertIsNone(point['charging_mode'])

    def test_each_required_ac_finished_evidence_must_match(self):
        finished = dict(chargerState=4, statusOfChargerConnection=1,
                        chargeUAct=0, chargeIAct=0)
        counterexamples = {
            'chargeLidAcStatus': (None, 2, 99),
            'chargeLidDcAcStatus': (None, 1, 99),
            'chargeSts': (None, 1, 99),
            'chargerState': (None, 0, 2, 99),
            'statusOfChargerConnection': (None, 0, 3, 99),
            'dcChargeSts': (None, 10, 12),
            'dcChargePileIAct': (None, -1, 1),
            'chargeUAct': (None, -1, 1, 1501),
            'chargeIAct': (None, -1, 1, 2001),
        }
        for key, values in counterexamples.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    raw = ac_sample(**dict(finished, **{key: value}))
                    self.assertIsNone(decode(raw)['charging'])

    def test_confirmed_ac_finished_state_ends_session_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'private' / 'tracks.sqlite3'
            monitor = Monitor(path)
            monitor.observe('synthetic-ac', ac_sample(0, chargeLevel=53), BASE)
            monitor.observe('synthetic-ac', ac_sample(60, chargeLevel=90,
                chargerState=4, statusOfChargerConnection=1,
                chargeUAct=0, chargeIAct=0), BASE + 60000)
            self.assertEqual([event['kind'] for event in monitor.events()],
                             ['charge_start', 'charge_end'])
            ended = monitor.events()[1]['summary']
            self.assertEqual(ended['start_soc'], 53)
            self.assertEqual(ended['end_soc'], 90)
            self.assertIsNone(monitor.status('synthetic-ac')['charge'])

            monitor = Monitor(path)
            monitor.observe('synthetic-ac', ac_sample(120, chargeLevel=90,
                chargerState=4, statusOfChargerConnection=1,
                chargeUAct=0, chargeIAct=0), BASE + 120000)
            self.assertEqual([event['kind'] for event in monitor.events()],
                             ['charge_start', 'charge_end'])

    def test_upgrade_reinterprets_same_cached_ac_finished_state_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'private' / 'tracks.sqlite3'
            monitor = Monitor(path)
            monitor.observe('synthetic-ac', ac_sample(0, chargeLevel=53), BASE)
            monitor.observe('synthetic-ac', ac_sample(60, chargeLevel=90,
                chargeIAct=0), BASE + 60000)
            self.assertEqual([event['kind'] for event in monitor.events()],
                             ['charge_start'])

            monitor = Monitor(path)
            finished = ac_sample(60, chargeLevel=90, chargerState=4,
                                 statusOfChargerConnection=1,
                                 chargeUAct=0, chargeIAct=0)
            monitor.observe('synthetic-ac', finished, BASE + 600000)
            monitor.observe('synthetic-ac', finished, BASE + 660000)
            self.assertEqual([event['kind'] for event in monitor.events()],
                             ['charge_start', 'charge_end'])

    def test_ac_metadata_alone_never_claims_activity_or_stop(self):
        for changes in ({'chargeUAct': None, 'chargeIAct': None},
                        {'chargeUAct': 220, 'chargeIAct': 0},
                        {'bookChargeSts': 1, 'chargeIAct': 0}):
            with self.subTest(changes=changes):
                point = decode(ac_sample(**changes))
                self.assertIsNone(point['charging'])
                self.assertEqual(point['charging_phase'], 'unknown')

    def test_verified_dc_stop_remains_supported(self):
        raw = sample(0, charger=26, dc_lid=1)
        raw['additionalVehicleStatus']['electricVehicleStatus'].update(
            dcChargeSts=10, dcChargePileUAct=400, dcChargePileIAct=0)
        point = decode(raw)
        self.assertIs(point['charging'], False)
        self.assertEqual(point['charging_phase'], 'stopped')


if __name__ == '__main__':
    unittest.main()
