"""End-to-end usage scenarios using synthetic observations and private temp DBs."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_monitor import BASE, sample
from zeekr_control.monitor import Monitor


class UsageScenarioTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.monitor = Monitor(Path(temporary.name) / 'private' / 'tracks.sqlite3')

    def observe(self, seconds, observed_seconds=None, **values):
        raw = sample(seconds, **values)
        observed = seconds if observed_seconds is None else observed_seconds
        return self.monitor.observe('synthetic-vehicle', raw, BASE + observed * 1000,
                                    profile={'battery_capacity_kwh': 86, 'range_km': 700,
                                             'range_standard': 'CLTC'})

    def charge(self, seconds, soc=50, current=100, km=100):
        raw = sample(seconds, soc=soc, km=km, charger=24, dc_lid=1)
        raw['additionalVehicleStatus']['electricVehicleStatus'].update(
            dcChargeSts=12, dcChargePileUAct=400, dcChargePileIAct=current)
        return self.monitor.observe('synthetic-vehicle', raw, BASE + seconds * 1000,
                                    profile={'battery_capacity_kwh': 86, 'range_km': 700,
                                             'range_standard': 'CLTC'})

    def events(self, kind):
        return [event for event in self.monitor.events() if event['kind'] == kind]

    def test_odometer_motion_cancels_parking_when_sampled_speed_is_zero(self):
        self.observe(0)
        self.observe(60, speed=30, engine='engine_on', ready=1, km=101)
        self.observe(120, km=110, soc=76)
        self.observe(180, km=111, soc=75)
        stop = self.monitor.status('synthetic-vehicle')['trip']['stop']
        self.assertIsNone((stop or {}).get('time'))
        for seconds in range(240, 841, 60):
            self.observe(seconds, km=111, soc=75)
            if seconds < 840:
                self.assertEqual(self.events('trip_end'), [])
        data = self.events('trip_end')[0]['summary']
        self.assertEqual(data['end_time'], BASE + 240000)
        self.assertEqual(data['distance_km'], 11)
        self.assertEqual(data['end_soc'], 75)

    def test_short_stop_then_continue_retains_samples_without_inventing_gap(self):
        self.observe(0)
        self.observe(60, speed=30, engine='engine_on', ready=1, km=101)
        for seconds in range(120, 301, 60):
            self.observe(seconds, km=101)
        self.monitor = Monitor(self.monitor.tracks.path)
        self.observe(360, speed=30, engine='engine_on', ready=1, km=102)
        self.assertEqual(self.events('trip_end'), [])
        for seconds in range(420, 1021, 60):
            self.observe(seconds, km=110, soc=76)
        events = self.events('trip_end')
        self.assertEqual(len(events), 1)
        data = events[0]['summary']
        report = data['report_v2']
        self.assertEqual(data['end_time'], BASE + 420000)
        self.assertEqual(report['coverage']['accepted_samples'], 8)
        self.assertEqual(report['quality']['parking_samples'], 10)
        self.assertEqual(report['metrics']['max_gap_seconds'], 60)
        self.assertFalse(report['partial'])

    def test_unknown_charging_sample_breaks_power_and_time_coverage(self):
        self.observe(0, soc=50)
        for seconds in range(60, 541, 60):
            self.charge(seconds, soc=50 + seconds / 60,
                        current=0 if seconds == 120 else 100)
        self.observe(600, soc=59)
        report = self.events('charge_end')[0]['summary']['report_v2']
        metrics = report['metrics']
        self.assertEqual(report['coverage']['accepted_samples'], 10)
        self.assertEqual(metrics['power_covered_seconds'], 360)
        self.assertEqual(metrics['charging_time_covered_seconds'], 360)
        self.assertAlmostEqual(metrics['power_coverage'], 2 / 3)
        self.assertIsNone(metrics['average_power_kw'])

    def test_fresh_parking_then_repeated_cache_keeps_ten_minute_confirmation(self):
        self.observe(0)
        self.observe(60, speed=30, engine='engine_on', ready=1, km=101)
        for seconds in range(120, 601, 60):
            self.observe(seconds, km=110, soc=76)
        self.observe(600, observed_seconds=660, km=110, soc=76)
        self.assertEqual(self.events('trip_end'), [])
        self.observe(600, observed_seconds=720, km=110, soc=76)
        events = self.events('trip_end')
        self.assertEqual(len(events), 1)
        data = events[0]['summary']
        self.assertEqual(data['end_time'], BASE + 120000)
        self.assertEqual(data['report_v2']['coverage']['accepted_samples'], 3)
        self.assertEqual(data['report_v2']['parking']['state_time'], BASE + 600000)

    def test_new_cache_after_continuous_repeated_parking_keeps_frozen_endpoint(self):
        self.observe(0)
        self.observe(60, speed=30, engine='engine_on', ready=1, km=101)
        for seconds in range(120, 301, 60):
            self.observe(seconds, km=110, soc=76)
        for observed in range(360, 661, 60):
            self.observe(300, observed_seconds=observed, km=110, soc=76)
        self.assertEqual(self.events('trip_end'), [])
        self.observe(720, km=110, soc=76)
        events = self.events('trip_end')
        self.assertEqual(len(events), 1)
        data = events[0]['summary']
        self.assertEqual(data['end_time'], BASE + 120000)
        self.assertEqual(data['distance_km'], 10)
        self.assertFalse(data['partial'])
        self.assertEqual(data['report_v2']['coverage']['accepted_samples'], 3)
        self.assertEqual(data['report_v2']['parking']['state_time'], BASE + 720000)

    def test_parking_wait_does_not_evict_driving_samples_at_session_limit(self):
        with patch('zeekr_control.monitor.MAX_SESSION_SAMPLES', 5):
            self.observe(0)
            for seconds, speed, km in ((60, 70, 101), (120, 30, 102), (180, 20, 103)):
                self.observe(seconds, speed=speed, engine='engine_on', ready=1, km=km)
            for seconds in range(240, 841, 60):
                self.observe(seconds, km=104, soc=76)
        report = self.events('trip_end')[0]['summary']['report_v2']
        self.assertEqual(report['coverage']['accepted_samples'], 5)
        self.assertEqual(report['quality']['parking_samples'], 10)
        self.assertEqual(report['metrics']['sampled_max_speed_kmh'], 70)
        self.assertEqual(report['metrics']['max_gap_seconds'], 60)
        self.assertFalse(report['partial'])

    def test_real_confirmation_gap_still_waits_ten_minutes_after_local_reset(self):
        self.observe(0)
        self.observe(60, speed=30, engine='engine_on', ready=1, km=101)
        self.observe(120, km=110, soc=76)
        self.observe(120, observed_seconds=180, km=110, soc=76)
        # No successful observation for four minutes: local confirmation restarts.
        for observed in range(420, 601, 60):
            self.observe(120, observed_seconds=observed, km=110, soc=76)
        trip = self.monitor.status('synthetic-vehicle')['trip']
        self.assertEqual(trip['stop_confirmation']['started'], BASE + 420000)
        for seconds in range(660, 1021, 60):
            self.observe(seconds, km=110, soc=76)
            if seconds < 1020:
                self.assertEqual(self.events('trip_end'), [])
        events = self.events('trip_end')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['summary']['end_time'], BASE + 120000)

    def test_drive_home_charge_stop_and_drive_next_day_are_separate_events(self):
        self.observe(0)
        self.observe(60, speed=30, engine='engine_on', ready=1, km=101, soc=79)
        self.observe(120, speed=30, engine='engine_on', ready=1, km=110, soc=76)
        self.observe(180, km=112, soc=75)
        for seconds in range(240, 781, 60):
            self.charge(seconds, km=112, soc=75 + (seconds - 240) / 60)
        trip = self.events('trip_end')[0]['summary']
        self.assertEqual(trip['end_time'], BASE + 180000)
        self.assertEqual(trip['distance_km'], 12)
        self.assertEqual(trip['soc_delta'], -5)
        self.assertEqual(trip['report_v2']['metrics']['soc_delta'], -5)
        self.assertEqual(trip['report_v2']['coverage']['accepted_samples'], 4)
        self.assertEqual(trip['report_v2']['quality']['parking_samples'], 1)
        self.assertEqual(trip['report_v2']['parking']['soc'], 75)
        self.observe(840, km=112, soc=84)
        charge = self.events('charge_end')[0]['summary']
        self.assertEqual(charge['start_time'], BASE + 240000)
        self.assertEqual(charge['end_time'], BASE + 840000)
        self.assertEqual(charge['soc_delta'], 9)
        self.observe(86400, km=112, soc=84)
        self.observe(86460, speed=30, engine='engine_on', ready=1, km=113, soc=83)
        for seconds in range(86520, 87121, 60):
            self.observe(seconds, km=122, soc=80)
        trips = self.events('trip_end')
        self.assertEqual(len(trips), 2)
        self.assertEqual(trips[1]['summary']['start_time'], BASE + 86400000)
        self.assertEqual(trips[1]['summary']['distance_km'], 10)
        self.assertEqual([event['kind'] for event in self.monitor.events()],
                         ['trip_end', 'charge_start', 'charge_end', 'trip_end'])

    def test_drive_home_then_ac_charge_freezes_arrival_soc_and_sends_start_once(self):
        from test_ac_charging import ac_sample
        self.observe(0)
        self.observe(60, speed=30, engine='engine_on', ready=1, km=101, soc=79)
        self.observe(120, km=110, soc=76)
        for seconds in range(180, 721, 60):
            raw = ac_sample(seconds, chargeLevel=76 + (seconds - 180) / 60)
            raw['additionalVehicleStatus']['maintenanceStatus']['odometer'] = 110
            self.monitor.observe('synthetic-vehicle', raw, BASE + seconds * 1000)
            if seconds == 420:
                self.monitor = Monitor(self.monitor.tracks.path)
        starts = self.events('charge_start')
        self.assertEqual(len(starts), 1)
        self.assertIn('开始充电｜交流', starts[0]['message'])
        trip = self.events('trip_end')[0]['summary']
        self.assertEqual(trip['end_time'], BASE + 120000)
        self.assertEqual(trip['end_soc'], 76)
        self.assertEqual(trip['soc_delta'], -4)
        self.assertEqual(trip['report_v2']['metrics']['soc_delta'], -4)
        self.assertEqual(trip['report_v2']['parking']['charging_mode'], 'ac')
        self.assertEqual(self.events('charge_end'), [])
        self.monitor.observe('synthetic-vehicle', raw, BASE + 780000)
        self.assertEqual(len(self.events('charge_start')), 1)


    def test_unknown_charge_state_and_collection_gap_do_not_invent_stop(self):
        self.observe(0, soc=50)
        self.charge(60, soc=50)
        self.charge(120, soc=51, current=0)
        self.charge(600, soc=55, current=0)
        self.assertEqual(self.events('charge_end'), [])
        self.assertIsNotNone(self.monitor.status('synthetic-vehicle')['charge'])
        self.charge(660, soc=56)
        self.assertEqual(len(self.events('charge_start')), 1)
        self.observe(720, soc=57)
        data = self.events('charge_end')[0]['summary']
        self.assertTrue(data['partial'])
        self.assertEqual(data['start_time'], BASE + 60000)
        self.assertEqual(data['end_time'], BASE + 720000)

    def test_short_stop_charge_then_drive_produces_two_trip_reports(self):
        self.observe(0, soc=80)
        self.observe(60, speed=30, engine='engine_on', ready=1, km=101, soc=79)
        self.observe(120, km=101, soc=79)
        self.charge(180, km=101, soc=80)
        self.observe(240, speed=30, engine='engine_on', ready=1, km=105, soc=81)
        for seconds in range(300, 901, 60):
            self.observe(seconds, km=112, soc=76)
        trips = self.events('trip_end')
        self.assertEqual(len(trips), 2)
        self.assertEqual(trips[0]['summary']['end_time'], BASE + 120000)
        self.assertEqual(trips[0]['summary']['end_soc'], 79)
        self.assertEqual(trips[1]['summary']['start_soc'], 81)

    def test_cross_midnight_charge_restart_stop_and_resume_remain_separate(self):
        self.observe(57480, soc=50)
        for seconds in range(57540, 58141, 60):
            self.charge(seconds, soc=50 + (seconds - 57540) / 60)
            if seconds == 57840:
                self.monitor = Monitor(self.monitor.tracks.path)
        stopped = sample(58200, soc=61, charger=26, dc_lid=1)
        electric = stopped['additionalVehicleStatus']['electricVehicleStatus']
        electric.update(dcChargeSts=10, dcChargePileUAct=400, dcChargePileIAct=0)
        self.monitor.observe('synthetic-vehicle', stopped, BASE + 58200000)
        # A fresh identical stopped state is not another charge-end event.
        stopped['updateTime'] = BASE + 58260000
        self.monitor.observe('synthetic-vehicle', stopped, BASE + 58260000)
        self.assertEqual(len(self.events('charge_start')), 1)
        ended = self.events('charge_end')
        self.assertEqual(len(ended), 1)
        self.assertIn('01月01日 23:59—01月02日 00:10', ended[0]['message'])
        self.assertIn('充电已停止', ended[0]['message'])
        self.assertNotIn('停止原因：未确认', ended[0]['message'])
        self.assertNotIn('充满', ended[0]['message'])
        self.assertNotIn('充电枪连接：未确认', ended[0]['message'])
        self.assertFalse(ended[0]['summary']['partial'])
        self.charge(58320, soc=61)
        starts = self.events('charge_start')
        self.assertEqual(len(starts), 2)
        self.assertNotEqual(starts[0]['id'], starts[1]['id'])
        self.assertEqual(len(self.events('charge_end')), 1)


if __name__ == '__main__':
    unittest.main()
