"""Long parking must complete under the same bounded scratch budget."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from parking_quota_workload import matrix_plans, seed_archive, seed_events
from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.analysis_work import AnalysisCapacity, SampleStore, WorkDatabase
from zeekr_control.parking_analytics import ParkingAnalytics
import zeekr_control.parking_analytics as analytics


class ParkingCompactWorkspaceTests(unittest.TestCase):
    def test_compact_records_preserve_public_fields_types_and_extensions(self):
        record = dict(key='202608.7', state_time=1785513600000,
                      fetched_at=1785513601000, observed_at=1785513602000,
                      source='monitor', change='revision', flags=['stale'],
                      gap_seconds=601.0, delay_seconds=1.0)
        for changes in ({}, {'state_time': None}, {'state_time': True},
                        {'future_metadata': {'retained': [1, None, 'value']}}):
            original = dict(record, **changes)
            with self.subTest(changes=changes):
                with SampleStore(iter([dict(record=original, state={}, location=None)]),
                                 compact=True) as work:
                    actual = work.raw().first()['record']
                self.assertEqual(actual, original)
                self.assertIs(type(actual['state_time']), type(original['state_time']))

    def test_month_query_retains_ninety_day_event_in_fixed_scratch_budget(self):
        plan = copy.deepcopy(next(p for p in matrix_plans()
                                  if p['case'] == 'month-long-none'))
        plan['cadence_ms'] = 3600000
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o700)
            seed_archive(root, plan)
            seed_events(root, plan)

            def query():
                return ParkingAnalytics(ArchiveReader(root/'archive'),
                    root/'events'/(plan['case']+'.sqlite3')).query(
                        'synthetic', 'car', '2026-08-01', '2026-08-31', 86)

            # Keep the existing full-record representation as the output oracle.
            with patch.object(analytics, 'SampleStore',
                              side_effect=lambda samples, **options: SampleStore(samples)):
                expected = query()
            original_enter = WorkDatabase.__enter__

            def limited_enter(work):
                result = original_enter(work)
                work.db.execute('PRAGMA max_page_count=256')  # Same 1 MiB for every work DB.
                return result

            with patch.object(WorkDatabase, '__enter__', limited_enter):
                try:
                    actual = query()
                except AnalysisCapacity:
                    self.fail('A month query cannot retain the full 90-day parking event '
                              'within the fixed 1 MiB scratch budget')
            self.assertEqual(actual, expected)
            event = actual['events'][0]
            self.assertEqual(event['start_time'], 1782835200000)
            self.assertEqual(event['duration_seconds'], 90*86400-3600)
            self.assertGreater(event['gap_count'], 0)
            self.assertIsNone(event['soc_drop'])
            self.assertIsNone(event['estimated_kwh'])


if __name__ == '__main__':
    unittest.main()
