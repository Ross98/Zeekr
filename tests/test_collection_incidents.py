"""Outage evidence must distinguish a network status success from cached data."""
from pathlib import Path
import tempfile
import unittest
from zeekr_control.client import QueryOutcome
from zeekr_control.collection_incidents import CollectionIncidents

BASE=1792710000000


class CollectionIncidentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.incidents=CollectionIncidents(Path(self.tmp.name))

    def test_cache_and_list_do_not_close_outage_and_fresh_state_is_separate(self):
        row=self.incidents.failure('owner','car','session',BASE,BASE-1000,BASE-2000)
        for outcome in (QueryOutcome(operation='vehicles',actual_request=True,success_code='1000',schema_valid=True),
                        QueryOutcome(operation='status',cache_hit=True,success_code='1000',schema_valid=True)):
            self.incidents.success('owner','car','session',outcome,BASE+1000,BASE)
            self.assertIsNotNone(self.incidents.current('owner','car'))
        good=QueryOutcome(operation='status',actual_request=True,success_code='1000',schema_valid=True)
        self.incidents.success('owner','car','session',good,BASE+2000,BASE-1000)
        saved=self.incidents.read(row['id'])
        self.assertEqual(saved['interface_recovered_at'],BASE+2000)
        self.assertIsNone(saved['fresh_state_seen_at'])
        self.incidents.success('owner','car','session',good,BASE+3000,BASE+2500)
        self.assertEqual(self.incidents.read(row['id'])['fresh_state_seen_at'],BASE+3000)

    def test_restarts_counters_and_next_outage_do_not_invent_freshness(self):
        row=self.incidents.failure('owner','car','old',BASE,BASE-1000,BASE-2000)
        restarted=CollectionIncidents(self.incidents.root)
        row=restarted.failure('owner','car','old',BASE+60000,BASE-1000,BASE-2000)
        self.assertEqual(row['attempts'],2)
        good=QueryOutcome(operation='status',actual_request=True,success_code='1000',schema_valid=True)
        restarted.success('owner','car','new',good,BASE+61000,BASE-1000)
        newer=restarted.failure('owner','car','new',BASE+70000,BASE-1000,BASE+61000)
        self.assertNotEqual(newer['id'],row['id'])
        self.assertEqual(restarted.read(row['id'])['fresh_state_outcome'],'not_observed_before_next_outage')
        self.assertIsNone(restarted.current('other','car'))
