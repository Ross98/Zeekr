import tempfile
import unittest
import json
from unittest.mock import patch
from pathlib import Path

from capacity_workload import seed_archive, monthly_report, summarize_collection, web_work
from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.tracks import day_bounds


class CapacityWorkloadTests(unittest.TestCase):
    def test_web_progress_survives_an_interrupted_later_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'private'
            seed_archive(root, 31)
            with patch('zeekr_control.usage_reports.UsageReports.query',
                       side_effect=RuntimeError('interrupted query')):
                with self.assertRaisesRegex(RuntimeError, 'interrupted query'):
                    web_work(root)
            path = root / 'web-progress.json'
            self.assertTrue(path.exists(), 'Completed stages must survive worker failure')
            progress = json.loads(path.read_text())
            self.assertEqual(progress['active_stage'], 'month_report')
            self.assertEqual(progress['stages'][0]['name'], 'calendar')
            self.assertEqual(progress['stages'][0]['status'], 'completed')
            self.assertEqual(progress['stages'][1]['status'], 'running')
            self.assertGreaterEqual(progress['stages'][0]['seconds'], 0)

    def test_web_progress_records_all_validated_stages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'private'
            seed_archive(root, 31)
            result = web_work(root)
            path = root / 'web-progress.json'
            self.assertTrue(path.exists())
            progress = json.loads(path.read_text())
            self.assertIsNone(progress['active_stage'])
            self.assertEqual([stage['name'] for stage in progress['stages']],
                             ['calendar', 'month_report', 'parking'])
            self.assertTrue(all(s['status'] == 'completed' for s in progress['stages']))
            self.assertEqual(result['records'], 31)
    def test_fixture_and_monthly_query_include_every_synthetic_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'private'
            seed_archive(root, 31)
            reads = ArchiveReader(root / 'snapshot-archive').iter_metadata(
                'owner', 'car', day_bounds('2026-10-01')[0], day_bounds('2026-11-01')[0], limit=None)
            self.assertEqual(sum(1 for _ in reads), 31)
            result = monthly_report(root)
            self.assertEqual(result['observed_days'], 1)
            self.assertFalse(result['archive_limited'])
            self.assertGreater(result['png_bytes'], 1000)

    def test_collection_summary_requires_progress_during_image_work(self):
        result = summarize_collection([0.05, 0.2, 0.1], 3, 2, 1234)
        self.assertEqual(result['ticks'], 3)
        self.assertEqual(result['ticks_during_image'], 2)
        self.assertEqual(result['max_tick_seconds'], 0.2)
        with self.assertRaises(ValueError):
            summarize_collection([0.05], 1, 0, 1234)

    def test_collection_summary_rejects_missing_reads_and_failed_image(self):
        for reads, image in [(1, 1234), (2, 0)]:
            with self.subTest(reads=reads, image=image), self.assertRaises(ValueError):
                summarize_collection([0.1, 0.1], reads, 1, image)
