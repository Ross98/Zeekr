import json
import sqlite3
import unittest

import test_archive_reader as archive_fixtures
from zeekr_control.tracks import day_bounds


class DataQualityTests(unittest.TestCase):
    append=archive_fixtures.ArchiveReaderTests.append

    def setUp(self):
        archive_fixtures.ArchiveReaderTests.setUp(self)
        from zeekr_control.data_quality import DataQuality
        self.now=self.start+86400000
        self.api=DataQuality(self.reader,clock=lambda:self.now)

    def query(self,start='2026-09-20',end='2026-09-20'):
        return self.api.query('owner','car',start,end)

    def test_disjoint_categories_cover_every_read_and_preserve_diagnostics(self):
        self.append();self.append(60000,state_offset=0);self.append(120000,soc=69,state_offset=0)
        self.append(180000,state_offset=-60000)
        self.append(1800000,state_offset=0)
        self.append(1860000,extra={'updateTime':None})
        self.append(1920000,state_offset=2100000)
        result=self.query()
        self.assertEqual(result['counts'],dict(new=1,revision=1,repeat=1,invalid=4))
        self.assertEqual(sum(result['counts'].values()),result['reads'])
        self.assertEqual(result['issues']['regression'],1)
        self.assertEqual(result['issues']['stale'],1)
        self.assertEqual(result['issues']['unknown_time'],1)
        self.assertEqual(result['issues']['future_time'],1)

    def test_delay_bins_unknown_and_negative_do_not_pollute_nonnegative_quantiles(self):
        for index,delay in enumerate((-120,0,60,61,300,301,600,601)):
            offset=index*1000000
            self.append(offset,state_offset=offset-delay*1000)
        self.append(9000000,extra={'updateTime':None})
        delay=self.query()['delay']
        self.assertEqual([row['count'] for row in delay['bins']],[1,2,2,2,1])
        self.assertEqual(delay['unknown_count'],1)
        self.assertEqual(delay['sample_count'],7)
        self.assertEqual(delay['p50_seconds'],300)
        self.assertEqual(delay['p95_seconds'],601)
        self.assertEqual(delay['max_seconds'],601)

    def test_gap_intervals_include_bounded_edges_without_claiming_outages(self):
        self.append(30*60000);self.append(35*60000);self.append(60*60000)
        self.now=self.start+90*60000
        gaps=self.query()['gaps']
        self.assertEqual([r['kind'] for r in gaps],['leading','between','trailing'])
        self.assertEqual(gaps[0]['start'],self.start)
        self.assertEqual(gaps[1]['duration_seconds'],25*60)
        self.assertLessEqual(gaps[-1]['end'],self.now+1)

    def test_normal_parking_cadence_is_not_a_gap(self):
        for minute in range(0,31,5):self.append(minute*60000)
        self.now=self.start+31*60000
        result=self.query()
        self.assertEqual(result['gaps'],[])
        self.assertEqual(result['days'][0]['read_slots'],2)
        self.assertEqual(result['days'][0]['elapsed_slots'],2)
        self.assertEqual(result['gap_threshold_seconds'],600)

    def test_future_is_not_missing_and_empty_history_does_not_create_storage(self):
        self.now=self.start+3600000
        result=self.query('2026-09-20','2026-09-21')
        self.assertEqual(result['days'][1]['status'],'future')
        self.assertEqual(result['days'][1]['elapsed_slots'],0)
        self.assertEqual(len(result['gaps']),1)
        self.assertEqual(result['gaps'][0]['kind'],'empty')
        self.assertFalse(self.root.exists())
        future=self.query('2026-09-21','2026-09-21')
        self.assertEqual(future['gaps'],[])
        self.assertIsNone(future['delay']['p50_seconds'])

    def test_only_metadata_is_read_even_if_payload_is_corrupt(self):
        self.append()
        shard=self.root/'2026'/'09.sqlite3'
        with sqlite3.connect(shard) as db:db.execute("UPDATE payloads SET compressed_json=X'00'")
        before=shard.read_bytes()
        result=self.query()
        self.assertEqual(result['reads'],1)
        self.assertEqual(shard.read_bytes(),before)
        for secret in ('PRIVATE','digest','compressed_json','scope_key','latitude'):
            self.assertNotIn(secret,json.dumps(result))

    def test_repeated_time_after_regression_cannot_be_counted_as_new_twice(self):
        self.append();self.append(120000)
        self.append(180000,state_offset=60000)
        self.append(240000,state_offset=120000)
        result=self.query()
        self.assertEqual(result['counts']['new'],2)
        self.assertEqual(result['counts']['invalid'],2)
        self.assertEqual(result['issues']['revisited_time'],1)

    def test_midnight_cross_month_and_account_vehicle_scope(self):
        self.start=day_bounds('2026-10-01')[0]
        self.append(-60000);self.append(0,state_offset=-60000)
        self.append(60000,scope='other');self.append(120000,vehicle='other')
        self.now=self.start+3600000
        result=self.query('2026-10-01','2026-10-01')
        self.assertEqual(result['counts']['repeat'],1)
        self.assertEqual(result['counts']['new'],0)
        self.assertEqual(result['reads'],1)

    def test_bounded_range_and_real_dates(self):
        for start,end in [('2026-09-20','2026-09-19'),('2026-08-01','2026-09-20'),('bad','2026-09-20')]:
            with self.assertRaises(ValueError):self.query(start,end)


if __name__=='__main__':unittest.main()
