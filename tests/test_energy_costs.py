import unittest
from zeekr_control.energy_costs import estimate, summarize

def event(identity,kind,start,end,a,b,capacity=100,partial=False):
    delta=b-a if a is not None and b is not None else None
    energy=(delta if kind=='charge_end' else -delta)*capacity/100 if delta is not None else None
    return dict(id=identity,kind=kind,start_time=start,end_time=end,start_soc=a,end_soc=b,battery_capacity_kwh=capacity,
                estimated_kwh=energy,partial=partial)

class EnergyCostTests(unittest.TestCase):
    def test_actual_fee_includes_charging_loss_and_excludes_parking_fee(self):
        rows=[event('c','charge_end',1,2,0,20),event('t','trip_end',3,4,20,10)]
        costs=estimate(rows,{'c':dict(actual_cents=2500,metered_kwh=25,parking_fee_cents=900)})
        self.assertEqual(costs['t']['estimated_cents'],1250)
        self.assertEqual(costs['t']['reference_cents_per_kwh'],125)
        self.assertEqual(costs['t']['status'],'priced')

    def test_weighted_stock_changes_only_after_charge_and_consumption(self):
        rows=[event('c1','charge_end',1,2,0,20),event('t1','trip_end',3,4,20,10),
              event('c2','charge_end',5,6,10,30),event('t2','trip_end',7,8,30,20)]
        books={'c1':dict(actual_cents=2500,metered_kwh=25),'c2':dict(actual_cents=4000,metered_kwh=20)}
        costs=estimate(rows,books)
        self.assertEqual(costs['t1']['estimated_cents'],1250)
        self.assertEqual(costs['t2']['estimated_cents'],1750)

    def test_initial_unknown_and_missing_bill_remain_partial(self):
        rows=[event('c','charge_end',1,2,20,40),event('t','trip_end',3,4,40,20)]
        cost=estimate(rows,{'c':dict(actual_cents=2000,metered_kwh=20)})['t']
        self.assertEqual((cost['estimated_cents'],cost['known_kwh'],cost['unknown_kwh']),(1000,10,10))
        self.assertEqual(cost['status'],'partial')
        cost=estimate(rows,{})['t'];self.assertIsNone(cost['estimated_cents'])
        self.assertEqual(cost['unknown_kwh'],20)

    def test_known_free_zero_differs_from_unknown_price(self):
        rows=[event('c','charge_end',1,2,0,20),event('t','trip_end',3,4,20,10)]
        self.assertEqual(estimate(rows,{'c':dict(actual_cents=0,metered_kwh=20)})['t']['estimated_cents'],0)
        self.assertIsNone(estimate(rows,{'c':dict(actual_cents=None,metered_kwh=20)})['t']['estimated_cents'])

    def test_invalid_meter_does_not_price_stock(self):
        rows=[event('c','charge_end',1,2,0,20),event('t','trip_end',3,4,20,10)]
        for meter in (None,0,10):
            self.assertIsNone(estimate(rows,{'c':dict(actual_cents=2000,metered_kwh=meter)})['t']['estimated_cents'])
        rows[0]['partial']=True
        cost=estimate(rows,{'c':dict(actual_cents=2000,metered_kwh=25)})['t']
        self.assertEqual(cost['estimated_cents'],800)
        self.assertTrue(cost['loss_unknown'])

    def test_unknown_soc_gain_and_capacity_change_do_not_inherit_all_prices(self):
        rows=[event('c','charge_end',1,2,0,20),event('t','trip_end',3,4,40,20)]
        cost=estimate(rows,{'c':dict(actual_cents=2000,metered_kwh=20)})['t']
        self.assertEqual(cost['unknown_kwh'],10)
        rows[1]=event('t','trip_end',3,4,20,10,capacity=80)
        self.assertIsNone(estimate(rows,{'c':dict(actual_cents=2000,metered_kwh=20)})['t']['estimated_cents'])

    def test_parking_consumption_is_charged_once_and_overlap_is_unknown(self):
        rows=[event('c','charge_end',1,2,0,20),event('p','parking',3,4,20,19),event('t','trip_end',5,6,19,9)]
        books={'c':dict(actual_cents=2000,metered_kwh=20)}
        costs=estimate(rows,books)
        self.assertEqual((costs['p']['estimated_cents'],costs['t']['estimated_cents']),(100,1000))
        rows[2]['start_time']=3
        costs=estimate(rows,books)
        self.assertIsNone(costs['t']['estimated_cents'])

    def test_unknown_consumption_is_not_zero_and_zero_energy_can_be_zero(self):
        rows=[event('t','trip_end',1,2,None,None)]
        cost=estimate(rows,{})['t'];self.assertIsNone(cost['estimated_cents']);self.assertIsNone(cost['energy_kwh'])
        cost=estimate([event('t','trip_end',1,2,20,20)],{})['t']
        self.assertEqual(cost['estimated_cents'],0)

    def test_zero_energy_does_not_turn_unknown_consumption_into_zero_daily_cost(self):
        costs=estimate([event('zero','trip_end',1,2,20,20),event('unknown','trip_end',3,4,20,10)],{})
        rows=[dict(kind='trip_end',energy_cost=costs[key]) for key in ('zero','unknown')]
        self.assertIsNone(summarize(rows)['estimated_cents'])
        self.assertEqual(summarize(rows)['known_cents'],0)

    def test_known_free_energy_remains_partial_when_unknown_energy_exists(self):
        costs=estimate([event('c','charge_end',1,2,20,40),event('t','trip_end',3,4,40,20)],{'c':dict(actual_cents=0,metered_kwh=20)})
        summary=summarize([dict(kind='trip_end',energy_cost=costs['t'])])
        self.assertEqual(summary['estimated_cents'],0)
        self.assertGreater(summary['unknown_kwh'],0)

    def test_partial_charge_without_valid_energy_still_remains_unknown(self):
        rows=[event('c','charge_end',1,2,0,20,partial=True),event('t','trip_end',3,4,20,10)]
        rows[0]['estimated_kwh']=None
        self.assertIsNone(estimate(rows,{'c':dict(actual_cents=2000,metered_kwh=25)})['t']['estimated_cents'])
