"""P-gear trip boundaries; synthetic observations, no vehicle/network requests."""
from pathlib import Path
import tempfile
import unittest

from zeekr_control.monitor import Monitor
from test_monitor import BASE, sample


class ParkingConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tracks.sqlite3'
        self.monitor = Monitor(self.path)
        self.observe(0)
        self.observe(20, gear=3, speed=30, engine='engine_on', ready=1, km=101)

    def observe(self, second, gear=0, valid_speed=True, observed=None, **values):
        raw = sample(second, **values)
        raw['additionalVehicleStatus']['drivingBehaviourStatus'] = {'gearAutoStatus': gear}
        raw['basicVehicleStatus']['speedValidity'] = valid_speed
        self.monitor.observe('car', raw, BASE + (second if observed is None else observed)*1000,
                             battery_capacity_kwh=86, profile={'battery_capacity_kwh':86})

    def test_p_off_stationary_confirms_in_one_minute_and_keeps_first_endpoint(self):
        self.observe(40, km=110, soc=76)
        self.observe(60, km=110, soc=76, valid_speed=False)
        self.assertFalse(self.monitor.events())
        self.observe(100, km=110, soc=76, valid_speed=False)
        event = self.monitor.events()[0]
        self.assertEqual(event['summary']['end_time'], BASE+40000)
        self.assertEqual(event['summary']['distance_km'], 10)
        self.assertEqual(event['summary']['end_evidence']['basis'], 'p_gear_confirmed')
        self.assertIsNone(self.monitor.status('car')['trip'])

    def test_new_drive_after_confirmed_p_creates_second_trip_without_duplicate_distance(self):
        self.observe(40, km=110, soc=76)
        self.observe(100, km=110, soc=76)
        self.observe(120, gear=3, engine='engine_on', ready=1, km=110, soc=76)
        self.observe(140, gear=3, speed=30, engine='engine_on', ready=1, km=111, soc=75)
        self.observe(160, km=116, soc=72)
        self.observe(220, km=116, soc=72)
        events = self.monitor.events()
        self.assertEqual(len(events), 2)
        self.assertEqual(sum(e['summary']['distance_km'] for e in events), 16)
        self.assertEqual(sum(-e['summary']['soc_delta'] for e in events), 8)

    def test_drive_neutral_reverse_stops_do_not_finish_even_if_off_signal_claims_off(self):
        for gear in (1, 2, 3):
            with self.subTest(gear=gear):
                self.monitor = Monitor(self.path.with_name(str(gear)+'.sqlite3'))
                self.observe(0)
                self.observe(20, gear=3, speed=30, engine='engine_on', ready=1, km=101)
                for second in range(40, 761, 60):self.observe(second, gear=gear, km=101)
                self.assertFalse(self.monitor.events())

    def test_p_with_power_on_or_moving_never_confirms(self):
        for values in ({'engine':'engine_on','ready':1}, {'speed':5}):
            with self.subTest(values=values):
                self.monitor = Monitor(self.path.with_name(str(len(str(values)))+'.sqlite3'))
                self.observe(0)
                self.observe(20, gear=3, speed=30, engine='engine_on', ready=1, km=101)
                for second in (40, 60, 100, 120):self.observe(second, km=101, **values)
                self.assertFalse(self.monitor.events())

    def test_missing_speed_requires_three_p_off_states_over_two_minutes_and_is_inferred(self):
        self.observe(40, km=110, valid_speed=False)
        self.observe(100, km=110, valid_speed=False)
        self.assertFalse(self.monitor.events())
        self.observe(160, km=110, valid_speed=False)
        evidence = self.monitor.events()[0]['summary']['end_evidence']
        self.assertEqual(evidence['basis'], 'p_gear_stationary_inferred')
        self.assertFalse(evidence['zero_speed_observed'])
        self.assertEqual(evidence['confirmation_ms'], 120000)

    def test_restart_keeps_valid_confirmation_without_gap(self):
        self.observe(40, km=110)
        self.monitor = Monitor(self.path)
        self.observe(100, km=110)
        self.assertEqual(len(self.monitor.events()), 1)

    def test_missing_p_falls_back_to_legacy_wait(self):
        for second in range(40, 640, 60):
            self.observe(second, gear=None, km=110)
            self.assertFalse(self.monitor.events())
        self.observe(640, gear=None, km=110)
        self.assertEqual(len(self.monitor.events()), 1)

    def test_brief_p_stop_then_drive_remains_one_trip(self):
        self.observe(40, km=110)
        self.observe(60, km=110)
        self.observe(80, gear=3, speed=20, engine='engine_on', ready=1, km=111)
        self.assertFalse(self.monitor.events())
        self.observe(100, km=116)
        self.observe(160, km=116)
        self.assertEqual(self.monitor.events()[0]['summary']['distance_km'], 16)

    def test_old_p_cache_cannot_bridge_a_new_confirmation(self):
        self.observe(40, km=110)
        self.observe(40, km=110, observed=240)
        self.observe(260, km=110)
        self.assertFalse(self.monitor.events())
        self.observe(320, km=110)
        self.assertEqual(len(self.monitor.events()), 1)

    def test_repeated_cache_does_not_confirm_and_does_not_erase_fresh_evidence(self):
        self.observe(40, km=110)
        for now in (60, 80, 100):self.observe(40, km=110, observed=now)
        self.assertFalse(self.monitor.events())
        self.observe(101, km=110, valid_speed=False)
        self.assertEqual(len(self.monitor.events()), 1)

    def test_restart_keeps_confirmation_and_known_collection_gap_restarts_it(self):
        self.observe(40, km=110)
        self.monitor = Monitor(self.path)
        self.observe(80, km=110)
        self.monitor.mark_sampling_gap('car')
        self.observe(100, km=110)
        self.assertFalse(self.monitor.events())
        self.observe(140, km=110)
        self.assertFalse(self.monitor.events())
        self.observe(160, km=110)
        self.assertEqual(len(self.monitor.events()), 1)

    def test_conflicting_gear_breaks_confirmation(self):
        self.observe(40, km=110)
        self.observe(80, gear=3, km=110)
        self.observe(100, km=110)
        self.observe(140, km=110)
        self.assertFalse(self.monitor.events())
        self.observe(160, km=110)
        self.assertEqual(self.monitor.events()[0]['summary']['end_time'], BASE+100000)


if __name__ == '__main__':unittest.main()
