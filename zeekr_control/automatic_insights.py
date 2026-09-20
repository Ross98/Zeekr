"""Scheduled descriptive statistics from existing evidence, never adaptive control."""
import json
import math
from pathlib import Path
import sqlite3
import threading

from .archive_reader import _context, _private
from .data_quality import DataQuality
from .storage import load, save
from .tracks import day_bounds
from .trip_visibility import revision
from .usage_events import UsageEvents
from .usage_reports import DAY, date_label

VERSION = 1
INTERVAL_MS = 3600000
MAX_CACHE_BYTES = 131072
READ_ERRORS = (ValueError, OSError, sqlite3.Error)


def energy_group(rows):
    trips = [r for r in rows if r['kind'] == 'trip_end']
    eligible = [r for r in trips if not r['partial'] and r['estimated_kwh'] is not None
                and r['distance_km'] is not None and r['distance_km'] >= 10
                and r['soc_delta'] is not None and r['soc_delta'] <= -3]
    distance = sum(r['distance_km'] for r in eligible)
    energy = sum(r['estimated_kwh'] for r in eligible)
    return dict(samples=len(eligible), excluded=len(trips)-len(eligible),
                distance_km=round(distance, 3) if eligible else None,
                estimated_kwh=round(energy, 3) if eligible else None,
                kwh_per_100km=round(energy/distance*100, 3) if distance else None)


def quartiles(values):
    ordered = sorted(values)
    def at(fraction):
        index = (len(ordered)-1)*fraction
        low, high = math.floor(index), math.ceil(index)
        return round(ordered[low]+(ordered[high]-ordered[low])*(index-low), 3)
    return dict(p25=at(.25), median=at(.5), p75=at(.75))


def charging_groups(rows):
    charges = [r for r in rows if r['kind'] == 'charge_end']
    eligible = [r for r in charges if not r['partial'] and r['start_soc'] is not None
                and r['end_soc'] is not None and r['soc_delta'] is not None and r['soc_delta'] > 0
                and abs(r['end_soc']-r['start_soc']-r['soc_delta']) <= .001
                # Reuse the verified SOC/capacity and decoder-consistency gate.
                and r['estimated_kwh'] is not None]
    groups = {}
    for mode in ('ac', 'dc', 'unknown'):
        group = [r for r in eligible if (r['charge_mode'] or 'unknown') == mode]
        ready = len(group) >= 5
        groups[mode] = dict(status='ready' if ready else 'insufficient', samples=len(group),
            start_soc=quartiles([r['start_soc'] for r in group]) if ready else None,
            end_soc=quartiles([r['end_soc'] for r in group]) if ready else None)
    return dict(status='ready' if any(g['status'] == 'ready' for g in groups.values()) else 'insufficient',
                excluded=len(charges)-len(eligible), groups=groups)


class Analyzer:
    def __init__(self, database, archive):
        self.events = UsageEvents(database)
        self.archive = archive

    def revision(self, vehicle):
        with self.events.connect() as db:
            return revision(db, vehicle)

    def build(self, scope, vehicle, now):
        _context(scope, vehicle)
        today, _ = day_bounds(date_label(now))
        lower, recent = today-27*DAY, today-6*DAY
        before = self.revision(vehicle)
        result = dict(version=VERSION, generated_at=now, event_revision=before,
                      start_date=date_label(lower), recent_start_date=date_label(recent), end_date=date_label(now))
        try:
            history = self.events.between(vehicle, lower, now+1)
            rows = history['events']
            current = energy_group([r for r in rows if r['end_time'] >= recent])
            baseline = energy_group([r for r in rows if r['end_time'] < recent])
            ready = current['samples'] >= 3 and baseline['samples'] >= 5
            a, b = current['kwh_per_100km'], baseline['kwh_per_100km']
            result['energy'] = dict(status='ready' if ready else 'insufficient', recent=current, baseline=baseline,
                change_percent=round((a/b-1)*100, 2) if ready and b else None)
            result['charging'] = charging_groups(rows)
            result['unreadable_events'] = history['unreadable_or_undated']
        except READ_ERRORS:
            result.update(energy={'status': 'error'}, charging={'status': 'error'}, unreadable_events=None)
        try:
            quality = DataQuality(self.archive, clock=lambda: now).query(
                scope, vehicle, date_label(recent), date_label(now))
            result['quality'] = dict(status='ready' if quality['reads'] else 'insufficient',
                reads=quality['reads'], counts=quality['counts'],
                read_slots=sum(d['read_slots'] for d in quality['days']),
                new_slots=sum(d['new_slots'] for d in quality['days']),
                elapsed_slots=sum(d['elapsed_slots'] for d in quality['days']),
                last_read_at=max((d['last_read'] for d in quality['days'] if d['last_read'] is not None), default=None),
                p50_seconds=quality['delay']['p50_seconds'], p95_seconds=quality['delay']['p95_seconds'])
        except READ_ERRORS:
            result['quality'] = {'status': 'error'}
        if self.revision(vehicle) != before:
            raise ValueError('行程记录发生变化，等待下次重新分析。')
        return result


# Cache reads also use a strict scalar projection. Future/raw fields stay private.
STATUS = frozenset(('ready', 'insufficient', 'error'))
ENERGY_GROUP = dict(samples=int, excluded=int, distance_km=[float], estimated_kwh=[float], kwh_per_100km=[float])
QUARTILES = dict(p25=float, median=float, p75=float)
CHARGE_GROUP = dict(status=STATUS, samples=int, start_soc=[QUARTILES], end_soc=[QUARTILES])
REPORT = dict(version=int, generated_at=int, event_revision=int, start_date=str, recent_start_date=str, end_date=str,
    unreadable_events=[int],
    energy=dict(status=STATUS, recent=ENERGY_GROUP, baseline=ENERGY_GROUP, change_percent=[float]),
    charging=dict(status=STATUS, excluded=int, groups=dict(ac=CHARGE_GROUP, dc=CHARGE_GROUP, unknown=CHARGE_GROUP)),
    quality=dict(status=STATUS, reads=int, counts=dict(new=int, revision=int, repeat=int, invalid=int),
                 read_slots=int, new_slots=int, elapsed_slots=int, last_read_at=[int], p50_seconds=[float], p95_seconds=[float]))


def project(value, shape=REPORT):
    if isinstance(shape, list):
        return None if value is None else project(value, shape[0])
    if isinstance(shape, dict):
        if not isinstance(value, dict): raise ValueError('分析缓存格式无效。')
        if 'status' in shape and value.get('status') == 'error': return {'status': 'error'}
        return {key: project(value.get(key), spec) for key, spec in shape.items()}
    if isinstance(shape, frozenset):
        if not isinstance(value, str) or value not in shape: raise ValueError('分析状态无效。')
    elif shape is str:
        day_bounds(value)  # The only free strings in a report are validated dates.
    elif shape is int:
        if type(value) is not int or value < 0: raise ValueError('分析计数无效。')
    elif type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('分析数值无效。')
    return value


class InsightCache:
    """Atomic, bounded, owner-only cache for the currently bound account/vehicle."""
    def __init__(self, path):
        self.path = Path(path)

    def _check(self):
        if self.path.parent.exists() or self.path.parent.is_symlink():
            _private(self.path.parent, directory=True)
        if self.path.exists() or self.path.is_symlink():
            _private(self.path)
            if self.path.stat().st_size > MAX_CACHE_BYTES: raise ValueError('分析缓存超过大小限制。')

    def _read(self, scope, vehicle):
        _context(scope, vehicle); self._check()
        data = load(self.path)
        return data if data.get('scope') == scope and data.get('vehicle') == vehicle else {}

    def _write(self, scope, vehicle, now, report, error, event_revision):
        _context(scope, vehicle); self._check()
        data = dict(scope=scope, vehicle=vehicle, version=str(VERSION), attempted_at=str(now),
                    event_revision=str(event_revision), error='true' if error else 'false',
                    report=json.dumps(project(report), allow_nan=False) if report else '')
        if len(json.dumps(data).encode()) > MAX_CACHE_BYTES: raise ValueError('分析缓存超过大小限制。')
        save(self.path, data)

    def success(self, scope, vehicle, now, report):
        self._write(scope, vehicle, now, report, False, report['event_revision'])

    def failure(self, scope, vehicle, now, event_revision=0):
        data = self._read(scope, vehicle)
        report = project(json.loads(data['report'])) if data.get('report') else None
        self._write(scope, vehicle, now, report, True, event_revision)

    def due(self, scope, vehicle, now, event_revision):
        data = self._read(scope, vehicle)
        attempted = int(data.get('attempted_at', '0'))
        return (not data or data.get('version') != str(VERSION)
                or int(data.get('event_revision', '-1')) != event_revision
                or now < attempted or now >= attempted+INTERVAL_MS)

    def query(self, scope, vehicle, now, event_revision):
        data = self._read(scope, vehicle)
        result = dict(status='waiting', report=None, attempted_at=None, next_check_at=None, interval_seconds=INTERVAL_MS//1000)
        if not data: return result
        attempted = int(data['attempted_at'])
        result.update(attempted_at=attempted, next_check_at=attempted+INTERVAL_MS)
        report = project(json.loads(data['report'])) if data.get('report') else None
        if (data.get('version') != str(VERSION)
                or report and (report['event_revision'] != event_revision or report['version'] != VERSION)):
            result['status'] = 'changed'
            return result
        stale = report and (now < report['generated_at'] or now >= report['generated_at']+INTERVAL_MS)
        partial = report and any(report[key]['status'] == 'error' for key in ('energy', 'charging', 'quality'))
        result.update(report=report, status='error' if data.get('error') == 'true' else
                      'stale' if stale else 'partial' if partial else 'ready')
        return result


class InsightWorker:
    """One bounded analysis at a time; collection never waits for archive scans."""
    def __init__(self, analyzer, cache):
        self.analyzer, self.cache = analyzer, cache
        self.lock = threading.Lock()
        self.thread = None
        self.closed = False
        self.retry_after = 0

    def start(self, scope, vehicle, now, guard):
        with self.lock:
            if self.closed or self.thread and self.thread.is_alive() or now < self.retry_after: return False
            self.thread = threading.Thread(target=self._run, args=(scope, vehicle, now, guard), daemon=True)
            self.thread.start()
            return True

    def _run(self, scope, vehicle, now, guard):
        try:
            event_revision = self.analyzer.revision(vehicle)
            if not self.cache.due(scope, vehicle, now, event_revision): return
            if self.closed or not guard(): return
            try:
                report = self.analyzer.build(scope, vehicle, now)
            except Exception:
                report = None
            # SQL reads and archive scans stay outside the scheduler lock.
            if self.analyzer.revision(vehicle) != event_revision: return
            with self.lock:
                if self.closed or not guard(): return
                if report is None: self.cache.failure(scope, vehicle, now, event_revision)
                else: self.cache.success(scope, vehicle, now, report)
        except Exception:
            with self.lock:
                self.retry_after = now+INTERVAL_MS
            print('自动分析缓存读取或保存失败；采集继续，稍后重试。', flush=True)

    def close(self):
        with self.lock:
            self.closed = True
