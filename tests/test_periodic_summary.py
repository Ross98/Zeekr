import unittest

import test_usage_reports as fixtures
from zeekr_control.personal_store import PersonalStore
from zeekr_control.tracks import day_bounds
from zeekr_control.periodic_summary import PeriodicSummary


class PeriodicSummaryTests(unittest.TestCase):
    setUp = fixtures.UsageReportsTests.setUp
    add = fixtures.UsageReportsTests.add
    def query_period(self, period='day', date='2026-09-15', now=None):
        return PeriodicSummary(self.db,self.archive,PersonalStore(self.root/'personal.sqlite3')).query(
            'owner','car','owner',period,date,now=self.now if now is None else now)

    def test_closed_period_and_boundary_excludes_next_day(self):
        self.add()
        self.add('next',day='2026-09-16')
        result=self.query_period()
        self.assertEqual(result['metrics']['distance_km'],40)
        self.assertEqual(result['end_date'],'2026-09-15')
        with self.assertRaises(ValueError):self.query_period(now=self.day+9*3600000)
        self.assertEqual(self.query_period(now=day_bounds('2026-09-16')[0])['metrics']['trip_count'],1)

    def test_calendar_month_week_and_cross_midnight(self):
        self.add(day='2026-09-14',start_time=self.day-60000,end_time=self.day+60000,duration_seconds=120)
        self.add('outside',day='2026-09-21')
        result=self.query_period('week','2026-09-20')
        self.assertEqual((result['start_date'],result['end_date']),('2026-09-14','2026-09-20'))
        self.assertEqual(result['metrics']['trip_count'],1)
        self.assertEqual(self.query_period('month','2024-02-20')['end_date'],'2024-02-29')

    def test_missing_zero_and_private_payment(self):
        self.assertIsNone(self.query_period()['metrics']['distance_km'])
        self.add(distance_km=0,partial=True,soc_delta=None)
        store=PersonalStore(self.root/'personal.sqlite3')
        body=dict(date='2026-09-15',actual_cents=1234,note='PRIVATE-NOTE',event=None)
        store.change('owner','car','charges','save','one',body,0)
        store.change('owner','car','charges','save','two',dict(body,actual_cents=None),1)
        result=self.query_period()
        self.assertEqual(result['metrics']['distance_km'],0)
        self.assertEqual(result['metrics']['charging_paid_cents'],1234)
        self.assertEqual(result['quality']['unpriced_bill_count'],1)
        self.assertEqual(result['quality']['partial_trip_count'],1)
        self.assertNotIn('PRIVATE',str(result))


if __name__=='__main__':unittest.main()
