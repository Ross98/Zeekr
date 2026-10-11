"""Offline workers for systemd capacity acceptance; never use production stores."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark_archive_capacity import raw
from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.focused_trip_image import FocusedTripImage
from zeekr_control.monitor import Monitor
from zeekr_control.periodic_report import ReportImage
from zeekr_control.periodic_summary import PeriodicSummary
from zeekr_control.personal_store import PersonalStore
from zeekr_control.snapshot_archive import SnapshotArchive
from zeekr_control.tracks import day_bounds


def seed_archive(root, records):
    if not 1 <= records <= 267840:
        raise ValueError('Synthetic record count must be 1..267840')
    archive = root / 'snapshot-archive'
    if archive.exists():
        raise ValueError('Use a fresh synthetic directory')
    start = day_bounds('2026-10-01')[0]
    writer = SnapshotArchive(archive)
    writer.append('owner', 'car', json.dumps(raw(start)), start, start, start, 'monitor')
    with sqlite3.connect(archive / '2026' / '10.sqlite3') as db:
        for first in range(1, records, 512):
            payloads, reads = [], []
            for index in range(first, min(records, first + 512)):
                stamp = start + index * 10000
                encoded = json.dumps(raw(stamp), separators=(',', ':')).encode()
                digest = hashlib.sha256(encoded).hexdigest()
                payloads.append((digest, 'gzip-json-v1', len(encoded), gzip.compress(encoded, compresslevel=1, mtime=0)))
                reads.append(('owner', 'car', stamp, stamp, stamp, 'monitor', digest))
            db.executemany('INSERT OR IGNORE INTO payloads VALUES (?,?,?,?)', payloads)
            db.executemany('INSERT INTO reads(scope_key,vehicle_key,state_time,fetched_at,observed_at,source,digest) VALUES (?,?,?,?,?,?,?)', reads)
    Monitor(root / 'tracks.sqlite3')
    PersonalStore(root / 'personal.sqlite3')
    (root / 'fixture.json').write_text(json.dumps({'records': records}))


def monthly_report(root):
    end = day_bounds('2026-11-01')[0]
    report = PeriodicSummary(root / 'tracks.sqlite3', ArchiveReader(root / 'snapshot-archive'),
        PersonalStore(root / 'personal.sqlite3')).query('owner', 'car', 'owner', 'month', '2026-10-01', now=end)
    image = ReportImage().render(report)
    return dict(observed_days=report['quality']['observed_days'],
        archive_limited=report['quality']['archive_limited'], png_bytes=len(image))


def image_work(root):
    from zeekr_control.road_network import build_network
    start = day_bounds('2026-10-01')[0]
    nodes = [dict(type='node', id=i+1, lon=118+i*0.0001, lat=32) for i in range(300)]
    roads = root / 'synthetic-roads'
    roads.mkdir()
    build_network({'elements': nodes + [dict(type='way', id=1000, nodes=[n['id'] for n in nodes],
        tags={'highway': 'primary'})]}, roads / 'region.sqlite3')
    points = [dict(longitude=n['lon'], latitude=n['lat'], state_time=start+i*10000,
        observed_time=start+i*10000, trusted=True, plottable=True,
        coordinate_system='WGS84（社区解释）') for i, n in enumerate(nodes)]
    route = dict(observations=points, segments=[points], count=len(points), gaps=[])
    report = dict(start_time=start, end_time=start+2990000, metrics=dict(distance_km=8,
        duration_seconds=2990, estimated_kwh=1.5, soc_delta=-3))
    image = FocusedTripImage(roads).render_trip(report, route)
    return dict(png_bytes=len(image), route_points=len(points))


def summarize_collection(durations, reads, during, png_bytes):
    if not durations or reads != len(durations) or during < 1 or png_bytes < 1:
        raise ValueError('Collection or image did not complete during concurrent work')
    return dict(ticks=len(durations), ticks_during_image=during, reads=reads,
        max_tick_seconds=round(max(durations), 3), png_bytes=png_bytes)


def monitor_work(root):
    from test_monitor import BASE, sample
    from zeekr_control.monitor_runtime import Runner
    from zeekr_control.storage import save
    folder = root / 'collector'
    save(folder / 'session.json', {'accessToken': 'synthetic-capacity-only'})
    class Client:
        calls = 0
        def __init__(self, session):
            pass
        def vehicles(self):
            return [{'vin': 'L6T79X2Z0NP000001'}]
        def status(self, vin):
            Client.calls += 1
            return sample(Client.calls * 30)
    runner = Runner(folder / 'session.json', client_factory=Client, sender=Mock())
    durations, during = [], 0
    log = root / 'image.json'
    with log.open('w') as output:
        process = subprocess.Popen([sys.executable, __file__, '--task', 'image', '--root', str(root)], stdout=output)
        try:
            deadline = time.monotonic() + 75
            while process.poll() is None and time.monotonic() < deadline:
                begin = time.monotonic()
                runner.tick(BASE + (Client.calls + 1) * 30000)
                durations.append(time.monotonic() - begin)
                during += int(process.poll() is None)
                time.sleep(max(0, 1 - durations[-1]))
            if process.poll() is None:
                raise TimeoutError('Concurrent image exceeded acceptance budget')
            if process.returncode:
                raise ValueError('Image worker failed')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            runner.insight_worker.close()
    reads = 0
    for path in (folder / 'snapshot-archive').rglob('*.sqlite3'):
        with sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True) as db:
            reads += db.execute('SELECT count(*) FROM reads').fetchone()[0]
    runner.sender.assert_not_called()
    return summarize_collection(durations, reads, during, json.loads(log.read_text())['png_bytes'])


def web_work(root):
    from zeekr_control.usage_calendar import UsageCalendar
    from zeekr_control.usage_reports import UsageReports
    from zeekr_control.parking_analytics import ParkingAnalytics
    reader = ArchiveReader(root / 'snapshot-archive')
    database = root / 'tracks.sqlite3'
    end = day_bounds('2026-11-01')[0]
    counts = json.loads((root / 'fixture.json').read_text())['records']
    timings = {}
    for name, query in (
        ('calendar', lambda: UsageCalendar(database, reader).query('owner', 'car', '2026-10-01', now=end)),
        ('month_report', lambda: UsageReports(database, reader).query('owner', 'car', 'month', '2026-10-01', now=end)),
        ('parking', lambda: ParkingAnalytics(reader, database).query('owner', 'car', '2026-10-01', '2026-10-31', 86))):
        begin = time.monotonic()
        result = query()
        timings[name] = round(time.monotonic()-begin, 3)
        if name == 'calendar':
            assert sum(day['reads'] for day in result['days']) == counts
        elif name == 'month_report':
            assert result['current']['coverage']['reads'] == counts
        else:
            assert result['parking_count'] == 1
    return dict(records=counts, seconds=timings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', choices=['prepare', 'month', 'monitor', 'image', 'web'], required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--records', type=int, default=267840)
    parser.add_argument('--barrier', type=Path)
    args = parser.parse_args()
    if args.barrier:
        (args.root / (args.task + '.ready')).touch()
        deadline = time.monotonic() + 60
        while not args.barrier.exists():
            if time.monotonic() > deadline:
                raise TimeoutError('Acceptance start barrier not released')
            time.sleep(0.1)
    begin = time.monotonic()
    if args.task == 'prepare':
        seed_archive(args.root, args.records)
        result = dict(records=args.records)
    else:
        result = {'month': monthly_report, 'monitor': monitor_work,
            'image': image_work, 'web': web_work}[args.task](args.root)
    result.update(task=args.task, seconds_total=round(time.monotonic()-begin, 3))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
