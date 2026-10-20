"""Small real-archive contracts for the offline Z15 measurement harness."""
import copy
from pathlib import Path
import tempfile
import unittest

from parking_quota_workload import (matrix_plans, seed_archive, seed_events,
                                    query_once, check_contract, cancel_probe)


class ParkingQuotaWorkloadTests(unittest.TestCase):
    def test_matrix_has_all_sixteen_distinct_cells(self):
        plans = matrix_plans()
        self.assertEqual(len(plans), 16)
        self.assertEqual(len({(p['range'], p['history'], p['boundary']) for p in plans}), 16)
        self.assertEqual({p['boundary'] for p in plans}, {'complete', 'missing_before', 'missing_after', 'none'})
        self.assertEqual({(p['history_upper']-p['history_lower'])//86400000 for p in plans}, {31, 90})
        self.assertTrue(all(p['cadence_ms'] == 10000 for p in plans))

    def test_real_cached_gap_preserves_full_events_and_complete_response(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            plans = [copy.deepcopy(p) for p in matrix_plans() if p['range'] == 'day' and p['history'] == 'long']
            for p in plans:
                p.update(history_lower=p['query_lower']-3600000,
                         history_upper=p['query_upper']+3600000, cadence_ms=300000)
            seed_archive(root, plans[0])
            for p in plans:
                seed_events(root, p)
                actual = query_once(root, p)
                reference = query_once(root, p, full_payload=True)
                self.assertEqual(actual['response'], reference['response'])
                self.assertEqual(actual['response_sha256'], reference['response_sha256'])
                check_contract(actual['response'], p)
                event = actual['response']['events'][0]
                self.assertGreater(event['gap_count'], 0)
                self.assertIsNone(event['soc_drop'])
                self.assertIsNone(event['estimated_kwh'])
                self.assertGreater(actual['counters']['event_rows'], 0)
                if p['boundary'] == 'none':
                    self.assertGreater(event['duration_seconds'], 86400)
                    self.assertEqual(actual['counters']['metadata_rows'], 312)

    def test_cancel_uses_jobs_and_drains_scratch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            p = copy.deepcopy(next(p for p in matrix_plans() if p['range']=='day' and p['boundary']=='none'))
            p.update(history_lower=p['query_lower']-3600000,
                     history_upper=p['query_upper']+3600000, cadence_ms=60000)
            seed_archive(root, p)
            seed_events(root, p)
            row = cancel_probe(root, p, threshold=20)
            self.assertTrue(row['cancelled'])
            self.assertTrue(row['slots_released'])
            self.assertLess(row['cleanup_seconds'], 2)
            self.assertEqual(row['scratch_remaining'], [])


if __name__ == '__main__':
    unittest.main()
