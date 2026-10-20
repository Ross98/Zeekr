import json
import unittest
from zeekr_control.tracks import day_bounds
from zeekr_control.personal_store import PersonalStore
from zeekr_control.charge_ledger import ChargeLedger
import test_usage_reports as fixtures

class ChargingReviewTests(unittest.TestCase):
    setUp=fixtures.UsageReportsTests.setUp
    add=fixtures.UsageReportsTests.add

    def review(self,date='2026-09-01',now=None,owner='owner'):
        from zeekr_control.charging_review import ChargingReview
        return ChargingReview(self.db,PersonalStore(self.root/'personal.sqlite3')).query(owner,'car',date,now=self.now if now is None else now)

    def charge(self,identity='charge',**changes):
        return self.add(identity,kind='charge_end',start_soc=20,end_soc=80,soc_delta=60,**changes)

    def bill(self,identity,amount='10',meter='60'):
        store=PersonalStore(self.root/'personal.sqlite3')
        ChargeLedger(store,self.db).update('owner','car',dict(action='save',revision=store.read('owner','car','charges')['revision'],event_id=identity,date='2026-09-15',source='unknown',amount=amount,metered_kwh=meter))

    def test_month_records_unknown_bills_privacy_and_vehicle_scope(self):
        self.charge();self.add('trip');self.charge('other',vehicle='other')
        result=self.review()
        self.assertEqual(len(result['records']),1)
        self.assertEqual(result['summary']['charge_count'],1)
        self.assertEqual(result['summary']['pending_count'],1)
        self.assertIsNone(result['summary']['actual_cents'])
        self.assertAlmostEqual(result['summary']['estimated_kwh'],51.6)
        self.assertEqual(result['records'][0]['place_label'],'地点未知')
        for secret in ('PRIVATE-VIN','PRIVATE-ADDRESS','coordinates','latitude','longitude'):
            self.assertNotIn(secret,json.dumps(result))

    def test_weighted_price_uses_only_paired_bills_and_meter_not_soc(self):
        self.charge('a');self.charge('b');self.charge('c')
        self.bill('a','20','60');self.bill('b','40','80');self.bill('c','30',None)
        result=self.review();s=result['summary']
        self.assertEqual(s['actual_cents'],9000)
        self.assertAlmostEqual(result['analysis']['unit_price_cents_per_kwh'],6000/140)
        self.assertEqual(result['analysis']['metered_samples'],2)
        self.assertIsNone(self.review(owner='other')['summary']['actual_cents'])

    def test_mode_unknown_and_free_charging_are_preserved(self):
        self.charge('ac',report_v2={'start':{'charging_mode':'ac'},'end':{'charging_mode':'ac'}})
        self.charge('conflict',report_v2={'start':{'charging_mode':'ac'},'end':{'charging_mode':'dc'}})
        self.bill('ac','0','60');self.bill('conflict','10','60')
        result=self.review();groups={g['mode']:g for g in result['groups']}
        self.assertEqual(groups['ac']['actual_cents'],0)
        self.assertEqual(groups['unknown']['actual_cents'],1000)
        self.assertEqual(result['summary']['pending_count'],0)
        self.assertEqual(groups['unknown']['share_percent'],100)

    def test_overnight_is_counted_only_on_end_month(self):
        boundary=day_bounds('2026-10-01')[0]
        self.charge(start_time=boundary-3600000,end_time=boundary+3600000,duration_seconds=7200)
        self.assertEqual(self.review()['records'],[])
        self.assertEqual(len(self.review('2026-10-01')['records']),1)

    def test_current_month_compares_previous_same_elapsed_period(self):
        self.charge('september',day='2026-09-15');self.bill('september','10')
        self.charge('october',day='2026-10-15');self.bill('october','20')
        self.charge('late',day='2026-09-30');self.bill('late','100')
        now=day_bounds('2026-10-20')[0]+12*3600000
        result=self.review('2026-10-01',now)
        self.assertEqual(result['comparison']['previous_actual_cents'],1000)
        self.assertEqual(result['comparison']['change_percent'],100)
        self.assertEqual(result['comparison']['previous_end_date'],'2026-09-20')

    def test_future_and_empty_month_do_not_invent_zero_prices(self):
        for date in ('2024-02-01','2026-12-01'):
            r=self.review(date)
            self.assertEqual(r['records'],[])
            self.assertIsNone(r['analysis']['unit_price_cents_per_kwh'])
            self.assertIsNone(r['intervals']['summary']['kwh_per_100km'])
            self.assertIsNone(r['comparison']['change_percent'])
        with self.assertRaises(ValueError):self.review('2026-02-30')

    def test_partial_energy_is_counted_but_not_fabricated(self):
        self.charge(partial=True);r=self.review()
        self.assertEqual(r['summary']['partial_count'],1)
        self.assertAlmostEqual(r['summary']['estimated_kwh'],51.6)

    def test_existing_manual_mode_correction_is_honored(self):
        self.charge('corrected')
        store=PersonalStore(self.root/'personal.sqlite3')
        ChargeLedger(store,self.db).update('owner','car',dict(action='save',revision=0,event_id='corrected',date='2026-09-15',source='unknown',amount='20',charge_mode_override='dc'))
        row=self.review()['records'][0]
        self.assertEqual(row['mode'],'dc')
        self.assertEqual(row['mode_source'],'manual')

    def test_review_exposes_whole_interval_consumption_instead_of_trip_costs(self):
        from test_charging_intervals import ChargingIntervalsTests
        ChargingIntervalsTests.charge(self,'a','2026-09-15',30,80,1000)
        ChargingIntervalsTests.charge(self,'b','2026-09-20',40,90,1200)
        r=self.review()
        self.assertIsNone(r['driving']['cents_per_100km'])
        self.assertEqual(r['driving']['status'],'replaced_by_intervals')
        self.assertAlmostEqual(r['intervals']['summary']['kwh_per_100km'],17.2)
        self.assertIsNone(r['intervals']['summary']['cents_per_100km'])
