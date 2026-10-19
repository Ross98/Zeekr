"""Payload selection must preserve the complete v6 response, including gaps."""
import tempfile
import copy
import random
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from benchmark_parking_ranges import CASES, DAY, START, QUERY, raw, seed, run_case
from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.parking_analytics import payload_windows
from zeekr_control.parking_events import build_events, observation_time
from zeekr_control.snapshot_archive import SnapshotArchive
from test_parking_streaming import sample


class ParkingReadPlanTests(unittest.TestCase):
    def test_selection_matches_full_v6_with_late_cache_revisions_and_location_changes(self):
        rng = random.Random(12019)
        for case in range(60):
            trips = [dict(id=str(index), kind='trip_end', start_time=START+int(a*DAY),
                          end_time=START+int(b*DAY), start_soc=70, end_soc=70, partial=False)
                     for index, (a, b) in enumerate(rng.choice(list(CASES.values())))]
            windows = payload_windows(trips, QUERY, QUERY+DAY)
            rows = []
            for index in range(120):
                row = sample(index)
                stamp = START + rng.randrange(90*24)*3600000
                observed = START + index*90*DAY//120
                row['record'].update(state_time=stamp, observed_at=observed,
                                     flags=rng.choice([[], [], ['stale']]),
                                     change=rng.choice(['new', 'repeat', 'revision', 'regression']))
                if rng.randrange(5) == 0:row['record']['state_time'] = None
                row['location']['latitude'] += rng.choice([0, 0, .00002, .02])
                row['state']['charging'] = rng.choice([False, False, True, None])
                rows.append(row)
            projected = copy.deepcopy(rows)
            for row in projected:
                stamp = observation_time(row)
                if not any(left <= stamp <= right for left, right in windows):
                    row.update(state={}, location=None, inside_temp=None, inside_time=None)
            with self.subTest(case=case):
                self.assertEqual(build_events(trips, [], projected, QUERY, QUERY+DAY, 86),
                                 build_events(trips, [], rows, QUERY, QUERY+DAY, 86))

    def test_missing_boundaries_skip_unrelated_bodies_without_changing_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            seed(root, cadence=3600000)
            # Collected far outside the query, but vehicle time falls inside a
            # relevant parking event. Its contradictory body must not be skipped.
            stamp, observed = QUERY+13*3600000, START+89*DAY+1000
            body = raw(stamp)
            body['additionalVehicleStatus']['maintenanceStatus']['odometer'] = 2000
            SnapshotArchive(root/'archive').append('owner', 'car', json.dumps(body), stamp,
                                                   observed, observed, 'monitor')
            original = ArchiveReader.iter_records
            def full(reader, *args, **kwargs):
                kwargs.pop('payload_when', None)
                return original(reader, *args, **kwargs)
            for name, trips in CASES.items():
                with self.subTest(case=name):
                    with patch.object(ArchiveReader, 'iter_records', full):
                        expected = run_case(root, name, trips)
                    (root/(name+'.sqlite3')).unlink()
                    actual = run_case(root, name, trips)
                    self.assertEqual(actual['result_sha256'], expected['result_sha256'])
                    self.assertEqual(actual['metadata_rows'], expected['metadata_rows'])
                    if name in ('missing_both_crossing_trip', 'missing_before', 'missing_after'):
                        self.assertLess(actual['payload_decodes'], expected['payload_decodes']//20)
                    else:
                        if name.startswith('missing_'):
                            self.assertLess(actual['payload_decodes'], expected['payload_decodes']*.7)
                        else:
                            self.assertEqual(actual['payload_decodes'], expected['payload_decodes'])
                        self.assertEqual(len(actual['events']), 1)
                        self.assertGreater(actual['events'][0]['gap_count'], 0)
                        self.assertIsNone(actual['events'][0]['soc_drop'])


if __name__ == '__main__':
    unittest.main()
