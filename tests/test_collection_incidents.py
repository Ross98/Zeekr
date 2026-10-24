"""Outage evidence must distinguish a network status success from cached data."""
from pathlib import Path
import tempfile
import unittest
from zeekr_control.client import QueryOutcome
from zeekr_control.collection_incidents import CollectionIncidents

BASE=1792710000000


class CollectionIncidentTests(unittest.TestCase):
    def test_schema_initialization_failure_keeps_existing_database_unchanged(self):
        import sqlite3
        path=self.incidents.root/'collection-incidents.sqlite3'
        db=sqlite3.connect(path)
        try:
            db.execute('CREATE TABLE sentinel(value TEXT)')
            db.execute('CREATE INDEX probes ON sentinel(value)')
            db.commit()
        finally:db.close()
        path.chmod(0o600);before=path.read_bytes()
        with self.assertRaises(sqlite3.OperationalError):
            with self.incidents.connect():pass
        self.assertEqual(path.read_bytes(),before)

    def test_new_state_freshness_edges_and_first_seen_time_are_preserved(self):
        good=QueryOutcome(operation='status',actual_request=True,success_code='1000',schema_valid=True)
        for index,(offset,seen) in enumerate(((-180001,False),(-180000,True),
                                            (30000,True),(30001,False))):
            with self.subTest(offset=offset):
                vehicle='car-'+str(index)
                row=self.incidents.failure('owner',vehicle,'old',BASE-1000,BASE-200000)
                self.incidents.success('owner',vehicle,'new',good,BASE,BASE+offset)
                saved=self.incidents.read(row['id'])
                self.assertEqual(saved['interface_recovered_at'],BASE)
                self.assertEqual(saved['fresh_state_seen_at'],BASE if seen else None)
                if not seen:
                    self.incidents.success('owner',vehicle,'new',good,BASE+1000,BASE+500)
                self.incidents.success('owner',vehicle,'new',good,BASE+2000,BASE+1500)
                saved=self.incidents.read(row['id'])
                self.assertEqual(saved['interface_recovered_at'],BASE)
                self.assertEqual(saved['fresh_state_seen_at'],BASE if seen else BASE+1000)
                self.assertEqual(saved['fresh_vehicle_state_at'],BASE+offset if seen else BASE+500)

    def test_invalid_status_outcome_and_unchanged_state_cannot_claim_data_recovery(self):
        row=self.incidents.failure('owner','car','old',BASE-1000,BASE-500)
        for outcome in (QueryOutcome(operation='status',actual_request=True,success_code='1000'),
                        QueryOutcome(operation='status',actual_request=True,success_code='1509',schema_valid=True),
                        QueryOutcome(operation='status',success_code='1000',schema_valid=True)):
            self.assertFalse(self.incidents.success('owner','car','new',outcome,BASE,BASE))
            self.assertIsNone(self.incidents.read(row['id'])['interface_recovered_at'])
        good=QueryOutcome(operation='status',actual_request=True,success_code='1000',schema_valid=True)
        for state in (None,True,BASE-501,BASE-500):
            self.incidents.success('owner','car','new',good,BASE,state)
            self.assertIsNone(self.incidents.read(row['id'])['fresh_state_seen_at'])

    def test_verified_target_status_also_resolves_same_account_prebinding_outage(self):
        early=self.incidents.failure('owner','unbound','old',BASE)
        target=self.incidents.failure('owner','car','new',BASE+1000)
        other=self.incidents.failure('other','unbound','other',BASE)
        another_car=self.incidents.failure('owner','other-car','new',BASE)
        for outcome in (QueryOutcome(operation='vehicles',actual_request=True,success_code='1000',schema_valid=True),
                        QueryOutcome(operation='status',cache_hit=True,success_code='1000',schema_valid=True)):
            self.incidents.success('owner','car','new',outcome,BASE+2000,BASE)
            self.assertIsNotNone(self.incidents.current('owner','unbound'))
        good=QueryOutcome(operation='status',actual_request=True,success_code='1000',schema_valid=True)
        self.incidents.success('owner','car','new',good,BASE+3000,BASE+2500)
        for identity in (early['id'],target['id']):
            self.assertEqual(self.incidents.read(identity)['interface_recovered_at'],BASE+3000)
        self.assertEqual(self.incidents.read(early['id'])['vehicle'],'unbound')
        self.assertIsNone(self.incidents.read(other['id'])['interface_recovered_at'])
        self.assertIsNone(self.incidents.read(another_car['id'])['interface_recovered_at'])

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
