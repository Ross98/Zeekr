import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from zeekr_control.charge_ledger import ChargeLedger
from zeekr_control.personal_store import PersonalStore
from zeekr_control.tracks import day_bounds


class ChargeLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'tracks.sqlite3'
        self.personal=PersonalStore(self.root/'personal.sqlite3')
        self.ledger=ChargeLedger(self.personal,self.db)
        self.start,_=day_bounds('2026-09-20')
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE monitor_events(id TEXT PRIMARY KEY,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
            for identity,kind,distance,a,b,vehicle in [('charge','charge_end',0,40,80,'car'),('trip','trip_end',100,80,60,'car'),('other','charge_end',0,30,90,'other')]:
                summary=dict(start_time=self.start,end_time=self.start+3600000,duration_seconds=3600,
                             start_soc=a,end_soc=b,soc_delta=b-a,distance_km=distance,partial=False,battery_capacity_kwh=86)
                db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',(identity,vehicle,kind,json.dumps(summary),self.start))
        self.db.chmod(0o600)

    def save(self,revision=0,**changes):
        data={'action':'save','revision':revision,'event_id':'charge','date':'2026-09-20','source':'home',
              'amount':'','metered_kwh':'','unit_price':'','service_fee':'','note':''}
        data.update(changes)
        return self.ledger.update('owner','car',data)

    def query(self,date='2026-09-20'):
        return self.ledger.query('owner','car',date)

    def test_actual_bill_overrides_estimate_without_double_counting(self):
        self.save(amount='30.10',metered_kwh='40',unit_price='0.75',service_fee='1')
        data=self.query();row=data['entries'][0]
        self.assertEqual(row['actual_cents'],3010)
        self.assertEqual(row['estimated_cents'],3100)
        self.assertEqual(data['totals']['actual_cents'],3010)
        self.assertEqual(data['totals']['unbilled_estimated_cents'],None)
        self.assertAlmostEqual(data['cost_per_km']['actual_yuan'],.301)
        self.assertEqual(row['estimate_basis'],'metered_price')

    def test_soc_based_cost_is_explicit_and_frozen_to_recorded_capacity(self):
        self.save(unit_price='0.5')
        row=self.query()['entries'][0]
        self.assertEqual(row['estimated_cents'],1720)
        self.assertIsNone(row['actual_cents'])
        self.assertEqual(row['estimate_basis'],'soc_price')
        self.assertEqual(row['event']['battery_capacity_kwh'],86)

    def test_partial_trip_distance_is_included_in_monthly_cost_reference(self):
        self.save(amount='30')
        with sqlite3.connect(self.db) as db:
            summary=json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='trip'").fetchone()[0])
            summary.update(partial=True,distance_km=50)
            db.execute("INSERT INTO monitor_events VALUES ('partial','car','trip_end',?,?)",
                       (json.dumps(summary),self.start))
        cost=self.query()['cost_per_km']
        self.assertEqual(cost['distance_km'],150)
        self.assertEqual(cost['distance_samples'],2)
        self.assertEqual(cost['partial_distance_samples'],1)
        self.assertEqual(cost['actual_yuan'],.2)

    def test_manual_unlinked_entry_and_zero_cost_are_valid(self):
        self.save(event_id='',amount='0',metered_kwh='10',source='public')
        data=self.query();row=data['entries'][0]
        self.assertIsNone(row['event'])
        self.assertTrue(row['id'].startswith('manual_'))
        self.assertEqual(data['totals']['actual_cents'],0)
        self.assertEqual(data['totals']['actual_count'],1)

    def test_rounding_to_cents_and_source_breakdown(self):
        self.save(metered_kwh='1',unit_price='0.005')
        self.save(revision=1,event_id='',amount='20',source='public')
        data=self.query()
        self.assertEqual(data['totals']['unbilled_estimated_cents'],1)
        self.assertEqual(data['sources']['home']['count'],1)
        self.assertEqual(data['sources']['public']['actual_cents'],2000)

    def test_missing_price_or_energy_never_turns_into_free_charging(self):
        self.save(event_id='',service_fee='5')
        row=self.query()['entries'][0]
        self.assertIsNone(row['estimated_cents'])
        self.assertIsNone(row['actual_cents'])
        self.assertEqual(self.query()['totals']['unpriced_count'],1)

    def test_event_selection_rejects_other_vehicle_and_trip(self):
        for event in ('other','trip','missing'):
            with self.assertRaises(ValueError):self.save(event_id=event)

    def test_money_and_date_validation(self):
        for changes in ({'amount':'-1'},{'amount':'1.001'},{'unit_price':'NaN'},{'metered_kwh':True},
                        {'date':'2026-02-30'},{'date':None},{'date':20260920},{'date':[]},
                        {'source':'unknown-code'},{'note':'x'*1001}):
            with self.assertRaises(ValueError):self.save(**changes)

    def test_duplicate_event_edits_one_record_with_revision_control(self):
        self.save(amount='10')
        self.save(revision=1,amount='12')
        data=self.query()
        self.assertEqual(len(data['entries']),1)
        self.assertEqual(data['totals']['actual_cents'],1200)
        with self.assertRaises(ValueError):self.save(revision=1,amount='99')

    def test_soft_delete_undo_and_reopen(self):
        self.save(amount='12')
        identity=self.query()['entries'][0]['id']
        self.ledger.update('owner','car',{'action':'delete','id':identity,'revision':1})
        data=self.query();self.assertEqual(data['entries'],[]);self.assertEqual(len(data['trash']),1)
        self.ledger.update('owner','car',{'action':'undo','revision':2})
        reopened=ChargeLedger(PersonalStore(self.root/'personal.sqlite3'),self.db).query('owner','car','2026-09-20')
        self.assertEqual(reopened['totals']['actual_cents'],1200)

    def test_month_trend_and_bill_date_determine_period(self):
        self.save(amount='12',date='2026-08-31')
        data=self.query()
        self.assertEqual(data['entries'],[])
        self.assertEqual(data['trend'][-2]['actual_cents'],1200)
        self.assertEqual(self.query('2026-08-01')['totals']['actual_cents'],1200)

    def test_scope_and_privacy(self):
        self.save(amount='12')
        self.assertEqual(self.ledger.query('other','car','2026-09-20')['entries'],[])
        self.assertEqual(self.ledger.query('owner','other','2026-09-20')['entries'],[])
        encoded=json.dumps(self.query(),allow_nan=False)
        for private in ('scope_key','vehicle_key','vin','address','coordinates'):
            self.assertNotIn(private,encoded)


if __name__=='__main__':unittest.main()
