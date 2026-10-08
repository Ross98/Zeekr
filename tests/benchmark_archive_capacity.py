"""Production-shape month capacity; synthetic private files, no network or sends."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.daily_timeline import DailyTimeline
from zeekr_control.monitor import Monitor
from zeekr_control.parking_analytics import ParkingAnalytics
from zeekr_control.periodic_summary import PeriodicSummary
from zeekr_control.personal_store import PersonalStore
from zeekr_control.snapshot_archive import SnapshotArchive
from zeekr_control.tracks import day_bounds
from zeekr_control.usage_calendar import UsageCalendar
from zeekr_control.usage_reports import UsageReports


def raw(stamp):
    return {'updateTime': stamp, 'basicVehicleStatus': {'engineStatus': 'engine_off', 'speedValidity': True, 'speed': 0},
            'additionalVehicleStatus': {'electricVehicleStatus': {'ptReady': 0, 'chargeSts': 0, 'chargerState': 0,
            'statusOfChargerConnection': 0, 'chargeLevel': 70}, 'maintenanceStatus': {'odometer': 1000},
            'drivingBehaviourStatus': {'gearAutoStatus': 0}},
            'position': {'latitude': 108000000, 'longitude': 432000000, 'marsCoordinates': False, 'posCanBeTrusted': True}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=int, default=267840)
    parser.add_argument('--repeat', action='store_true')
    parser.add_argument('--year', action='store_true')
    args = parser.parse_args()
    start = day_bounds('2026-10-01')[0]
    end = day_bounds('2026-11-01')[0]
    with tempfile.TemporaryDirectory(prefix='zeekr-month-capacity-') as temporary:
        root = Path(temporary) / 'private'; archive_root = root / 'snapshot-archive'
        writer = SnapshotArchive(archive_root)
        for stamp in (start-10000, start, end):
            encoded = json.dumps(raw(stamp), separators=(',', ':'))
            writer.append('owner', 'car', encoded, stamp, stamp, stamp, 'monitor')
        with sqlite3.connect(archive_root/'2026'/'10.sqlite3') as db:
            for first in range(1, args.records, 512):
                payloads, reads = [], []
                for i in range(first, min(args.records, first+512)):
                    observed = start+i*10000; stamp = start if args.repeat else observed
                    encoded = json.dumps(raw(stamp), separators=(',', ':')).encode()
                    digest = hashlib.sha256(encoded).hexdigest()
                    payloads.append((digest, 'gzip-json-v1', len(encoded), gzip.compress(encoded, compresslevel=1, mtime=0)))
                    reads.append(('owner', 'car', stamp, observed, observed, 'monitor', digest))
                db.executemany('INSERT OR IGNORE INTO payloads VALUES (?,?,?,?)', payloads)
                db.executemany('INSERT INTO reads(scope_key,vehicle_key,state_time,fetched_at,observed_at,source,digest) VALUES (?,?,?,?,?,?,?)', reads)
        reader = ArchiveReader(archive_root); database = root/'tracks.sqlite3'; Monitor(database)
        store = PersonalStore(root/'personal.sqlite3')
        timings = {}
        def measure(name, query):
            begin = time.monotonic(); result = query(); timings[name] = round(time.monotonic()-begin, 3)
            print(json.dumps(dict(check=name,seconds=timings[name])),flush=True)
            return result
        calendar = measure('calendar', lambda: UsageCalendar(database,reader).query('owner','car','2026-10-01',now=end+86400000))
        assert sum(day['reads'] for day in calendar['days']) == args.records
        report = measure('month_report', lambda: UsageReports(database,reader).query('owner','car','month','2026-10-01',now=end+86400000))
        assert report['current']['coverage']['reads'] == args.records
        periodic = measure('periodic_month', lambda: PeriodicSummary(database,reader,store).query('owner','car','owner','month','2026-10-01',now=end+86400000))
        assert not periodic['quality']['archive_limited']
        parking = measure('parking', lambda: ParkingAnalytics(reader,database).query('owner','car','2026-10-01','2026-10-31',86))
        assert parking['calculation_version'] == 6
        assert parking['parking_count'] == 1
        assert parking['events'][0]['observation_quality']['read_count'] == args.records+2
        if not args.repeat:
            assert parking['events'][0]['sample_count'] == args.records+2
            if args.records == 267840:
                assert parking['events'][0]['gap_count'] == 0
        if args.year:
            timeline = DailyTimeline(database,reader,store)
            with patch('zeekr_control.usage_calendar.time.time',return_value=(end+86400000)/1000):
                year = measure('year_review', lambda: timeline.year('owner','car','2026',owner='owner'))
            assert sum(day['reads'] for day in year['days']) == args.records+2
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_bytes = rss if sys.platform == 'darwin' else rss*1024
        assert rss_bytes < 256*1024*1024, rss_bytes
        print(json.dumps(dict(records=args.records,boundary_records=2,repeat=args.repeat,
                              max_rss_mib=round(rss_bytes/1024/1024,2),seconds=timings),ensure_ascii=False))


if __name__ == '__main__':
    main()
