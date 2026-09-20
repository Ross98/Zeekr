import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.tracks import day_bounds
import test_usage_reports as usage_fixtures


class AnalysisTests(unittest.TestCase):
    setUp = usage_fixtures.UsageReportsTests.setUp
    add = usage_fixtures.UsageReportsTests.add

    def analyzer(self):
        from zeekr_control.automatic_insights import Analyzer
        return Analyzer(self.db, self.archive)

    def result(self):
        return self.analyzer().build('owner', 'car', day_bounds('2026-09-20')[0] + 12*3600000)

    def test_weighted_energy_compares_disjoint_windows_and_requires_samples(self):
        for i in range(5): self.add('base%d' % i, day='2026-09-01', distance_km=40)
        for i, distance in enumerate((20, 40, 60)):
            self.add('recent%d' % i, distance_km=distance)
        energy = self.result()['energy']
        self.assertEqual(energy['status'], 'ready')
        self.assertEqual(energy['recent']['samples'], 3)
        self.assertEqual(energy['baseline']['samples'], 5)
        self.assertAlmostEqual(energy['recent']['kwh_per_100km'], 21.5)
        self.assertEqual(energy['change_percent'], 0)

    def test_valid_partial_contributes_but_invalid_short_future_other_vehicle_do_not(self):
        for i, changes in enumerate(({'partial': True}, {'battery_capacity_kwh': None},
                {'distance_km': 2}, {'soc_delta': -2, 'end_soc': 68},
                {'vehicle': 'other'}, {'day': '2026-09-21'})):
            self.add(str(i), **changes)
        energy = self.result()['energy']
        self.assertEqual(energy['status'], 'insufficient')
        self.assertEqual(energy['recent']['samples'], 1)
        self.assertEqual(energy['recent']['partial_samples'], 1)
        self.assertEqual(energy['recent']['excluded'], 3)
        self.assertIsNotNone(energy['recent']['kwh_per_100km'])
        self.assertIsNone(energy['change_percent'])

    def test_utc_year_boundary_uses_beijing_calendar_and_no_future(self):
        now = day_bounds('2027-01-01')[0]
        result = self.analyzer().build('owner', 'car', now)
        self.assertEqual(result['start_date'], '2026-12-05')
        self.assertEqual(result['recent_start_date'], '2026-12-26')
        self.assertEqual(result['end_date'], '2027-01-01')
        self.assertEqual(result['quality']['elapsed_slots'], 289)

    def test_charging_groups_keep_unknown_separate_and_exclude_bad_soc(self):
        for i in range(5):
            self.add('ac%d' % i, kind='charge_end', start_soc=20+i*5, end_soc=80,
                     soc_delta=60-i*5, partial=i == 0, report_v2={'start': {'charging_mode': 'ac'}})
        self.add('unknown', kind='charge_end', start_soc=40, end_soc=80, soc_delta=40)
        self.add('bad', kind='charge_end', start_soc=40, end_soc=80, soc_delta=39)
        groups = self.result()['charging']['groups']
        self.assertEqual(groups['ac']['samples'], 5)
        self.assertEqual(groups['ac']['partial_samples'], 1)
        self.assertEqual(groups['ac']['start_soc'], {'p25': 25, 'median': 30, 'p75': 35})
        self.assertEqual(groups['unknown']['samples'], 1)
        self.assertIsNone(groups['unknown']['start_soc'])
        self.assertEqual(self.result()['charging']['excluded'], 1)

    def test_quality_failure_does_not_hide_valid_energy_and_has_no_exception_text(self):
        with patch('zeekr_control.automatic_insights.DataQuality.query', side_effect=ValueError('PRIVATE-RAW')):
            result = self.result()
        self.assertEqual(result['quality']['status'], 'error')
        self.assertEqual(result['energy']['status'], 'insufficient')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_trashed_trips_are_excluded_and_revision_change_during_scan_is_rejected(self):
        from zeekr_control.automatic_insights import Analyzer
        self.add()
        with self.analyzer().events.connect() as db:
            self.assertIsNotNone(db)
        import sqlite3
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE trip_record_trash (vehicle TEXT,event_id TEXT)')
            db.execute('INSERT INTO trip_record_trash VALUES (?,?)', ('car', 'trip'))
        self.assertEqual(self.result()['energy']['recent']['samples'], 0)
        with patch.object(Analyzer, 'revision', side_effect=[0, 1]):
            with self.assertRaises(ValueError): self.result()

    def test_output_contains_no_event_ids_locations_or_raw_fields(self):
        self.add('PRIVATE-ID')
        encoded = json.dumps(self.result(), allow_nan=False)
        for value in ('PRIVATE', 'latitude', 'longitude', 'battery_capacity_kwh', 'scope'):
            self.assertNotIn(value, encoded)

    def test_new_evidence_updates_saved_results_next_hour_without_web_requests(self):
        from zeekr_control.automatic_insights import InsightCache, InsightWorker, INTERVAL_MS
        analyzer = self.analyzer()
        cache = InsightCache(self.root/'automatic-insights.json')
        worker = InsightWorker(analyzer, cache); self.addCleanup(worker.close)
        now = day_bounds('2026-09-20')[0]+12*3600000
        self.add('first')
        worker.start('owner', 'car', now, lambda: True); worker.thread.join(2)
        self.assertEqual(cache.query('owner', 'car', now, 0)['report']['energy']['recent']['samples'], 1)
        self.add('next')
        worker.start('owner', 'car', now+60000, lambda: True); worker.thread.join(2)
        self.assertEqual(cache.query('owner', 'car', now+60000, 0)['report']['energy']['recent']['samples'], 1)
        worker.start('owner', 'car', now+INTERVAL_MS, lambda: True); worker.thread.join(2)
        saved = cache.query('owner', 'car', now+INTERVAL_MS, 0)
        self.assertEqual(saved['report']['energy']['recent']['samples'], 2)
        self.assertEqual(saved['report']['generated_at'], now+INTERVAL_MS)


class CacheAndWorkerTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.automatic_insights import Analyzer, InsightCache
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = InsightCache(self.root / 'automatic-insights.json')
        self.now = day_bounds('2026-09-20')[0] + 12*3600000
        self.analyzer = Analyzer(self.root/'tracks.sqlite3', ArchiveReader(self.root/'snapshot-archive'))
        self.result = self.analyzer.build('owner', 'car', self.now)

    def test_empty_read_is_readonly_success_is_private_and_scoped(self):
        self.assertEqual(self.cache.query('owner', 'car', self.now, 0)['status'], 'waiting')
        self.assertFalse(self.cache.path.exists())
        self.cache.success('owner', 'car', self.now, self.result)
        self.assertEqual(self.cache.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.cache.query('owner', 'car', self.now, 0)['report'], self.result)
        self.assertIsNone(self.cache.query('different', 'car', self.now, 0)['report'])
        self.assertIsNone(self.cache.query('owner', 'other', self.now, 0)['report'])

    def test_failure_retains_previous_success_and_retry_deadline_survives_restart(self):
        from zeekr_control.automatic_insights import InsightCache, INTERVAL_MS
        self.cache.success('owner', 'car', self.now, self.result)
        self.cache.failure('owner', 'car', self.now + INTERVAL_MS)
        reopened = InsightCache(self.cache.path)
        data = reopened.query('owner', 'car', self.now + INTERVAL_MS, 0)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['report']['generated_at'], self.now)
        self.assertFalse(reopened.due('owner', 'car', self.now + INTERVAL_MS + 1, 0))
        self.assertTrue(reopened.due('owner', 'car', self.now + 2*INTERVAL_MS, 0))

    def test_management_revision_hides_old_stats_and_forces_recompute(self):
        self.cache.success('owner', 'car', self.now, self.result)
        self.assertTrue(self.cache.due('owner', 'car', self.now + 1, 1))
        state = self.cache.query('owner', 'car', self.now + 1, 1)
        self.assertEqual(state['status'], 'changed')
        self.assertIsNone(state['report'])

    def test_future_clock_and_algorithm_change_cannot_claim_freshness(self):
        self.cache.success('owner', 'car', self.now, self.result)
        self.assertTrue(self.cache.due('owner', 'car', self.now - 1, 0))
        self.assertEqual(self.cache.query('owner', 'car', self.now - 1, 0)['status'], 'stale')
        with patch('zeekr_control.automatic_insights.VERSION', self.result['version']+1):
            self.assertTrue(self.cache.due('owner', 'car', self.now + 1, 0))
            self.assertIsNone(self.cache.query('owner', 'car', self.now + 1, 0)['report'])
            self.cache.failure('owner', 'car', self.now + 1)
            self.assertIsNone(self.cache.query('owner', 'car', self.now + 1, 0)['report'])

    def test_old_schema_is_hidden_and_rebuilt_without_reusing_old_failure_report(self):
        from zeekr_control.automatic_insights import InsightWorker
        from zeekr_control.storage import load, save
        self.cache.success('owner', 'car', self.now, self.result)
        saved = load(self.cache.path)
        saved.update(version='0', report=json.dumps({'version': 0}))
        save(self.cache.path, saved)
        self.assertTrue(self.cache.due('owner', 'car', self.now+1, 0))
        self.assertEqual(self.cache.query('owner', 'car', self.now+1, 0)['status'], 'changed')
        self.cache.failure('owner', 'car', self.now+1)
        state = self.cache.query('owner', 'car', self.now+1, 0)
        self.assertEqual(state['status'], 'error')
        self.assertIsNone(state['report'])
        save(self.cache.path, saved)
        worker = InsightWorker(self.analyzer, self.cache); self.addCleanup(worker.close)
        worker.start('owner', 'car', self.now+2, lambda: True); worker.thread.join(2)
        self.assertEqual(self.cache.query('owner', 'car', self.now+2, 0)['report'], self.analyzer.build('owner', 'car', self.now+2))

    def test_unsafe_links_and_oversized_cache_are_rejected(self):
        self.cache.success('owner', 'car', self.now, self.result)
        os.link(self.cache.path, self.root/'hardlink')
        with self.assertRaises(OSError): self.cache.query('owner', 'car', self.now, 0)
        with self.assertRaises(OSError): self.cache.success('owner', 'car', self.now, self.result)
        (self.root/'hardlink').unlink()
        self.cache.path.write_text('x'*131073)
        with self.assertRaises(ValueError): self.cache.query('owner', 'car', self.now, 0)

    def test_cache_projects_unknown_fields_out_and_rejects_nonfinite_values(self):
        self.result['PRIVATE-RAW'] = 'PRIVATE-SECRET'
        self.result['energy']['PRIVATE-RAW'] = 'PRIVATE-SECRET'
        self.cache.success('owner', 'car', self.now, self.result)
        self.assertNotIn('PRIVATE', json.dumps(self.cache.query('owner', 'car', self.now, 0)))
        self.result['energy']['change_percent'] = float('nan')
        with self.assertRaises(ValueError): self.cache.success('owner', 'car', self.now, self.result)

    def test_worker_is_single_flight_nonblocking_and_discards_switched_context(self):
        from zeekr_control.automatic_insights import InsightWorker
        entered, release = threading.Event(), threading.Event()
        allowed = [True]
        def build(*args):
            entered.set(); release.wait(3); return self.result
        worker = InsightWorker(self.analyzer, self.cache)
        self.addCleanup(worker.close)
        with patch.object(self.analyzer, 'build', side_effect=build):
            self.assertTrue(worker.start('owner', 'car', self.now, lambda: allowed[0]))
            self.assertTrue(entered.wait(1))
            self.assertFalse(worker.start('owner', 'car', self.now, lambda: True))
            allowed[0] = False; release.set(); worker.thread.join(2)
        self.assertFalse(self.cache.path.exists())

    def test_worker_failure_and_closed_worker_cannot_affect_collection(self):
        from zeekr_control.automatic_insights import InsightWorker
        worker = InsightWorker(self.analyzer, self.cache)
        with patch.object(self.analyzer, 'build', side_effect=RuntimeError('PRIVATE')):
            self.assertTrue(worker.start('owner', 'car', self.now, lambda: True))
            worker.thread.join(2)
        self.assertEqual(self.cache.query('owner', 'car', self.now, 0)['status'], 'error')
        self.assertNotIn('PRIVATE', self.cache.path.read_text())
        worker.close()
        self.assertFalse(worker.start('owner', 'car', self.now + 3600000, lambda: True))

    def test_worker_success_does_not_repeat_during_same_hour(self):
        from zeekr_control.automatic_insights import InsightWorker
        worker = InsightWorker(self.analyzer, self.cache); self.addCleanup(worker.close)
        with patch.object(self.analyzer, 'build', wraps=self.analyzer.build) as build:
            self.assertTrue(worker.start('owner', 'car', self.now, lambda: True)); worker.thread.join(2)
            worker.start('owner', 'car', self.now + 60000, lambda: True); worker.thread.join(2)
            self.assertEqual(build.call_count, 1)

    def test_slow_cache_check_is_off_collection_thread_and_close_discards_work(self):
        import time
        from zeekr_control.automatic_insights import InsightWorker
        entered, release = threading.Event(), threading.Event()
        worker = InsightWorker(self.analyzer, self.cache)
        def due(*args):
            entered.set(); release.wait(2); return True
        with patch.object(self.cache, 'due', side_effect=due):
            started = time.monotonic()
            worker.start('owner', 'car', self.now, lambda: True)
            elapsed = time.monotonic()-started
            self.assertTrue(entered.wait(1))
            worker.close(); release.set(); worker.thread.join(2)
            self.assertLess(elapsed, .5)
        self.assertFalse(self.cache.path.exists())


if __name__ == '__main__': unittest.main()
