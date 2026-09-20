import json
import unittest

import test_usage_reports as fixtures


class TripCardTests(unittest.TestCase):
    add=fixtures.UsageReportsTests.add

    def setUp(self):
        fixtures.UsageReportsTests.setUp(self)
        from zeekr_control.trip_cards import TripCards
        self.cards=TripCards(self.db,clock=lambda:self.now)

    def test_month_choices_keep_only_safe_ended_current_vehicle_events(self):
        self.add();self.add('charge','charge_end',start_soc=30,end_soc=80,soc_delta=50)
        self.add('partial',partial=True);self.add('other',vehicle='other');self.add('future',day='2026-09-25')
        self.now=self.day+10*3600000
        result=self.cards.query('car','2026-09-20')
        self.assertEqual({r['id'] for r in result['trips']},{'trip','partial'})
        self.assertEqual(len(result['charges']),1)
        for secret in ('PRIVATE','coordinates','vin','latitude','address','message'):
            self.assertNotIn(secret,json.dumps(result))

    def test_charge_and_trip_are_not_automatically_associated(self):
        self.add();self.add('charge','charge_end')
        result=self.cards.query('car','2026-09-20')
        self.assertNotIn('charge_id',result['trips'][0])
        self.assertNotIn('trip_id',result['charges'][0])

    def test_readonly_and_month_validation(self):
        self.add();before=self.db.read_bytes()
        self.cards.query('car','2026-09-20')
        self.assertEqual(self.db.read_bytes(),before)
        with self.assertRaises(ValueError):self.cards.query('car','invalid')


if __name__=='__main__':unittest.main()
