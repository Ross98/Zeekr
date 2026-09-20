"""Partial records contribute real observed metrics without rewriting events."""
import json
from pathlib import Path
import tempfile
import unittest

from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.charging_analytics import ChargingAnalytics
from zeekr_control.events import EventStore
from zeekr_control.monitor import Monitor
from zeekr_control.tracks import day_bounds
from zeekr_control.trip_tags import comparison
from zeekr_control.usage_events import UsageEvents, project
from zeekr_control.usage_reports import UsageReports


class PartialEventStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'tracks.sqlite3'
        self.monitor = Monitor(self.path)
        self.start, _ = day_bounds('2026-09-20')
        self.base = dict(start_time=self.start, end_time=self.start+3600000,
                         duration_seconds=3600, distance_km=20, start_soc=70,
                         end_soc=65, soc_delta=-5, partial=True, battery_capacity_kwh=86)

    def event(self, **changes):
        return project('partial', 'trip_end', dict(self.base, **changes))

    def test_partial_metrics_are_eligible_independently_of_completeness(self):
        event = self.event()
        self.assertTrue(event['partial'])
        self.assertEqual(event['distance_km'], 20)
        self.assertEqual(event['duration_seconds'], 3600)
        self.assertEqual(event['estimated_kwh'], 4.3)
        group = comparison('通勤', [event])
        self.assertEqual(group['distance_km']['samples'], 1)
        self.assertEqual(group['efficiency']['samples'], 1)
        self.assertEqual(group['efficiency']['value'], 21.5)

    def test_invalid_energy_does_not_discard_valid_distance(self):
        invalid = [dict(start_time=None), dict(start_time=self.base['end_time']+1),
                   dict(start_soc=None), dict(start_soc=True), dict(soc_delta=-4),
                   dict(end_soc=75, soc_delta=5), dict(battery_capacity_kwh=None),
                   dict(battery_capacity_kwh=float('nan')),
                   dict(report_v2={'profile_snapshot': {}}),
                   dict(report_v2={'metrics': {'charge_overlap': True}}),
                   dict(report_v2={'quality': {'decoder_changed_mid_session': True}})]
        for changes in invalid:
            with self.subTest(changes=changes):
                event = self.event(**changes)
                self.assertIsNone(event['estimated_kwh'])
                self.assertEqual(comparison('通勤', [event])['distance_km']['mean'], 20)

    def test_duration_is_observation_window_and_unknown_is_not_zero(self):
        self.assertIsNone(self.event(duration_seconds=1)['duration_seconds'])
        self.assertIsNone(self.event(start_time=None)['duration_seconds'])
        event = self.event(distance_km=0, end_soc=70, soc_delta=0)
        self.assertEqual(event['estimated_kwh'], 0)
        self.assertEqual(comparison('停车观测', [event])['distance_km']['mean'], 0)
        unknown = self.event(distance_km=None)
        self.assertIsNone(comparison('未知', [unknown])['distance_km']['mean'])

    def test_inconsistent_soc_is_not_used_for_soc_mean(self):
        event = self.event(soc_delta=-4)
        self.assertIsNone(event['soc_delta'])
        self.assertIsNone(comparison('冲突', [event])['soc_consumed']['mean'])
        malformed = self.event(report_v2={'quality': {'quality_reasons': True}})
        self.assertEqual(malformed['distance_km'], 20)

    def insert(self, identity, kind, **changes):
        summary = dict(self.base, **changes)
        with self.monitor.tracks.connect() as db:
            db.execute('INSERT INTO monitor_events '
                       '(id,vehicle,kind,summary,message,created,delivery,attempts) '
                       'VALUES (?,?,?,?,?,?,?,?)',
                       (identity, 'car', kind, json.dumps(summary), '已发送的原始正文',
                        summary['end_time'], 'sent', 1))

    def stored(self):
        with self.monitor.tracks.connect() as db:
            return db.execute('SELECT * FROM monitor_events ORDER BY id').fetchall()

    def test_sent_partial_events_are_counted_once_without_mutation(self):
        self.insert('partial-trip', 'trip_end')
        self.insert('partial-charge', 'charge_end', start_soc=65, end_soc=75, soc_delta=10)
        before = self.stored()
        reports = UsageReports(self.path, ArchiveReader(self.root/'archive'))
        for _ in range(2):
            result = reports.query('owner', 'car', 'month', '2026-09-20', self.start+7200000)
            current = result['current']
            self.assertEqual(current['totals']['distance_km'], 20)
            self.assertEqual(current['totals']['partial_distance_km'], 20)
            self.assertIsNone(current['totals']['complete_distance_km'])
            self.assertEqual(current['totals']['duration_seconds'], 3600)
            self.assertEqual(current['totals']['trip_estimated_kwh'], 4.3)
            self.assertEqual(current['totals']['charge_estimated_kwh'], 8.6)
            self.assertEqual(current['days'][19]['distance_km'], 20)
            self.assertEqual(current['samples']['distance'], 1)
            self.assertEqual(current['samples']['partial_distance'], 1)
            self.assertEqual(current['totals']['trip_count'], 1)
        charging = ChargingAnalytics(self.path).statistics('car', 7, 'all', self.start+7200000)
        self.assertEqual(charging['summary']['estimated_kwh'], 8.6)
        self.assertEqual(charging['summary']['partial_energy_count'], 1)
        self.assertEqual(charging['summary']['duration_seconds'], 3600)
        self.assertIsNone(charging['summary']['complete_duration_seconds'])
        self.assertEqual(charging['daily'][-1]['estimated_kwh'], 8.6)
        public = EventStore(self.path).query('car', '2026-09-20', 'charge_end')['events'][0]
        self.assertEqual(public['estimated_kwh'], 8.6)
        self.assertEqual(EventStore(self.path).latest('car')['charge_end']['estimated_kwh'], 8.6)
        self.assertEqual(UsageEvents(self.path).get('car', 'partial-charge')['estimated_kwh'], 8.6)
        self.assertEqual(before, self.stored(), 'Analytics cannot rewrite or resend saved events')

    def test_charge_statistics_unknown_zero_and_invalid_endpoints(self):
        self.insert('bad', 'charge_end', start_soc=65, end_soc=75, soc_delta=11)
        api = ChargingAnalytics(self.path)
        result = api.statistics('car', 7, 'all', self.start+7200000)
        self.assertIsNone(result['summary']['estimated_kwh'])
        self.assertIsNone(result['daily'][-1]['estimated_kwh'])
        self.assertEqual(result['summary']['excluded_energy_count'], 1)
        self.insert('zero', 'charge_end', start_soc=65, end_soc=65, soc_delta=0)
        result = api.statistics('car', 7, 'all', self.start+7200000)
        self.assertEqual(result['summary']['estimated_kwh'], 0)
        self.assertEqual(result['summary']['included_energy_count'], 1)
        self.assertEqual(result['daily'][-1]['estimated_kwh'], 0)


if __name__ == '__main__':
    unittest.main()
