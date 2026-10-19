"""Offline Z12 scan/time probe. Fresh synthetic archives; no live data or sends."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark_archive_capacity import raw
from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.parking_analytics import ParkingAnalytics
from zeekr_control.snapshot_archive import SnapshotArchive, BEIJING
from zeekr_control.tracks import day_bounds
from datetime import datetime

DAY = 86400000
START = day_bounds('2026-07-01')[0]
QUERY = START + 45*DAY
CASES = {
    'missing_both_crossing_trip': [(10, 80)],
    'missing_before': [(10, 45.5), (45.75, 46)],
    'missing_after': [(44, 45.25), (45.5, 80)],
    'missing_before_long_event': [(45.5, 46.5)],
    'missing_after_open_event': [(44.5, 45.5)],
    'cross_day_gap': [(39, 40), (50, 51)],
    'no_trips_long_event': [],
}


def seed(root, cadence=300000):
    writer = SnapshotArchive(root/'archive')
    groups = {}
    # Two missing days inside a real multi-day stop must remain a single event.
    for index in range(90*DAY//cadence):
        stamp = START + index*cadence
        if 42*DAY <= stamp-START < 44*DAY:
            continue
        month = datetime.fromtimestamp(stamp/1000, BEIJING).strftime('%Y/%m')
        groups.setdefault(month, []).append(stamp)
    for month, stamps in groups.items():
        first = stamps[0]
        writer.append('owner', 'car', json.dumps(raw(first)), first, first, first, 'monitor')
        with sqlite3.connect(root/'archive'/(month+'.sqlite3')) as db:
            for offset in range(1, len(stamps), 512):
                payloads, reads = [], []
                for stamp in stamps[offset:offset+512]:
                    encoded = json.dumps(raw(stamp), separators=(',', ':')).encode()
                    digest = hashlib.sha256(encoded).hexdigest()
                    payloads.append((digest, 'gzip-json-v1', len(encoded), gzip.compress(encoded, mtime=0)))
                    reads.append(('owner', 'car', stamp, stamp, stamp, 'monitor', digest))
                db.executemany('INSERT INTO payloads VALUES (?,?,?,?)', payloads)
                db.executemany('INSERT INTO reads(scope_key,vehicle_key,state_time,fetched_at,observed_at,source,digest) VALUES (?,?,?,?,?,?,?)', reads)


def run_case(root, name, trips, *, full_payload=False):
    database = root/(name+'.sqlite3')
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE monitor_events (id TEXT,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
        for index, (start, end) in enumerate(trips):
            start, end = START+int(start*DAY), START+int(end*DAY)
            summary = dict(start_time=start, end_time=end, duration_seconds=(end-start)/1000,
                           start_soc=70, end_soc=70, soc_delta=0, partial=False)
            db.execute('INSERT INTO monitor_events VALUES (?,?,?,?,?)',
                       (str(index), 'car', 'trip_end', json.dumps(summary), end))
    database.chmod(0o600)
    counts = dict(metadata_rows=0, payload_decodes=0)
    original_rows, original_payload = ArchiveReader._iter_rows, ArchiveReader._payload
    original_records = ArchiveReader.iter_records
    def rows(reader, *args, **kwargs):
        for row in original_rows(reader, *args, **kwargs):
            counts['metadata_rows'] += 1
            yield row
    def payload(row):
        counts['payload_decodes'] += 1
        return original_payload(row)
    def records(reader, *args, **kwargs):
        if full_payload:
            kwargs.pop('payload_when', None)
        return original_records(reader, *args, **kwargs)
    date = datetime.fromtimestamp(QUERY/1000, BEIJING).strftime('%Y-%m-%d')
    with patch.object(ArchiveReader, '_iter_rows', rows), patch.object(ArchiveReader, '_payload', staticmethod(payload)), patch.object(ArchiveReader, 'iter_records', records):
        begin = time.perf_counter()
        result = ParkingAnalytics(ArchiveReader(root/'archive'), database).query('owner', 'car', date, date, 86)
        seconds = time.perf_counter()-begin
    encoded = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return dict(case=name, seconds=round(seconds, 4), **counts,
                result_sha256=hashlib.sha256(encoded).hexdigest(), events=[
                    {key: event[key] for key in ('start_time', 'end_time', 'gap_count', 'status', 'soc_drop')}
                    for event in result['events']])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--full-payload', action='store_true', help='Replay the original full-body read path')
    parser.add_argument('--runs', type=int, default=1)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='zeekr-parking-ranges-') as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        seed(root)
        results = []
        for run in range(args.runs):
            for name, trips in CASES.items():
                if run:
                    (root/(name+'.sqlite3')).unlink()
                result = dict(run=run+1, **run_case(root, name, trips, full_payload=args.full_payload))
                results.append(result)
                print(json.dumps(result), flush=True)
        args.output.write_text(json.dumps(dict(history_days=90, query_days=1, cadence_seconds=300,
                                               missing_days=2, full_payload=args.full_payload, results=results), indent=2)+'\n')


if __name__ == '__main__':
    main()
