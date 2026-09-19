"""Read-only, privacy-safe charging session, series and aggregate queries."""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sqlite3


BEIJING = timezone(timedelta(hours=8))
VALID_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
VALID_VIEWS = {'power-soc', 'electrical'}
VALID_MODES = {'all', 'ac', 'dc'}


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _mode(report):
    values = {part.get('charging_mode') for part in
              (report.get('start', {}), report.get('end', {}))
              if isinstance(part, dict)} - {None}
    return values.pop() if len(values) == 1 and next(iter(values), None) in ('ac', 'dc') else 'unknown'


def _metric_value(point, name):
    value = point.get(name)
    if isinstance(value, dict) and value.get('validity') == 'valid':
        return _number(value.get('value'))
    return None


class ChargingAnalytics:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        return sqlite3.connect(self.path)

    def _event(self, db, vehicle, selection):
        if not isinstance(selection, str) or not VALID_ID.fullmatch(selection):
            raise ValueError('充电会话 ID 无效。')
        if selection == 'current':
            row = db.execute('SELECT payload FROM monitor_state WHERE vehicle=?', (vehicle,)).fetchone()
            state = json.loads(row[0]) if row else {}
            charge = state.get('charge') if isinstance(state, dict) else None
            if not isinstance(charge, dict):
                return None
            start = charge.get('report_start') if isinstance(charge.get('report_start'), dict) else {}
            samples = charge.get('samples') if isinstance(charge.get('samples'), list) else []
            end = samples[-1] if samples and isinstance(samples[-1], dict) else start
            return {'id': 'current', 'status': 'active', 'partial': bool(charge.get('partial')),
                    'start_time': _number(start.get('state_time')),
                    'end_time': _number(end.get('state_time')),
                    'start': start, 'end': end, 'metrics': {}, 'mode': start.get('charging_mode')}
        row = db.execute('SELECT summary FROM monitor_events WHERE id=? AND vehicle=? AND kind=?',
                         (selection, vehicle, 'charge_end')).fetchone()
        if not row:
            raise ValueError('充电记录不存在或不属于当前车辆。')
        try:
            summary = json.loads(row[0])
        except (TypeError, ValueError):
            raise ValueError('充电记录无法读取。') from None
        report = summary.get('report_v2') if isinstance(summary.get('report_v2'), dict) else {}
        start = report.get('start') if isinstance(report.get('start'), dict) else {}
        end = report.get('end') if isinstance(report.get('end'), dict) else {}
        return {'id': selection, 'status': 'ended', 'partial': bool(summary.get('partial')),
                'start_time': _number(summary.get('start_time')),
                'end_time': _number(summary.get('end_time')),
                'start': start, 'end': end,
                'metrics': report.get('metrics') if isinstance(report.get('metrics'), dict) else {},
                'mode': _mode(report)}

    def session(self, vehicle, selection):
        if not vehicle:
            raise ValueError('请先选择车辆。')
        if not self.path.exists():
            return {'id': selection, 'status': 'empty'}
        with self._connect() as db:
            item = self._event(db, vehicle, selection)
        if item is None:
            return {'id': selection, 'status': 'empty'}
        start, end, metrics = item.pop('start'), item.pop('end'), item.pop('metrics')
        item.update({'start_soc': _number(start.get('soc')), 'end_soc': _number(end.get('soc')),
                     'power_kw': _number(end.get('power_kw')),
                     'remaining_minutes': _number(end.get('remaining_minutes')),
                     'range_km': _number(end.get('range_km')),
                     'sampled_peak_kw': _number(metrics.get('sampled_peak_kw')),
                     'average_power_kw': _number(metrics.get('average_power_kw')),
                     'power_coverage': _number(metrics.get('power_coverage')),
                     'power_sample_count': _number(metrics.get('power_sample_count'))})
        return item

    def series(self, vehicle, selection, view):
        if view not in VALID_VIEWS:
            raise ValueError('充电曲线视图无效。')
        if not self.path.exists():
            return {'id': selection, 'view': view, 'points': [], 'segments': [],
                    'raw_count': 0, 'display_count': 0, 'has_gaps': False}
        with self._connect() as db:
            item = self._event(db, vehicle, selection)
            if item is None or item['start_time'] is None:
                return {'id': selection, 'view': view, 'points': [], 'segments': [],
                        'raw_count': 0, 'display_count': 0, 'has_gaps': False}
            upper = item['end_time'] if item['end_time'] is not None else 32503680000000
            rows = db.execute('''SELECT normalized_payload,decoder_version FROM report_observations
                                 WHERE vehicle=? AND state_time>=? AND state_time<=?
                                 ORDER BY state_time''', (vehicle, item['start_time'], upper)).fetchall()
        parsed = []
        for encoded, decoder in rows:
            try:
                point = json.loads(encoded)
            except (TypeError, ValueError):
                continue
            if not isinstance(point, dict):
                continue
            parsed.append((point, decoder))
        public, segment, previous = [], 0, None
        for point, decoder in parsed:
            continuous = previous is not None
            if previous is not None:
                left, left_decoder = previous
                state_gap = point.get('state_time', 0) - left.get('state_time', 0)
                observed_gap = point.get('observed_at', 0) - left.get('observed_at', 0)
                continuous = (0 < state_gap <= 180000 and 0 <= observed_gap <= 180000
                              and point.get('charging') == left.get('charging')
                              and point.get('charging_mode') == left.get('charging_mode')
                              and decoder == left_decoder)
            if previous is not None and not continuous:
                segment += 1
            row = {'time': _number(point.get('state_time')), 'soc': _number(point.get('soc')),
                   'segment_id': segment, 'quality': 'valid' if point.get('charging') is True else 'stopped'}
            if view == 'power-soc':
                row['power_kw'] = _number(point.get('power_kw'))
            else:
                mode = point.get('charging_mode')
                row.update({'mode': mode if mode in ('ac', 'dc') else 'unknown',
                            'voltage': _metric_value(point, 'ac_voltage' if mode == 'ac' else 'voltage'),
                            'current': _metric_value(point, 'ac_current' if mode == 'ac' else 'current')})
            public.append(row)
            previous = (point, decoder)
        raw_count = len(public)
        public = self._downsample(public, 600)
        segments = []
        for sid in sorted({p['segment_id'] for p in public}):
            group = [p for p in public if p['segment_id'] == sid]
            segments.append({'id': sid, 'start_time': group[0]['time'], 'end_time': group[-1]['time'],
                             'point_count': len(group)})
        return {'id': selection, 'view': view, 'points': public, 'segments': segments,
                'raw_count': raw_count, 'display_count': len(public), 'has_gaps': len(segments) > 1,
                'downsampled': raw_count > len(public)}

    @staticmethod
    def _downsample(points, limit):
        if len(points) <= limit:
            return points
        keep = {0, len(points)-1}
        for index in range(1, len(points)):
            if points[index]['segment_id'] != points[index-1]['segment_id']:
                keep.update((index-1, index))
        value_key = 'power_kw' if 'power_kw' in points[0] else 'voltage'
        peak = max(range(len(points)), key=lambda i: points[i].get(value_key) or -1)
        keep.add(peak)
        available = max(0, limit-len(keep))
        if available:
            step = (len(points)-1) / (available+1)
            keep.update(round(index*step) for index in range(1, available+1))
        if len(keep) < limit:
            keep.update(index for index in range(len(points)) if index not in keep
                        and len(keep) < limit)
        selected = sorted(keep)
        if len(selected) > limit:
            protected = {0, len(points)-1, peak}
            boundary = set()
            for index in range(1, len(points)):
                if points[index]['segment_id'] != points[index-1]['segment_id']:
                    boundary.update((index-1, index))
            protected.update(boundary)
            removable = [index for index in selected if index not in protected]
            while len(selected) > limit and removable:
                selected.remove(removable.pop(len(removable)//2))
            selected = selected[:limit]
        return [points[index] for index in selected]

    def statistics(self, vehicle, days, mode, now=None):
        if type(days) is not int or days not in (7, 30) or mode not in VALID_MODES:
            raise ValueError('充电统计范围无效。')
        now = int(now if now is not None else datetime.now(tz=BEIJING).timestamp()*1000)
        end_day = datetime.fromtimestamp(now/1000, BEIJING).replace(hour=0, minute=0, second=0, microsecond=0)
        lower = int((end_day-timedelta(days=days-1)).timestamp()*1000)
        upper = int((end_day+timedelta(days=1)).timestamp()*1000)
        rows = []
        if self.path.exists():
            with self._connect() as db:
                rows = db.execute('''SELECT id,summary FROM monitor_events
                                     WHERE vehicle=? AND kind='charge_end' ORDER BY created DESC,id DESC''',
                                  (vehicle,)).fetchall()
        records = []
        for event_id, encoded in rows:
            try:
                summary = json.loads(encoded)
            except (TypeError, ValueError):
                continue
            ended = _number(summary.get('end_time'))
            if ended is None or not lower <= ended < upper:
                continue
            report = summary.get('report_v2') if isinstance(summary.get('report_v2'), dict) else {}
            event_mode = _mode(report)
            if mode != 'all' and event_mode != mode:
                continue
            metrics = report.get('metrics') if isinstance(report.get('metrics'), dict) else {}
            partial = bool(summary.get('partial'))
            delta = _number(summary.get('soc_delta'))
            capacity = _number(summary.get('battery_capacity_kwh'))
            estimate = capacity*delta/100 if not partial and capacity and delta is not None and delta >= 0 else None
            duration = _number(summary.get('duration_seconds')) if not partial else None
            records.append({'id': event_id, 'end_time': ended, 'start_time': _number(summary.get('start_time')),
                            'date': datetime.fromtimestamp(ended/1000, BEIJING).strftime('%Y-%m-%d'),
                            'mode': event_mode, 'partial': partial,
                            'start_soc': _number(summary.get('start_soc')),
                            'end_soc': _number(summary.get('end_soc')),
                            'soc_delta': delta, 'duration_seconds': duration,
                            'estimated_kwh': estimate,
                            'sampled_peak_kw': _number(metrics.get('sampled_peak_kw')),
                            'average_power_kw': _number(metrics.get('average_power_kw'))})
        daily = []
        for offset in range(days):
            date = (end_day-timedelta(days=days-1-offset)).strftime('%Y-%m-%d')
            same = [r for r in records if r['date'] == date]
            daily.append({'date': date, 'count': len(same),
                          'ac_kwh': sum(r['estimated_kwh'] or 0 for r in same if r['mode'] == 'ac'),
                          'dc_kwh': sum(r['estimated_kwh'] or 0 for r in same if r['mode'] == 'dc'),
                          'unknown_kwh': sum(r['estimated_kwh'] or 0 for r in same if r['mode'] == 'unknown')})
        complete = [r for r in records if not r['partial']]
        energy = [r['estimated_kwh'] for r in records if r['estimated_kwh'] is not None]
        try:
            current = self.session(vehicle, 'current')
        except (ValueError, sqlite3.Error, json.JSONDecodeError):
            current = {'id': 'current', 'status': 'empty'}
        return {'days': days, 'mode': mode, 'timezone': 'Asia/Shanghai', 'daily': daily,
                'current': current if current.get('status') == 'active' else None,
                'summary': {'ended_count': len(records), 'complete_count': len(complete),
                            'partial_count': len(records)-len(complete), 'estimated_kwh': sum(energy),
                            'included_energy_count': len(energy), 'excluded_energy_count': len(records)-len(energy),
                            'complete_duration_seconds': sum(r['duration_seconds'] or 0 for r in complete)},
                'records': records}
