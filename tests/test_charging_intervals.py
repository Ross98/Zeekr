import json
import unittest
import test_usage_reports as fixtures
from zeekr_control.tracks import day_bounds
from zeekr_control.usage_reports import period_window


class ChargingIntervalsTests(unittest.TestCase):
    setUp = fixtures.UsageReportsTests.setUp
    add = fixtures.UsageReportsTests.add

    def charge(self, identity, day, a, b, odometer, *, partial=False, capacity=86, **changes):
        start = day_bounds(day)[0]+8*3600000
        report = dict(start=dict(state_time=start, observed_at=start+1000, soc=a, odometer=odometer, charging=True),
                      end=dict(state_time=start+3600000, observed_at=start+3601000, soc=b, odometer=odometer, charging=False),
                      partial=partial, profile_snapshot=dict(battery_capacity_kwh=capacity), quality={})
        report.update(changes)
        self.add(identity,'charge_end',day=day,start_soc=a,end_soc=b,soc_delta=b-a,partial=partial,report_v2=report)

    def query(self, month='2026-09-01', books=None, now=None):
        from zeekr_control.charging_intervals import ChargingIntervals
        return ChargingIntervals(self.db).query('car',period_window('month',month),self.now if now is None else now,books or {})

    def pair(self):
        self.charge('a','2026-09-15',30,80,1000)
        self.charge('b','2026-09-20',40,90,1200)

    def test_interval_uses_battery_and_odometer_endpoints_not_trip_samples(self):
        self.pair()
        self.add('flat',day='2026-09-17',distance_km=2,start_soc=70,end_soc=70,soc_delta=0)
        r=self.query();s=r['summary']
        self.assertEqual(s['valid_count'],1)
        self.assertEqual(s['distance_km'],200)
        self.assertAlmostEqual(s['estimated_kwh'],34.4)
        self.assertAlmostEqual(s['kwh_per_100km'],17.2)
        self.assertEqual(r['records'][-1]['reason'],'missing_previous')
        self.assertIsNone(s['cents_per_100km'])

    def test_weighted_month_uses_total_energy_over_total_distance(self):
        self.pair();self.charge('c','2026-09-25',80,90,1300)
        s=self.query()['summary']
        self.assertEqual(s['valid_count'],2)
        self.assertEqual(s['distance_km'],300)
        self.assertAlmostEqual(s['kwh_per_100km'],43/300*100)

    def test_cross_month_interval_is_kept_whole_and_assigned_to_closing_charge_month(self):
        self.charge('a','2026-08-31',30,80,1000);self.charge('b','2026-09-02',40,90,1200)
        r=self.query();self.assertEqual(r['summary']['valid_count'],1)
        self.assertTrue(r['records'][0]['cross_month'])
        self.assertEqual(r['summary']['distance_km'],200)
        self.assertEqual(self.query('2026-08-01')['summary']['valid_count'],0)

    def test_missing_previous_is_not_zero_and_current_interval_waits(self):
        self.charge('a','2026-09-15',30,80,1000)
        r=self.query(now=day_bounds('2026-09-20')[0])
        self.assertIsNone(r['summary']['kwh_per_100km'])
        self.assertEqual(r['records'][0]['reason'],'missing_previous')
        self.assertEqual(r['open_interval']['start_time'],day_bounds('2026-09-15')[0]+9*3600000)
        self.assertIsNone(self.query()['open_interval'])

    def test_late_start_at_closing_charge_cannot_be_treated_as_precharge_soc(self):
        self.charge('a','2026-09-15',30,80,1000);self.charge('b','2026-09-20',40,90,1200,partial=True)
        r=self.query();self.assertEqual(r['records'][0]['reason'],'late_start')
        self.assertIsNone(r['summary']['kwh_per_100km'])

    def test_late_start_of_previous_charge_does_not_invalidate_its_confirmed_end(self):
        self.charge('a','2026-09-15',30,80,1000,partial=True);self.charge('b','2026-09-20',40,90,1200)
        self.assertEqual(self.query()['summary']['valid_count'],1)

    def test_small_soc_change_and_short_distance_are_insufficient(self):
        for endpoint,km,reason in [(80,1200,'soc_resolution'),(79,1200,'soc_resolution'),(40,1001,'short_distance'),(40,1000,'no_distance'),(40,900,'odometer_reset'),(85,1200,'soc_increase')]:
            with self.subTest(endpoint=endpoint,km=km):
                self.setUp();self.charge('a','2026-09-15',30,80,1000);self.charge('b','2026-09-20',endpoint,90,km)
                r=self.query();self.assertIsNone(r['summary']['kwh_per_100km']);self.assertEqual(r['records'][0]['reason'],reason)

    def test_missing_or_inconsistent_boundary_and_capacity_are_excluded(self):
        cases=[('capacity_changed',{'profile_snapshot':{'battery_capacity_kwh':100}}),
               ('missing_endpoint',{'start':{}}),('decoder_changed',{'quality':{'decoder_changed_mid_session':True}})]
        for reason,changes in cases:
            with self.subTest(reason=reason):
                self.setUp();self.charge('a','2026-09-15',30,80,1000);self.charge('b','2026-09-20',40,90,1200,**changes)
                self.assertEqual(self.query()['records'][0]['reason'],reason)

    def test_reference_price_uses_previous_charge_paired_meter_and_fee_and_allows_free(self):
        self.pair()
        for fee,expected in [(4000,1720),(0,0)]:
            r=self.query(books={'a':{'actual_cents':fee,'metered_kwh':40}})['summary']
            self.assertAlmostEqual(r['cents_per_100km'],expected)
            self.assertEqual(r['priced_count'],1)
        self.assertIsNone(self.query(books={'a':{'actual_cents':4000}})['summary']['cents_per_100km'])

    def test_unpriced_interval_does_not_dilute_priced_distance(self):
        self.pair();self.charge('c','2026-09-25',80,90,1300)
        s=self.query(books={'a':{'actual_cents':4000,'metered_kwh':40}})['summary']
        self.assertEqual(s['distance_km'],300);self.assertEqual(s['priced_distance_km'],200)
        self.assertAlmostEqual(s['cents_per_100km'],1720)

    def test_hidden_charge_is_a_barrier_and_other_vehicle_is_ignored(self):
        self.pair();self.charge('c','2026-09-25',40,90,1300)
        with self.add_db() as db:
            db.execute('CREATE TABLE charge_record_trash(vehicle TEXT,event_id TEXT)')
            db.execute("INSERT INTO charge_record_trash VALUES('car','b')")
        r=self.query();self.assertEqual(len(r['records']),2)
        self.assertEqual(r['records'][0]['reason'],'hidden_charge')
        self.assertIsNone(r['records'][0]['start_time'])
        self.assertIsNone(r['records'][0]['previous_id'])
        self.assertEqual(r['summary']['valid_count'],0)
        self.add('foreign','charge_end',vehicle='another')
        self.assertEqual(self.query()['summary']['interval_count'],2)

    def add_db(self):
        import sqlite3
        return sqlite3.connect(self.db)

    def test_future_and_malformed_charge_do_not_create_fake_interval(self):
        self.pair()
        with self.add_db() as db:
            db.execute("INSERT INTO monitor_events VALUES('broken','car','charge_end','not-json',1)")
        r=self.query();self.assertIsNone(r['summary']['kwh_per_100km'])
        self.assertEqual(r['quality']['undated_charge_count'],1)
        self.assertEqual(self.query('2026-12-01')['records'],[])
        self.assertNotIn('PRIVATE',json.dumps(r))

    def test_unclosed_charge_start_between_boundaries_blocks_estimation(self):
        self.pair()
        stamp=day_bounds('2026-09-17')[0]
        self.add('unclosed','charge_start',day='2026-09-17',start_time=stamp,end_time=stamp)
        r=self.query()
        self.assertEqual(r['records'][0]['reason'],'unclosed_charge')
        self.assertIsNone(r['summary']['kwh_per_100km'])

    def test_stale_boundary_is_not_a_valid_interval_endpoint(self):
        self.charge('a','2026-09-15',30,80,1000)
        start=day_bounds('2026-09-20')[0]+8*3600000
        self.charge('b','2026-09-20',40,90,1200,start=dict(state_time=start,observed_at=start+600000,soc=40,odometer=1200,charging=True))
        self.assertEqual(self.query()['records'][0]['reason'],'missing_endpoint')

    def test_overlapping_charge_sessions_do_not_form_usage_interval(self):
        self.charge('a','2026-09-15',30,80,1000)
        self.charge('b','2026-09-15',40,90,1200)
        self.assertEqual(self.query()['records'][0]['reason'],'overlap')

    def test_impossible_odometer_jump_is_not_reported_as_tiny_consumption(self):
        self.charge('a','2026-09-15',30,80,1000)
        self.charge('b','2026-09-20',40,90,1000000)
        self.assertEqual(self.query()['records'][0]['reason'],'odometer_jump')
