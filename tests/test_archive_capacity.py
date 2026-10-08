"""Dense synthetic month, bounded pages, and frozen-read consistency."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from zeekr_control.archive_reader import ArchiveChanged, ArchiveReader
from zeekr_control.data_quality import DataQuality
from zeekr_control.snapshot_archive import SnapshotArchive
from zeekr_control.tracks import day_bounds
from zeekr_control.usage_calendar import UsageCalendar
from zeekr_control.usage_reports import UsageReports


class ArchiveCapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private' / 'snapshot-archive'
        self.start = day_bounds('2026-10-01')[0]
        self.end = day_bounds('2026-11-01')[0]
        raw = {'updateTime': self.start, 'basicVehicleStatus': {'engineStatus': 'engine_off',
               'speedValidity': True, 'speed': 0}, 'additionalVehicleStatus': {
               'electricVehicleStatus': {'ptReady': 0, 'chargeSts': 0, 'chargerState': 0,
               'statusOfChargerConnection': 0, 'chargeLevel': 70}}}
        SnapshotArchive(self.root).append('owner', 'car', json.dumps(raw), self.start,
                                          self.start, self.start, 'monitor')
        self.reader = ArchiveReader(self.root)
        self.path = self.root / '2026' / '10.sqlite3'

    def populate(self, count, step=30000):
        with sqlite3.connect(self.path) as db:
            digest = db.execute('SELECT digest FROM reads LIMIT 1').fetchone()[0]
            db.executemany('INSERT INTO reads(scope_key,vehicle_key,state_time,fetched_at,observed_at,source,digest) '
                           'VALUES(?,?,?,?,?,?,?)', (('owner', 'car', self.start, self.start+i*(step or 1),
                           self.start+i*step, 'monitor', digest) for i in range(1, count)))

    def test_full_stream_exceeds_old_cap_and_explicit_limit_still_rejects(self):
        self.populate(50001)
        self.assertEqual(sum(1 for _ in self.reader.iter_metadata('owner', 'car', self.start,
                         self.end, limit=None)), 50001)
        with self.assertRaises(ValueError):
            list(self.reader.iter_metadata('owner', 'car', self.start, self.end, limit=1))

    def test_new_rows_between_pages_are_excluded_even_when_backdated(self):
        self.populate(1025)
        stream = self.reader.iter_metadata('owner', 'car', self.start, self.end, limit=None)
        first = next(stream)
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO reads(scope_key,vehicle_key,state_time,fetched_at,observed_at,source,digest) '
                       'SELECT scope_key,vehicle_key,state_time,fetched_at+1,observed_at+1,source,digest '
                       'FROM reads WHERE id=700')
        rows = [first, *stream]
        self.assertEqual(len(rows), 1025)
        self.assertEqual(len({row['key'] for row in rows}), 1025)
        self.assertEqual(rows[512]['change'], 'repeat')

    def test_month_calendar_and_report_do_not_reject_legitimate_capacity(self):
        self.populate(50001)
        database = Path(self.temp.name) / 'missing.sqlite3'
        calendar = UsageCalendar(database, self.reader).query('owner', 'car', '2026-10-01', now=self.end)
        report = UsageReports(database, self.reader).query('owner', 'car', 'month', '2026-10-01', now=self.end)
        self.assertEqual(sum(day['reads'] for day in calendar['days']), 50001)
        self.assertEqual(report['current']['coverage']['reads'], 50001)

    def test_month_quality_reads_all_samples_and_preserves_exact_statistics(self):
        self.populate(50001)
        result = DataQuality(self.reader, clock=lambda:self.end).query('owner', 'car', '2026-10-01', '2026-10-31')
        self.assertEqual(result['reads'], 50001)
        self.assertEqual(result['delay']['sample_count'], 50001)
        self.assertEqual(result['delay']['p50_seconds'], 750000)
        self.assertEqual(result['delay']['p95_seconds'], 1425000)
        self.assertEqual(result['delay']['max_seconds'], 1500000)
        self.assertEqual(result['delay']['mean_seconds'], 750000)
        self.assertEqual(len(result['gaps']), 1)
        self.assertEqual(result['gaps'][0]['kind'], 'trailing')

    def test_same_timestamp_page_boundary_keeps_every_revision(self):
        self.populate(1025, step=0)
        rows = list(self.reader.iter_metadata('owner', 'car', self.start, self.end, limit=None))
        self.assertEqual(len(rows), 1025)
        self.assertTrue(all(row['change'] == 'repeat' for row in rows[1:]))
        self.assertEqual(rows[-1]['key'], '202610.1025')

    def test_replaced_shard_is_retryable_instead_of_an_empty_result(self):
        self.populate(1025)
        stream = self.reader.iter_metadata('owner', 'car', self.start, self.end, limit=None)
        next(stream)
        self.path.rename(self.path.with_suffix('.removed'))
        with self.assertRaises(ArchiveChanged):
            list(stream)

    def test_adjacent_month_is_frozen_before_yielding_first_page(self):
        next_start = day_bounds('2026-11-01')[0]
        writer = SnapshotArchive(self.root)
        raw = {'updateTime': next_start}
        writer.append('owner','car',json.dumps(raw),next_start,next_start,next_start,'monitor')
        stream = self.reader.iter_metadata('owner','car',self.start,next_start+60000,limit=None)
        first = next(stream)
        writer.append('owner','car',json.dumps(raw),next_start,next_start+30000,next_start+30000,'monitor')
        rows = [first,*stream]
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[-1]['change'],'new')
