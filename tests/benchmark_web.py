"""Repeatable local Web benchmark; temporary, synthetic data and no cloud access."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zeekr_control.monitor import Monitor
from zeekr_control.storage import save
from zeekr_control.web import App
from web_fixture import FixtureClient


def measure(call, repeats):
    call()
    samples = []
    gc.collect()
    cpu = time.process_time()
    for _ in range(repeats):
        start = time.perf_counter()
        call()
        samples.append((time.perf_counter() - start) * 1000)
    cpu_ms = (time.process_time() - cpu) * 1000 / repeats
    gc.collect()
    tracemalloc.start()
    call()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {'median_ms': round(statistics.median(samples), 3),
            'cpu_ms_per_call': round(cpu_ms, 3), 'peak_python_kib': round(peak / 1024, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=int, default=10000)
    parser.add_argument('--repeats', type=int, default=20)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        session = root / 'session.json'
        save(session, {'accessToken': 'SYNTHETIC', 'userId': 'SYNTHETIC'})
        app = App(session, client_factory=FixtureClient)
        try:
            app.refresh(1)
            vehicle = hashlib.sha256(b'L6T79X2Z0NP000001').hexdigest()
            monitor = Monitor(app.database_path)
            now = int(time.time() * 1000)
            save(root / 'monitor-health.json', {'status': 'fresh', 'heartbeat': str(now)})
            with monitor.tracks.connect() as db:
                def events():
                    for i in range(args.events):
                        ended = now - (args.events - i) * 3600000
                        summary = {'start_time': ended - 600000, 'end_time': ended,
                                   'start_soc': 70, 'end_soc': 68, 'soc_delta': -2,
                                   'distance_km': 8.4, 'duration_seconds': 600,
                                   'partial': False, 'battery_capacity_kwh': 86,
                                   'synthetic_private_payload': 'x' * 4096}
                        yield (str(i), vehicle, 'trip_end' if i % 2 else 'charge_end',
                               json.dumps(summary), 'SYNTHETIC', ended)
                db.executemany('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) '
                               'VALUES (?,?,?,?,?,?)', events())
            print(json.dumps({'events': args.events, 'repeats': args.repeats,
                              'state': measure(app.state, args.repeats),
                              'latest_events': measure(lambda: app.event_store.latest(vehicle), args.repeats),
                              'charging_statistics': measure(lambda: app.charging_analytics.statistics(
                                  vehicle, 30, 'all', now=now), args.repeats),
                              'unchanged_snapshot': measure(lambda: app._restore_snapshot(
                                  {'accessToken': 'SYNTHETIC', 'userId': 'SYNTHETIC'}), args.repeats)},
                             indent=2))
        finally:
            app.close()


if __name__ == '__main__':
    main()
