"""Persistent, conservative trip/charging transitions and notification outbox."""
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .notifications import DeliveryError, bark_time
from .summary import updated_at
from .vehicle_state import decode, numeric
from .tracks import TrackStore
from .web_model import parse_location
from .report_telemetry import normalize, DECODER_VERSION
from .report_metrics import trip_metrics, charge_metrics
from .report_render import render
from .report_markdown import markdown_for
from .trip_notification_image import render_trip_png
from .report_history import compare
from .report_attention import build as build_attention
from .start_evidence import build as start_evidence, project as project_start
from .start_evidence import from_summary as saved_start_evidence, MAX_GAP
from .notification_location import select_location, reference_suffix

MAX_AGE = MAX_GAP
STOP_WAIT = 600000
MAX_SESSION_SAMPLES = 1000


def _append_sample(activity, telemetry):
    samples = activity.setdefault('samples', [])
    if samples and telemetry.get('state_time') == samples[-1].get('state_time'):
        return
    samples.append(telemetry)
    if len(samples) > MAX_SESSION_SAMPLES:
        samples[1:2] = []
        activity['samples_truncated'] = True


def summary(start, end, partial=False):
    distance = end['km'] - start['km'] if end['km'] is not None and start['km'] is not None else None
    if distance is not None and distance < 0:
        distance = None
        partial = True
    delta = end['soc'] - start['soc'] if end['soc'] is not None and start['soc'] is not None else None
    return {'start_time': start['time'], 'end_time': end['time'],
            'duration_seconds': (end['time'] - start['time']) / 1000,
            'distance_km': round(distance, 3) if distance is not None else None,
            'start_soc': start['soc'], 'end_soc': end['soc'],
            'start_location': start.get('location'), 'end_location': end.get('location'),
            'soc_delta': round(delta, 3) if delta is not None else None, 'partial': partial}


def fmt(value, unit=''):
    return '未知' if value is None else ('%.2f' % value).rstrip('0').rstrip('.') + unit


def message_for(kind, data, event_id):
    title = {'trip_start': '检测到行程开始', 'trip_end': '本次行程已结束',
             'charge_start': '检测到开始充电', 'charge_end': '充电已停止'}[kind]
    lines = [title]
    if kind in ('trip_start', 'trip_end'):
        lines.append('出发地：' + _notification_address(data, 'start'))
        if kind == 'trip_end':
            lines.append('到达地：' + _notification_address(data, 'end'))
    else:
        lines += ['充电地点：' + _notification_address(data, 'start')]
    if kind in ('trip_start', 'charge_start'):
        lines += ['观测时间：' + updated_at(data['start_time']), '电量：' + fmt(data['start_soc'], '%')]
        if data['partial']:
            lines += ['实际开始时间未知；首次观测时已在%s。' % ('行驶' if kind == 'trip_start' else '充电')]
    else:
        lines += ['开始：' + updated_at(data['start_time']), '结束：' + updated_at(data['end_time']),
                  '观测时长：' + fmt(data['duration_seconds'] / 60, ' 分钟')]
        if kind == 'trip_end':
            lines += ['里程：' + fmt(data['distance_km'], ' km')]
        lines += ['电量：%s → %s' % (fmt(data['start_soc'], '%'), fmt(data['end_soc'], '%')),
                  '电量变化：' + fmt(data['soc_delta'], ' 个百分点')]
        capacity = numeric(data.get('battery_capacity_kwh'), .1, 1000)
        start = numeric(data.get('start_soc'), 0, 100)
        end = numeric(data.get('end_soc'), 0, 100)
        delta = numeric(data.get('soc_delta'), -100, 100)
        expected = (end - start) if start is not None and end is not None else None
        amount = delta if kind == 'charge_end' else -delta if delta is not None else None
        if (capacity is not None and amount is not None and amount >= 0
                and expected is not None and abs(expected - delta) < .001):
            label = '估算充入电量' if kind == 'charge_end' else '估算耗电量'
            lines += [label + '：%.1f kWh' % (capacity * amount / 100)]
        else:
            lines += ['kWh：暂无可靠数据']
        if data['partial']:
            lines += ['数据不完整：起点或期间观测存在缺口，仅汇总已观测部分。']
    lines += ['来源：车辆云端缓存，时间可能延迟。', '事件编号：' + event_id[:12]]
    return '\n'.join(lines)


def _notification_address(data, prefix):
    address = data.get(prefix + '_address')
    return address + reference_suffix(data.get(prefix + '_location_reference')) if address else '位置未知'


def bark_message_for(kind, data):
    titles = {'trip_start': '🚗 极氪行程开始', 'trip_end': '🚗 极氪行程结束', 'charge_start': '⚡ 极氪开始充电',
              'charge_end': '🔋 极氪充电结束'}
    starting = kind in ('trip_start', 'charge_start')
    when = data.get('start_time') if starting else data.get('end_time')
    lines = [('时间：' if starting else '结束时间：') + bark_time(when)]
    soc = data.get('start_soc') if starting else data.get('end_soc')
    if soc is not None:
        lines.append('当前电量：' + fmt(soc, '%'))
    if data.get('partial'):
        lines.append('本次只有部分记录')
    if kind == 'trip_end':
        lines.append('行程详情和路线图由企业微信发送')
    elif kind == 'charge_end':
        lines.append('充电详情由企业微信发送')
    return titles[kind], '\n'.join(lines)


class Monitor:
    def __init__(self, database_path, active_codes=(), stopped_codes=(), address_resolver=None, map_renderer=None):
        self.address_resolver = address_resolver
        self.map_renderer = map_renderer
        self.tracks = TrackStore(database_path)
        self.active_codes, self.stopped_codes = active_codes, stopped_codes
        with self.tracks.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS monitor_state (vehicle TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS monitor_events (
                id TEXT PRIMARY KEY, vehicle TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL,
                message TEXT NOT NULL, created INTEGER NOT NULL, delivery TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt INTEGER NOT NULL DEFAULT 0,
                error TEXT, sent_at INTEGER)''')
            db.execute('CREATE INDEX IF NOT EXISTS monitor_delivery ON monitor_events(delivery, next_attempt)')
            db.execute('CREATE INDEX IF NOT EXISTS monitor_vehicle_kind_created '
                       'ON monitor_events(vehicle,kind,created DESC,id DESC)')
            db.execute('CREATE INDEX IF NOT EXISTS monitor_vehicle_created '
                       'ON monitor_events(vehicle,created DESC)')
            db.execute('''CREATE TABLE IF NOT EXISTS monitor_event_media (
                event_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                delivery TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt INTEGER NOT NULL DEFAULT 0, error TEXT, sent_at INTEGER)''')
            db.execute('CREATE INDEX IF NOT EXISTS monitor_media_delivery '
                       'ON monitor_event_media(delivery,next_attempt)')
            db.execute('''CREATE TABLE IF NOT EXISTS monitor_event_alerts (
                event_id TEXT PRIMARY KEY, delivery TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt INTEGER NOT NULL DEFAULT 0,
                error TEXT, sent_at INTEGER)''')
            db.execute('CREATE INDEX IF NOT EXISTS monitor_alert_delivery '
                       'ON monitor_event_alerts(delivery,next_attempt)')
            db.execute('''CREATE TABLE IF NOT EXISTS report_metric_index (
                event_id TEXT PRIMARY KEY, vehicle TEXT NOT NULL, kind TEXT NOT NULL,
                end_time INTEGER NOT NULL, decoder_version TEXT NOT NULL,
                partial INTEGER NOT NULL, metrics TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS report_metric_lookup ON report_metric_index(vehicle,kind,end_time DESC)')
            db.execute('''CREATE TABLE IF NOT EXISTS report_observations (
                vehicle TEXT NOT NULL, state_time INTEGER NOT NULL, observed_at INTEGER NOT NULL,
                normalized_payload TEXT NOT NULL, decoder_version TEXT NOT NULL,
                PRIMARY KEY(vehicle,state_time))''')
            db.execute('CREATE INDEX IF NOT EXISTS report_observation_time ON report_observations(vehicle,state_time)')
            db.execute("UPDATE monitor_events SET delivery='uncertain', error='发送期间进程中断，需人工确认' WHERE delivery='sending'")
            db.execute("UPDATE monitor_event_media SET delivery='uncertain', error='图片发送期间进程中断，需人工确认' WHERE delivery='sending'")
            db.execute("UPDATE monitor_event_alerts SET delivery='uncertain', error='Bark 发送期间进程中断，需人工确认' WHERE delivery='sending'")

    def status(self, vehicle):
        with self.tracks.connect() as db:
            row = db.execute('SELECT payload FROM monitor_state WHERE vehicle=?', (vehicle,)).fetchone()
        return json.loads(row[0]) if row else {'last': None, 'trip': None, 'charge': None}

    def _event(self, db, vehicle, kind, data, now):
        identity = '%s:%s:%s' % (vehicle, kind, data['start_time'])
        event_id = hashlib.sha256(identity.encode()).hexdigest()
        message = message_for(kind, data, event_id)
        if data.get('report_v2'):
            report = data['report_v2']
            report['event_created_at'] = now
            report['attention'] = build_attention(kind, report.get('end'), report.get('parking'), now)
            report['parking_changes'] = report['attention'].get('changes', [])
            if kind in ('trip_end', 'charge_end'):
                try:
                    report['comparison'] = compare(db, vehicle, report)
                except Exception:
                    report['comparison'] = {'version': 'history-v1', 'available': False, 'reason': 'unavailable'}
            message, omitted = render(kind, data['report_v2'], event_id)
            data['report_v2']['render'] = {'version': 'zh-text-v2', 'omitted': omitted,
                                           'message_frozen': False}
        db.execute('INSERT OR IGNORE INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                   (event_id, vehicle, kind, json.dumps(data, ensure_ascii=False), message, now))
        db.execute('INSERT OR IGNORE INTO monitor_event_alerts (event_id) VALUES (?)', (event_id,))
        if kind == 'trip_end':
            db.execute('INSERT OR IGNORE INTO monitor_event_media (event_id,kind) VALUES (?,?)',
                       (event_id, 'trip_image'))
        report = data.get('report_v2')
        if report:
            approved = {key:value for key,value in report.get('metrics',{}).items()
                        if type(value) in (int,float)}
            db.execute('INSERT OR IGNORE INTO report_metric_index VALUES (?,?,?,?,?,?,?)',
                       (event_id, vehicle, kind, int(report.get('end_time') or now),
                        report.get('decoder_version',''), int(bool(report.get('partial'))),
                        json.dumps(approved, separators=(',',':'))))

    def _report(self, kind, start, end, samples, profile, partial, charge_overlap=False, parking=None,
                upgrade_mid_session=False, samples_truncated=False, decoder_changed=False, parking_samples=0,
                start_timing=None):
        # Keep short-stop observations if driving resumes, but exclude the final
        # parking confirmation window from the frozen trip's statistics.
        if start.get('state_time') is not None and end.get('state_time') is not None:
            samples = [sample for sample in samples
                       if sample.get('state_time') is not None
                       and start['state_time'] <= sample['state_time'] <= end['state_time']]
        metrics = (trip_metrics(start, end, samples, profile, partial=partial, charge_overlap=charge_overlap)
                   if kind == 'trip_end' else charge_metrics(start, end, samples, profile, partial=partial)
                   if kind == 'charge_end' else {})
        if decoder_changed:
            for key in ('estimated_kwh_100km', 'range_attainment_percent', 'inside_temp_delta',
                        'outside_temp_delta', 'average_power_kw', 'tail_power_drop_percent'):
                if key in metrics: metrics[key] = None
        coverage = {'accepted_samples': len(samples), 'window_seconds': metrics.get('duration_seconds'),
                    'max_state_gap_s': metrics.get('max_state_gap_seconds'),
                    'max_observed_gap_s': metrics.get('max_observed_gap_seconds'),
                    'max_observation_gap_s': metrics.get('max_gap_seconds'),
                    'power_covered_seconds': metrics.get('power_covered_seconds'),
                    'power_coverage': metrics.get('power_coverage'),
                    'charging_time_coverage': metrics.get('charging_time_coverage')}
        return {'schema_version': 2, 'metric_version': 'metrics-v1', 'decoder_version': DECODER_VERSION, 'kind': kind,
                'start_time': start.get('state_time'), 'end_time': end.get('state_time'),
                'start_evidence': project_start(start_timing),
                'start': start, 'end': end, 'parking': parking, 'metrics': metrics,
                'statistics': metrics, 'coverage': coverage,
                'partial': partial, 'profile_snapshot': profile,
                'quality': {'observation_count': len(samples), 'upgrade_mid_session': upgrade_mid_session,
                            'parking_samples': parking_samples,
                            'samples_truncated': samples_truncated,
                            'decoder_changed_mid_session': decoder_changed,
                            'quality_reasons': (['upgrade_mid_session'] if upgrade_mid_session else []) +
                                               (['decoder_changed_mid_session'] if decoder_changed else []) +
                                               (['late_start'] if partial else []) +
                                               (['charge_overlap'] if charge_overlap else [])}}

    def _finish_trip(self, db, vehicle, trip, now, battery_capacity_kwh, profile):
        data = summary(trip['start'], trip['stop'], trip['partial'])
        data['start_evidence'] = saved_start_evidence(trip, 'trip')
        data['battery_capacity_kwh'] = battery_capacity_kwh
        charge_overlap = (trip.get('charging_time') is not None
                          and trip['charging_time'] <= trip['stop']['time'])
        if charge_overlap:
            data['soc_delta'] = None
            data['partial'] = True
        data['report_v2'] = self._report(
            'trip_end', trip['report_start'], trip['report_end'], trip.get('samples', []),
            trip.get('profile', profile), data['partial'], charge_overlap,
            parking=trip.get('parking'), upgrade_mid_session=trip.get('report_upgrade', False),
            samples_truncated=trip.get('samples_truncated', False),
            decoder_changed=trip.get('decoder_changed', False),
            parking_samples=trip.get('parking_samples', 0), start_timing=data['start_evidence'])
        self._event(db, vehicle, 'trip_end', data, now)

    def observe(self, vehicle, raw, now, battery_capacity_kwh=None, profile=None):
        point = decode(raw, self.active_codes, self.stopped_codes)
        profile = {key:value for key,value in dict(profile or {}).items()
                   if key in ('battery_capacity_kwh','range_km','range_standard','range_source')}
        if battery_capacity_kwh is not None:
            profile.setdefault('battery_capacity_kwh', battery_capacity_kwh)
        telemetry = normalize(raw, now, active_codes=self.active_codes, stopped_codes=self.stopped_codes)
        state = self.status(vehicle)
        previous = state['last']
        timestamp = point['time']
        trip = state['trip']
        if trip and 'report_start' not in trip:
            trip.update(report_start=telemetry, report_end=telemetry, samples=[telemetry],
                        profile=profile, parking=None, report_upgrade=True, partial=True)
        charge = state['charge']
        reclassified_charge_stop = (previous is not None and charge is not None
                                    and timestamp == previous.get('time')
                                    and previous.get('charging') is None
                                    and point.get('charging') is False
                                    and point.get('charging_phase') == 'stopped')
        had_activity = bool(trip or charge)
        if charge and 'report_start' not in charge:
            charge.update(report_start=telemetry, samples=[telemetry], profile=profile,
                          report_upgrade=True, partial=True)
        for activity in (trip, charge):
            if activity and activity.get('report_start', {}).get('decoder_version') != telemetry.get('decoder_version'):
                activity['decoder_changed'] = True
                activity['partial'] = True
        repeated_stop = (previous and trip and trip['stop'] and timestamp == previous['time']
                         and point['off'] is True and point['charging'] is False
                         and point['speed'] in (None, 0) and point['km'] == trip['stop']['km'])
        if repeated_stop:
            confirmation = trip.get('stop_confirmation') or {
                'started': trip['stop']['observed'], 'observed': trip['stop']['observed']}
            if not 0 <= now - confirmation['observed'] <= MAX_AGE:
                confirmation['started'] = now
            confirmation['observed'] = now
            trip['stop_confirmation'] = confirmation
            with self.tracks.connect() as db:
                if now - confirmation['started'] >= STOP_WAIT:
                    self._finish_trip(db, vehicle, trip, now, battery_capacity_kwh, profile)
                    state['trip'] = None
                db.execute('INSERT OR REPLACE INTO monitor_state VALUES (?,?)',
                           (vehicle, json.dumps(state)))
            return 'stale' if not -30000 <= now - timestamp <= MAX_AGE else 'unchanged'
        if (timestamp is None or not -30000 <= now - timestamp <= MAX_AGE) and not reclassified_charge_stop:
            return 'stale'
        if previous and timestamp <= previous['time'] and not reclassified_charge_stop:
            return 'unchanged'
        observed = previous.get('observed', now) if reclassified_charge_stop else now
        point['observed'] = observed
        if reclassified_charge_stop:
            telemetry['observed_at'] = observed
        point['location'] = parse_location(raw)
        point['_report'] = telemetry
        continuous = (reclassified_charge_stop or
                      previous is not None and timestamp - previous['time'] <= MAX_AGE
                      and 0 <= now - previous['observed'] <= MAX_AGE)
        seed_telemetry = None
        trip_started = False
        moving = point['speed'] is not None and point['speed'] > 0
        distance_moved = continuous and previous['km'] is not None and point['km'] is not None and point['km'] > previous['km']
        confirmation = trip.get('stop_confirmation') if trip else None
        parking_continuous = (trip and trip['stop'] and confirmation
                              and 0 <= now - confirmation['observed'] <= MAX_AGE
                              and point['off'] is True and not moving
                              and point['km'] == trip['stop']['km'])
        if trip and not continuous and not parking_continuous:
            trip['partial'], trip['stop'] = True, None
        if trip is None and (moving or distance_moved):
            start = previous if continuous and previous.get('charging') is not True else point
            start_raw = start.get('_report', telemetry)
            seed_telemetry = start_raw
            trip = {'start': start, 'stop': None, 'partial': not continuous, 'charging_time': None,
                    'report_start': start_raw, 'report_end': telemetry, 'samples': [start_raw],
                    'profile': profile, 'parking': None,
                    'start_evidence': start_evidence('trip', previous, point, continuous)}
            trip_started = True
        if trip:
            # The first arrival can include the last driven distance. Once a
            # stop is frozen, further distance is evidence of resumed motion.
            resumed_motion = moving or (trip['stop'] is not None and distance_moved)
            if trip['stop'] is None or resumed_motion or point['off'] is not True:
                # A short stop only belongs to the trip if driving resumes.
                # Final parking must not evict driving samples at the cap.
                parking_buffer = trip.pop('parking_buffer', {})
                for sample in parking_buffer.get('samples', []):
                    _append_sample(trip, sample)
                if parking_buffer.get('samples_truncated'):
                    trip['samples_truncated'] = True
                _append_sample(trip, telemetry)
            else:
                _append_sample(trip.setdefault('parking_buffer', {}), telemetry)
            # TrackStore deduplicates replays if state commit is interrupted.
            if trip['stop'] is None or resumed_motion:
                self.tracks.record(vehicle, raw, now, 180)
            if point['charging'] is True and trip.get('charging_time') is None:
                trip['charging_time'] = timestamp
            if resumed_motion or point['off'] is not True:
                trip['stop'] = None
                trip['parking'] = None
                trip['parking_samples'] = 0
                trip.pop('stop_confirmation', None)
            elif trip['stop'] is None:
                trip['stop'] = point
                trip['report_end'] = telemetry
                trip['parking'] = telemetry
                trip['parking_samples'] = 0
                trip['stop_confirmation'] = {'started': now, 'observed': now}
            elif point['off'] is True:
                trip['parking'] = telemetry
                trip['parking_samples'] = trip.get('parking_samples', 0) + 1
                trip.setdefault('stop_confirmation', {
                    'started': trip['stop']['observed']})['observed'] = now
        if charge:
            if not continuous:
                charge['partial'] = True
            # Unknown or conflicting observations must break interpolation;
            # they do not independently end or restart the charge session.
            _append_sample(charge, telemetry)
        with self.tracks.connect() as db:
            if trip_started:
                self._event(db, vehicle, 'trip_start', summary(point, point, trip['partial']), now)
            if (trip and trip['stop'] and charge is None
                    and point['charging'] is True and point['off'] is True
                    and continuous and not moving and not distance_moved
                    and point['km'] == trip['stop']['km']):
                self._finish_trip(db, vehicle, trip, now, battery_capacity_kwh, profile)
                trip = None
            if (trip and trip['stop'] and timestamp - trip['stop']['time'] >= STOP_WAIT
                    and now - trip['stop_confirmation']['started'] >= STOP_WAIT):
                self._finish_trip(db, vehicle, trip, now, battery_capacity_kwh, profile)
                trip = None
            if point['charging'] is True and charge is None:
                charge = {'start': point, 'partial': not continuous or previous['charging'] is not False,
                          'report_start': telemetry, 'samples': [telemetry], 'profile': profile,
                          'start_evidence': start_evidence('charge', previous, point, continuous)}
                start_data = summary(point, point, charge['partial'])
                start_data['start_evidence'] = charge['start_evidence']
                start_data['report_v2'] = self._report('charge_start', telemetry, telemetry, [telemetry], profile,
                    charge['partial'], start_timing=charge['start_evidence'])
                self._event(db, vehicle, 'charge_start', start_data, now)
            elif point['charging'] is False and charge:
                data = summary(charge['start'], point, charge['partial'])
                data['start_evidence'] = saved_start_evidence(charge, 'charge')
                data['battery_capacity_kwh'] = battery_capacity_kwh
                samples = charge.get('samples', [])
                data['report_v2'] = self._report('charge_end', charge['report_start'], telemetry,
                                                 samples, charge.get('profile', profile), charge['partial'],
                                                 upgrade_mid_session=charge.get('report_upgrade', False),
                                                 samples_truncated=charge.get('samples_truncated', False),
                                                 decoder_changed=charge.get('decoder_changed', False),
                                                 start_timing=data['start_evidence'])
                self._event(db, vehicle, 'charge_end', data, now)
                charge = None
            state.update(last=point, trip=trip, charge=charge)
            active_or_transition = had_activity or bool(trip or charge)
            if active_or_transition:
                if seed_telemetry and seed_telemetry.get('state_time') is not None:
                    db.execute('INSERT OR IGNORE INTO report_observations VALUES (?,?,?,?,?)',
                               (vehicle, int(seed_telemetry['state_time']), seed_telemetry['observed_at'],
                                json.dumps(seed_telemetry, ensure_ascii=False), DECODER_VERSION))
                db.execute('INSERT OR IGNORE INTO report_observations VALUES (?,?,?,?,?)',
                           (vehicle, int(telemetry['state_time']), now,
                            json.dumps(telemetry, ensure_ascii=False), DECODER_VERSION))
            db.execute('INSERT OR REPLACE INTO monitor_state VALUES (?,?)', (vehicle, json.dumps(state)))
        return 'fresh'

    def events(self, limit=100, include_alerts=False):
        with self.tracks.connect() as db:
            where = '' if include_alerts else "WHERE e.kind!='trip_start'"
            rows = db.execute('''SELECT e.id,e.kind,e.summary,e.message,e.delivery,e.attempts,e.error,
                m.delivery,m.error,a.delivery,a.error FROM monitor_events e
                LEFT JOIN monitor_event_media m ON m.event_id=e.id
                LEFT JOIN monitor_event_alerts a ON a.event_id=e.id
                ''' + where + ' ORDER BY e.created,e.rowid LIMIT ?', (limit,)).fetchall()
        return [dict(id=r[0], kind=r[1], summary=json.loads(r[2]), message=r[3], delivery=r[4],
                     attempts=r[5], error=r[6], image_delivery=r[7], image_error=r[8],
                     alert_delivery=r[9], alert_error=r[10]) for r in rows]

    def deliver(self, sender, now, alert_sender=None):
        if alert_sender is not None:
            self._deliver_alerts(alert_sender, now)
        # One worker owns the process lock; compare-and-set also guards claims.
        with self.tracks.connect() as db:
            extra = " AND kind!='trip_start'" + (" AND kind!='charge_start'" if alert_sender is not None else '')
            rows = db.execute("SELECT id,message,attempts,kind,summary,vehicle FROM monitor_events WHERE delivery='pending' AND next_attempt<=?" + extra + " ORDER BY created,rowid LIMIT 10", (now,)).fetchall()
        for event_id, message, attempts, kind, encoded, vehicle in rows:
            with self.tracks.connect() as db:
                claimed = db.execute("UPDATE monitor_events SET delivery='sending', attempts=attempts+1 WHERE id=? AND delivery='pending'", (event_id,)).rowcount
            if not claimed:
                continue
            error, next_attempt, sent_at = None, 0, None
            sender_called = False
            try:
                data = json.loads(encoded)
                if data.get('report_v2') and data['report_v2'].get('schema_version') != 2:
                    raise ValueError('未知报告版本')
                frozen = data.get('report_v2', {}).get('render', {}).get('message_frozen') is True
                if not data.get('addresses_resolved') and not frozen:
                    if (data.get('report_v2') and
                            data['report_v2'].get('render', {}).get('version') not in (None, 'zh-text-v2')):
                        raise ValueError('未知渲染器版本')
                    for prefix in ('start', 'end') if kind == 'trip_end' else ('start',):
                        address = None
                        if self.address_resolver:
                            try:
                                with self.tracks.connect() as db:
                                    location, reference = select_location(db, vehicle,
                                        data.get(prefix + '_location'), data.get(prefix + '_time'))
                                if location is not None:
                                    address = self.address_resolver(location)
                                if reference is not None:
                                    data[prefix + '_location_reference'] = reference
                            except Exception:
                                pass
                        data[prefix + '_address'] = ' '.join(address.split())[:100] if isinstance(address, str) else None
                    data['addresses_resolved'] = True
                    if data.get('report_v2'):
                        message, omitted = render(kind, data['report_v2'], event_id,
                            {'start': data.get('start_address'), 'end': data.get('end_address')},
                            references={prefix: data.get(prefix + '_location_reference') for prefix in ('start', 'end')})
                        data['report_v2']['render'] = {'version': 'zh-text-v2', 'omitted': omitted,
                                                       'message_frozen': True, 'bytes': len(message.encode()),
                                                       'frozen_at': now,
                                                       'sha256': hashlib.sha256(message.encode()).hexdigest()}
                    else:
                        message = message_for(kind, data, event_id)
                    with self.tracks.connect() as db:
                        db.execute('UPDATE monitor_events SET summary=?,message=? WHERE id=?',
                                   (json.dumps(data, ensure_ascii=False), message, event_id))
                sender_called = True
                if hasattr(sender, 'send_markdown'):
                    sender.send_markdown(markdown_for(message))
                else:
                    sender(message)
                delivery, sent_at = 'sent', now
            except DeliveryError as exc:
                delivery = 'uncertain' if exc.ambiguous else 'failed' if exc.permanent or attempts >= 5 else 'pending'
                error = str(exc)[:100]
                next_attempt = now + min(3600, 60 * 2 ** attempts) * 1000
            except Exception:
                if sender_called:
                    delivery, error = 'uncertain', '发送结果未确认'
                else:
                    delivery, error = 'failed', '报告准备失败，未调用发送器'
            with self.tracks.connect() as db:
                db.execute('UPDATE monitor_events SET delivery=?,error=?,next_attempt=?,sent_at=? WHERE id=?',
                           (delivery, error, next_attempt, sent_at, event_id))
        if hasattr(sender, 'send_image'):
            self._deliver_images(sender, now)

    def _deliver_alerts(self, sender, now):
        with self.tracks.connect() as db:
            rows = db.execute('''SELECT a.event_id,a.attempts,e.kind,e.summary
                FROM monitor_event_alerts a JOIN monitor_events e ON e.id=a.event_id
                WHERE a.delivery='pending' AND a.next_attempt<=?
                ORDER BY e.created,e.rowid LIMIT 10''', (now,)).fetchall()
        for event_id, attempts, kind, encoded in rows:
            with self.tracks.connect() as db:
                claimed = db.execute("UPDATE monitor_event_alerts SET delivery='sending',attempts=attempts+1 WHERE event_id=? AND delivery='pending'", (event_id,)).rowcount
            if not claimed:
                continue
            delivery, error, next_attempt, sent_at = 'sent', None, 0, now
            try:
                title, body = bark_message_for(kind, json.loads(encoded))
                sender(title, body)
            except DeliveryError as exc:
                delivery = 'uncertain' if exc.ambiguous else 'failed' if exc.permanent or attempts >= 5 else 'pending'
                error = str(exc)[:100]
                next_attempt = now + min(3600, 60 * 2 ** attempts) * 1000
            except Exception:
                delivery, error = 'uncertain', 'Bark 发送结果未确认'
            with self.tracks.connect() as db:
                db.execute('UPDATE monitor_event_alerts SET delivery=?,error=?,next_attempt=?,sent_at=? WHERE event_id=?',
                           (delivery, error, next_attempt, sent_at if delivery == 'sent' else None, event_id))
                if kind in ('trip_start', 'charge_start'):
                    db.execute("UPDATE monitor_events SET delivery=?,error=?,next_attempt=?,sent_at=? WHERE id=? AND delivery='pending'",
                               (delivery, error, next_attempt, sent_at if delivery == 'sent' else None, event_id))

    def _deliver_images(self, sender, now):
        with self.tracks.connect() as db:
            rows = db.execute('''SELECT m.event_id,m.attempts,e.vehicle,e.summary
                FROM monitor_event_media m JOIN monitor_events e ON e.id=m.event_id
                WHERE m.delivery='pending' AND m.next_attempt<=? AND e.delivery='sent'
                ORDER BY e.created,e.rowid LIMIT 10''', (now,)).fetchall()
        for event_id, attempts, vehicle, encoded in rows:
            with self.tracks.connect() as db:
                claimed=db.execute("UPDATE monitor_event_media SET delivery='sending',attempts=attempts+1 WHERE event_id=? AND delivery='pending'",(event_id,)).rowcount
            if not claimed: continue
            delivery,error,next_attempt,sent_at='sent',None,0,now
            called=False
            try:
                data=json.loads(encoded); report=data.get('report_v2')
                if not report or report.get('schema_version') != 2:
                    raise ValueError('未知报告版本')
                start,end=report.get('start_time'),report.get('end_time')
                date=datetime.fromtimestamp(end/1000,ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
                route=self.tracks.between(vehicle,start,end,date)
                if self.map_renderer is None:
                    raise ValueError('未配置真实地图渲染器')
                if hasattr(self.map_renderer, 'render_trip'):
                    name=data.get('start_address') if not data.get('start_location_reference') else None
                    if not name and self.address_resolver and route.get('segments'):
                        try:
                            name=self.address_resolver(dict(route['segments'][0][0],valid=True))
                        except Exception:
                            pass
                    content=self.map_renderer.render_trip(report,route,name)
                else:
                    content=render_trip_png(report,route,self.map_renderer(route))
                called=True; sender.send_image(content)
            except DeliveryError as exc:
                delivery='uncertain' if exc.ambiguous else 'failed' if exc.permanent or attempts>=5 else 'pending'
                error=str(exc)[:100]; next_attempt=now+min(3600,60*2**attempts)*1000
            except Exception:
                delivery,error=('uncertain','图片发送结果未确认') if called else ('failed','行程图片准备失败，未调用发送器')
            with self.tracks.connect() as db:
                db.execute('UPDATE monitor_event_media SET delivery=?,error=?,next_attempt=?,sent_at=? WHERE event_id=?',
                           (delivery,error,next_attempt,sent_at if delivery=='sent' else None,event_id))
