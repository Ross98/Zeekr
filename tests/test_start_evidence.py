"""Start evidence uses synthetic state and a distinct observation clock."""
import json
from pathlib import Path
import tempfile
import unittest

from zeekr_control.monitor import Monitor
from zeekr_control.events import EventStore
from zeekr_control.trips import TripStore
from zeekr_control.charging_analytics import ChargingAnalytics
from test_monitor import BASE, sample


class StartEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'private' / 'tracks.sqlite3'
        self.monitor = Monitor(self.path)

    def observe(self, seconds, observed=None, **changes):
        return self.monitor.observe('car-a', sample(seconds, **changes),
                                    BASE + (seconds if observed is None else observed)*1000)

    def test_trip_brackets_start_and_keeps_baseline_metrics(self):
        self.observe(0, observed=10)
        self.observe(60, observed=80, speed=30, engine='engine_on', ready=1, km=101, soc=79)
        trip = TripStore(self.path).active('car-a')
        self.assertEqual((trip['start_time'], trip['start_soc'], trip['distance_km']), (BASE, 80, 1))
        evidence = trip['start_evidence']
        self.assertEqual(evidence['basis'], 'bounded')
        self.assertEqual((evidence['earliest_time'], evidence['latest_time']), (BASE, BASE+60000))
        self.assertEqual((evidence['first_state_time'], evidence['detected_at']), (BASE+60000, BASE+80000))
        self.assertEqual(evidence['sample_age_seconds'], 20)
        self.assertEqual((evidence['delay_min_seconds'], evidence['delay_max_seconds']), (20, 80))
        self.assertIsNone(evidence['actual_start_time'])
        self.monitor = Monitor(self.path)
        self.observe(120, km=110, soc=75)
        for second in range(180, 721, 60):
            self.observe(second, km=110, soc=75)
        event = self.monitor.events()[0]
        self.assertEqual(event['summary']['start_evidence'], evidence)
        self.assertEqual(event['summary']['report_v2']['start_evidence'], evidence)
        self.assertEqual((event['summary']['distance_km'], event['summary']['duration_seconds']), (10, 120))
        public = EventStore(self.path).query('car-a', '2024-01-01', 'trip_end')['events'][0]
        self.assertEqual(public['start_evidence'], evidence)
        self.assertIn('可能开始范围', event['message'])
        self.assertIn('系统首次发现', event['message'])

    def test_charge_start_and_end_keep_distinct_observation_time(self):
        self.observe(0)
        self.observe(60, observed=90, code='charging', dc_lid=1)
        start = self.monitor.events()[0]
        evidence = start['summary']['start_evidence']
        self.assertEqual(evidence['basis'], 'bounded')
        self.assertEqual(start['summary']['start_time'], BASE+60000)
        self.assertEqual(evidence['delay_max_seconds'], 90)
        self.assertEqual(ChargingAnalytics(self.path).session('car-a', 'current')['start_evidence'], evidence)
        self.observe(60, observed=100, code='charging', dc_lid=1)
        self.observe(30, observed=105, code='charging', dc_lid=1)
        self.monitor = Monitor(self.path)
        self.observe(120, soc=81)
        event = self.monitor.events()[-1]
        self.assertEqual(event['kind'], 'charge_end')
        self.assertEqual(event['summary']['start_evidence'], evidence)
        self.assertEqual(ChargingAnalytics(self.path).session('car-a', event['id'])['start_evidence'], evidence)
        self.assertEqual(len(self.monitor.events()), 2)

    def test_unknown_previous_or_observation_gap_cannot_bracket(self):
        scenarios = [(None, 60, 60), ({'engine':'unknown', 'charger':99, 'code':99}, 60, 60),
                     ({}, 300, 300), ({}, 120, 240)]
        for index, (previous, seconds, observed) in enumerate(scenarios):
            with self.subTest(index=index):
                self.path = Path(self.temp.name) / str(index) / 'tracks.sqlite3'
                self.monitor = Monitor(self.path)
                if previous is not None:
                    self.observe(0, **previous)
                self.observe(seconds, observed=observed, code='charging', dc_lid=1)
                evidence = self.monitor.events()[0]['summary']['start_evidence']
                self.assertEqual(evidence['basis'], 'first_observation')
                self.assertIsNone(evidence['earliest_time'])
                self.assertIsNone(evidence['delay_max_seconds'])
                self.assertEqual(evidence['first_state_time'], BASE+seconds*1000)

    def test_stationary_engine_on_is_not_a_confirmed_trip_boundary(self):
        self.observe(0, engine='engine_on', ready=1)
        self.observe(60, speed=20, engine='engine_on', ready=1)
        self.assertEqual(TripStore(self.path).active('car-a')['start_evidence']['basis'], 'first_observation')

    def test_future_clock_does_not_claim_negative_detection_delay(self):
        self.observe(0)
        self.observe(60, observed=50, code='charging', dc_lid=1)
        evidence = self.monitor.events()[0]['summary']['start_evidence']
        self.assertIsNone(evidence['sample_age_seconds'])
        self.assertIsNone(evidence['delay_min_seconds'])
        self.assertIsNone(evidence['delay_max_seconds'])

    def test_legacy_events_remain_readonly_and_unknown(self):
        self.observe(0, speed=20, engine='engine_on', ready=1)
        with self.monitor.tracks.connect() as db:
            state = self.monitor.status('car-a')
            state['trip'].pop('start_evidence', None)
            state['trip'].pop('report_start', None)
            db.execute('UPDATE monitor_state SET payload=?', (json.dumps(state),))
        before = self.path.read_bytes()
        evidence = TripStore(self.path).active('car-a')['start_evidence']
        self.assertEqual(evidence['basis'], 'legacy')
        self.assertIsNone(evidence['detected_at'])
        self.assertIsNone(evidence['first_state_time'])
        self.assertEqual(before, self.path.read_bytes())

    def test_projection_rejects_private_and_unverified_exact_fields(self):
        from zeekr_control.start_evidence import project
        evidence = project({'basis':'exact', 'actual_start_time':BASE, 'detected_at':True,
                            'earliest_time':float('nan'), 'latest_time':float('inf'),
                            'location':{'latitude':31}, 'private':'NEVER-PUBLIC'})
        self.assertEqual(evidence['basis'], 'legacy')
        self.assertIsNone(evidence['actual_start_time'])
        self.assertIsNone(evidence['detected_at'])
        self.assertNotIn('NEVER-PUBLIC', json.dumps(evidence))
        self.assertNotIn('latitude', json.dumps(evidence))

    def test_ac_start_uses_same_evidence_and_does_not_backdate_soc(self):
        from test_ac_charging import ac_sample
        self.observe(0, soc=40)
        raw = ac_sample(60, chargeLevel=41)
        self.monitor.observe('car-a', raw, BASE+85000)
        event = self.monitor.events()[0]
        self.assertEqual(event['summary']['start_evidence']['basis'], 'bounded')
        self.assertEqual(event['summary']['start_soc'], 41)
        self.assertEqual(event['summary']['start_time'], BASE+60000)
        self.assertEqual(event['summary']['start_evidence']['sample_age_seconds'], 25)

    def test_new_observation_after_stale_gap_has_no_invented_boundary(self):
        self.observe(0)
        self.assertEqual(self.observe(60, observed=500), 'stale')
        self.observe(540, observed=560, speed=20, engine='engine_on', ready=1)
        trip = TripStore(self.path).active('car-a')
        self.assertTrue(trip['partial'])
        self.assertEqual(trip['start_time'], BASE+540000)
        self.assertEqual(trip['start_evidence']['basis'], 'first_observation')

    def test_legacy_saved_first_activity_can_recover_detection_but_not_boundary(self):
        from zeekr_control.start_evidence import from_summary
        saved = {'state_time':BASE+60000,'observed_at':BASE+83000,'charging':True,'speed':0}
        summary = {'start_time':BASE+60000,'report_v2':{'kind':'charge_end','start':saved}}
        evidence = from_summary(summary)
        self.assertEqual(evidence['basis'],'first_observation')
        self.assertEqual(evidence['sample_age_seconds'],23)
        self.assertIsNone(evidence['earliest_time'])
        self.assertIsNone(evidence['delay_max_seconds'])
        summary['start_time'] = BASE  # A report upgraded mid-session is not the first activity.
        self.assertEqual(from_summary(summary)['basis'],'legacy')
        summary['start_time'] = BASE+60000
        summary['report_v2']['kind'] = 'trip_end'
        self.assertEqual(from_summary(summary)['basis'],'legacy')  # Stationary trip baseline is not first motion.
        saved['speed'] = 20
        self.assertEqual(from_summary(summary)['basis'],'first_observation')
        self.assertEqual(from_summary({'start':{'time':BASE},'report_start':saved},'trip')['basis'],'legacy')

    def test_bounded_projection_rejects_wide_or_inconsistent_boundaries(self):
        from zeekr_control.start_evidence import project
        value = {'version':1,'basis':'bounded','first_state_time':BASE+300000,'detected_at':BASE+310000,
                 'previous_state_time':BASE,'previous_observed_at':BASE+290000}
        result=project(value)
        self.assertEqual(result['basis'],'first_observation')
        self.assertIsNone(result['earliest_time'])

    def test_legacy_inflight_charge_keeps_recovered_first_sample_at_end(self):
        self.observe(0, observed=15, code='charging', dc_lid=1)
        with self.monitor.tracks.connect() as db:
            state = self.monitor.status('car-a')
            state['charge'].pop('start_evidence')
            db.execute('UPDATE monitor_state SET payload=?', (json.dumps(state),))
        before = ChargingAnalytics(self.path).session('car-a','current')['start_evidence']
        self.assertEqual(before['detected_at'],BASE+15000)
        self.monitor = Monitor(self.path)
        self.observe(60)
        self.assertEqual(self.monitor.events()[-1]['summary']['start_evidence'],before)


if __name__ == '__main__':
    unittest.main()
