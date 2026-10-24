"""Read-only, privacy-safe charging session, series and aggregate queries."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from .start_evidence import from_summary as start_evidence
from .trip_visibility import visible_clause
from .usage_events import project, total, number, MAX_SUMMARY_BYTES
from .charging_details import remaining_charge_minutes, number as _number
from .analysis_cancel import check_cancelled, configure_sqlite
from .data_contract import charge_mode as _mode


BEIJING = timezone(timedelta(hours=8))
VALID_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
VALID_VIEWS = {'power-soc', 'electrical'}
VALID_MODES = {'all', 'ac', 'dc'}


def _metric_value(point, name):
    value = point.get(name)
    if isinstance(value, dict) and value.get('validity') == 'valid':
        return _number(value.get('value'))
    return None


class ChargingAnalytics:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _connect(self, connection=None):
        check_cancelled()
        if connection is not None:
            yield connection
            return
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            configure_sqlite(db)
            yield db

    def _event(self, db, vehicle, selection):
        check_cancelled()
        if not isinstance(selection, str) or not VALID_ID.fullmatch(selection):
            raise ValueError('充电会话 ID 无效。')
        if selection == 'current':
            row = db.execute('SELECT CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END '
                             'FROM monitor_state WHERE vehicle=?', (MAX_SUMMARY_BYTES,vehicle)).fetchone()
            try:
                state = json.loads(row[0]) if row else {}
            except (TypeError,ValueError,RecursionError):
                raise ValueError('当前充电状态无法读取。') from None
            charge = state.get('charge') if isinstance(state, dict) else None
            if not isinstance(charge, dict):
                return None
            start = charge.get('report_start') if isinstance(charge.get('report_start'), dict) else {}
            samples = charge.get('samples') if isinstance(charge.get('samples'), list) else []
            end = samples[-1] if samples and isinstance(samples[-1], dict) else start
            return {'id': 'current', 'status': 'active', 'partial': charge.get('partial') is not False,
                    'start_evidence': start_evidence(charge, 'charge'),
                    'start_time': _number(start.get('state_time')),
                    'end_time': _number(end.get('state_time')),
                    'start': start, 'end': end, 'metrics': {}, 'mode': start.get('charging_mode')}
        row = db.execute('SELECT CASE WHEN length(CAST(e.summary AS BLOB))<=? THEN e.summary END '
                         'FROM monitor_events e WHERE e.id=? AND e.vehicle=? AND e.kind=? AND '
                         + visible_clause(db, 'e'),
                         (MAX_SUMMARY_BYTES,selection, vehicle, 'charge_end')).fetchone()
        if not row:
            raise ValueError('充电记录不存在或不属于当前车辆。')
        try:
            summary = json.loads(row[0])
        except (TypeError, ValueError, RecursionError):
            raise ValueError('充电记录无法读取。') from None
        if not isinstance(summary,dict):raise ValueError('充电记录无法读取。')
        report = summary.get('report_v2') if isinstance(summary.get('report_v2'), dict) else {}
        start = report.get('start') if isinstance(report.get('start'), dict) else {}
        end = report.get('end') if isinstance(report.get('end'), dict) else {}
        observed=project(selection,'charge_end',summary) or {}
        return {'id': selection, 'status': 'ended', 'partial': observed.get('partial',True),
                'start_evidence': start_evidence(summary, 'charge'),
                'start_time': _number(summary.get('start_time')),
                'end_time': _number(summary.get('end_time')),
                'start': start, 'end': end,
                'metrics': report.get('metrics') if isinstance(report.get('metrics'), dict) else {},
                'mode': _mode(report)}

    def session(self, vehicle, selection, *, _connection=None):
        if not vehicle:
            raise ValueError('请先选择车辆。')
        if not self.path.exists():
            return {'id': selection, 'status': 'empty'}
        with self._connect(_connection) as db:
            item = self._event(db, vehicle, selection)
        if item is None:
            return {'id': selection, 'status': 'empty'}
        start, end, metrics = item.pop('start'), item.pop('end'), item.pop('metrics')
        item.update({'start_soc': _number(start.get('soc')), 'end_soc': _number(end.get('soc')),
                     'power_kw': _number(end.get('power_kw')),
                     'remaining_minutes': remaining_charge_minutes(end.get('remaining_minutes')),
                     'range_km': _number(end.get('range_km')),
                     'sampled_peak_kw': _number(metrics.get('sampled_peak_kw')),
                     'average_power_kw': _number(metrics.get('average_power_kw')),
                     'power_coverage': _number(metrics.get('power_coverage')),
                     'power_sample_count': _number(metrics.get('power_sample_count'))})
        return item

    def process(self, vehicle, selection, view):
        """Return the process summary and chart series in one response."""
        if not self.path.exists():
            return {'session': self.session(vehicle, selection),
                    'series': self.series(vehicle, selection, view)}
        with self._connect() as db:
            # Active state/observations do not advance the ended-event revision.
            # Keep both reads on this snapshot while collection continues.
            db.execute('BEGIN')
            return {'session': self.session(vehicle, selection, _connection=db),
                    'series': self.series(vehicle, selection, view, _connection=db)}

    def series(self, vehicle, selection, view, *, _connection=None):
        if view not in VALID_VIEWS:
            raise ValueError('充电曲线视图无效。')
        if not self.path.exists():
            return {'id': selection, 'view': view, 'points': [], 'segments': [],
                    'raw_count': 0, 'display_count': 0, 'has_gaps': False}
        with self._connect(_connection) as db:
            item = self._event(db, vehicle, selection)
            if item is None or item['start_time'] is None:
                return {'id': selection, 'view': view, 'points': [], 'segments': [],
                        'raw_count': 0, 'display_count': 0, 'has_gaps': False}
            upper = item['end_time'] if item['end_time'] is not None else 32503680000000
            rows = db.execute('''SELECT state_time,observed_at,
                                 CASE WHEN length(CAST(normalized_payload AS BLOB))<=? THEN normalized_payload END,
                                 decoder_version FROM report_observations
                                 WHERE vehicle=? AND state_time>=? AND state_time<=?
                                 ORDER BY state_time''', (MAX_SUMMARY_BYTES, vehicle, item['start_time'], upper))
            public, segment, previous, broken = [], 0, None, False
            value_keys = ('power_kw','soc') if view == 'power-soc' else ('voltage','current')
            line_counts = dict.fromkeys(value_keys,0)
            for stamp, observed, encoded, decoder in rows:
                check_cancelled()
                try:
                    point = json.loads(encoded)
                except (TypeError, ValueError, RecursionError):
                    broken = True
                    continue
                if (not isinstance(point, dict)
                        or number(stamp,1,32503680000000) is None
                        or number(observed,1,32503680000000) is None
                        or number(point.get('state_time'),1,32503680000000) != stamp
                        or number(point.get('observed_at'),1,32503680000000) != observed
                        or not -30000 <= observed-stamp <= 180000):
                    broken = True
                    continue
                continuous = previous is not None and not broken
                if previous is not None:
                    left, left_decoder = previous
                    state_gap = point.get('state_time', 0) - left.get('state_time', 0)
                    observed_gap = point.get('observed_at', 0) - left.get('observed_at', 0)
                    continuous = (not broken and 0 < state_gap <= 180000 and 0 <= observed_gap <= 180000
                                  and point.get('sampling_gap_before') is not True
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
                row['lines'] = {}
                for key in value_keys:
                    if row[key] is None:
                        row['lines'][key] = None
                    else:
                        if not public or public[-1][key] is None or public[-1]['segment_id'] != segment:
                            line_counts[key] += 1
                        row['lines'][key] = line_counts[key]
                public.append(row)
                previous = (point, decoder)
                broken = False
        raw_count = len(public)
        public = self._downsample(public, 600)
        segments = []
        for sid in sorted({p['segment_id'] for p in public}):
            group = [p for p in public if p['segment_id'] == sid]
            segments.append({'id': sid, 'start_time': group[0]['time'], 'end_time': group[-1]['time'],
                             'point_count': len(group)})
        return {'id': selection, 'view': view, 'points': public, 'segments': segments,
                'raw_count': raw_count, 'display_count': len(public),
                'has_gaps': len(segments) > 1 or any(count>1 for count in line_counts.values()),
                'downsampled': raw_count > len(public)}

    @staticmethod
    def _downsample(points, limit):
        check_cancelled()
        if len(points) <= limit:
            return points
        keys = ('power_kw','soc') if 'power_kw' in points[0] else ('voltage','current')
        anchors = {0, len(points)-1}
        for key in keys:
            low = high = None
            for index,point in enumerate(points):
                if index % 256 == 0:check_cancelled()
                value = point.get(key)
                if value is None:continue
                if low is None or value < points[low][key]:low = index
                if high is None or value > points[high][key]:high = index
            if low is not None:anchors.update((low,high))
        keep = set(anchors)
        for index in range(1, len(points)):
            check_cancelled()
            left,right = points[index-1],points[index]
            if (right['segment_id'] != left['segment_id']
                    or any(right.get('lines',{}).get(key) != left.get('lines',{}).get(key)
                           or (right.get(key) is None) != (left.get(key) is None) for key in keys)):
                keep.update((index-1, index))
        available = max(0, limit-len(keep))
        if available:
            step = (len(points)-1) / (available+1)
            keep.update(round(index*step) for index in range(1, available+1))
        if len(keep) < limit:
            keep.update(index for index in range(len(points)) if index not in keep
                        and len(keep) < limit)
        selected = sorted(keep)
        if len(selected) > limit:
            # Too many boundaries cannot all fit. Keep endpoints and extrema and
            # spread the remaining boundary samples across the whole session.
            candidates = [index for index in selected if index not in anchors]
            slots = limit-len(anchors)
            step = (len(candidates)-1)/max(1,slots-1)
            selected = sorted(anchors | {candidates[round(index*step)] for index in range(slots)})
        return [points[index] for index in selected]

    def statistics(self, vehicle, days, mode, now=None):
        check_cancelled()
        if type(days) is not int or days not in (7, 30) or mode not in VALID_MODES:
            raise ValueError('充电统计范围无效。')
        now = int(now if now is not None else datetime.now(tz=BEIJING).timestamp()*1000)
        end_day = datetime.fromtimestamp(now/1000, BEIJING).replace(hour=0, minute=0, second=0, microsecond=0)
        lower = int((end_day-timedelta(days=days-1)).timestamp()*1000)
        upper = int((end_day+timedelta(days=1)).timestamp()*1000)
        records = []
        if self.path.exists():
            with self._connect() as db:
                rows = db.execute('''SELECT e.id,CASE WHEN length(CAST(e.summary AS BLOB))<=? THEN e.summary END
                                     FROM monitor_events e
                                     WHERE e.vehicle=? AND e.kind='charge_end' AND '''
                                  + visible_clause(db, 'e') + ''' ORDER BY e.created DESC,e.id DESC''',
                                  (MAX_SUMMARY_BYTES,vehicle))
                for event_id, encoded in rows:
                    check_cancelled()
                    try:
                        summary = json.loads(encoded)
                    except (TypeError, ValueError, RecursionError):
                        continue
                    if not isinstance(summary, dict):
                        continue
                    event = project(event_id, 'charge_end', summary)
                    if event is None:
                        continue
                    ended = event['end_time']
                    if not lower <= ended < upper or ended > now:
                        continue
                    report = summary.get('report_v2') if isinstance(summary.get('report_v2'), dict) else {}
                    event_mode = _mode(report)
                    if mode != 'all' and event_mode != mode:
                        continue
                    metrics = report.get('metrics') if isinstance(report.get('metrics'), dict) else {}
                    records.append({'id': event_id, 'end_time': ended, 'start_time': event['start_time'],
                                    'date': datetime.fromtimestamp(ended/1000, BEIJING).strftime('%Y-%m-%d'),
                                    'mode': event_mode, 'partial': event['partial'],
                                    'start_soc': event['start_soc'], 'end_soc': event['end_soc'],
                                    'soc_delta': event['soc_delta'], 'duration_seconds': event['duration_seconds'],
                                    'estimated_kwh': event['estimated_kwh'],
                                    'sampled_peak_kw': _number(metrics.get('sampled_peak_kw')),
                                    'average_power_kw': _number(metrics.get('average_power_kw'))})
        daily = []
        for offset in range(days):
            check_cancelled()
            date = (end_day-timedelta(days=days-1-offset)).strftime('%Y-%m-%d')
            same = [r for r in records if r['date'] == date]
            daily.append({'date': date, 'count': len(same),
                          'estimated_kwh': total(r['estimated_kwh'] for r in same),
                          'ac_kwh': total(r['estimated_kwh'] for r in same if r['mode'] == 'ac'),
                          'dc_kwh': total(r['estimated_kwh'] for r in same if r['mode'] == 'dc'),
                          'unknown_kwh': total(r['estimated_kwh'] for r in same if r['mode'] == 'unknown')})
        complete = [r for r in records if not r['partial']]
        energy = [r['estimated_kwh'] for r in records if r['estimated_kwh'] is not None]
        try:
            current = self.session(vehicle, 'current')
        except (ValueError, sqlite3.Error, json.JSONDecodeError):
            current = {'id': 'current', 'status': 'empty'}
        return {'days': days, 'mode': mode, 'timezone': 'Asia/Shanghai', 'daily': daily,
                'current': current if current.get('status') == 'active' else None,
                'summary': {'ended_count': len(records), 'complete_count': len(complete),
                            'partial_count': len(records)-len(complete), 'estimated_kwh': total(energy),
                            'included_energy_count': len(energy), 'excluded_energy_count': len(records)-len(energy),
                            'partial_energy_count': sum(r['partial'] and r['estimated_kwh'] is not None for r in records),
                            'duration_seconds': total(r['duration_seconds'] for r in records),
                            'included_duration_count': sum(r['duration_seconds'] is not None for r in records),
                            'complete_duration_seconds': total(r['duration_seconds'] for r in complete)},
                'records': records}
