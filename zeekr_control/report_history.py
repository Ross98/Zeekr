"""Bounded, deterministic same-vehicle comparisons for frozen v2 reports."""
import json
import math
from statistics import median
from .trip_visibility import visible_clause
from .usage_events import MAX_SUMMARY_BYTES

RULE_VERSION = 'history-v1'
WINDOW_MS = 90 * 86400 * 1000


def _finite(value):
    if type(value) not in (int,float):return False
    try:return math.isfinite(value)
    except OverflowError:return False


def _pace(duration, denominator):
    return duration/60/denominator if (_finite(duration) and duration>0
                                      and _finite(denominator) and denominator>0) else None


def _coverage(value):
    return _finite(value) and .8<=value<=1


def _timing(metrics):
    gaps=(metrics.get('stop_detection_state_gap_seconds'),metrics.get('stop_detection_observed_gap_seconds'))
    return _coverage(metrics.get('charging_time_coverage')) and all(_finite(gap) and 0<=gap<=180 for gap in gaps)


def _candidates(db, vehicle, kind, start_time, decoder, limit=500):
    rows = db.execute('''SELECT e.id,CASE WHEN length(CAST(e.summary AS BLOB))<=? THEN e.summary END FROM monitor_events e
                         JOIN report_metric_index i ON i.event_id=e.id
                         WHERE e.vehicle=? AND e.kind=? AND i.end_time<? AND '''+visible_clause(db,'e')+'''
                         GROUP BY e.id,e.summary ORDER BY i.end_time DESC,e.id DESC LIMIT ?''',
                      (MAX_SUMMARY_BYTES,vehicle, kind, start_time, limit)).fetchall()
    result, excluded = [], {}
    for event_id, encoded in rows:
        if not isinstance(encoded,str):
            excluded['invalid_payload']=excluded.get('invalid_payload',0)+1;continue
        try:
            decoded = json.loads(encoded)
        except (TypeError, ValueError, RecursionError):
            excluded['invalid_json'] = excluded.get('invalid_json', 0) + 1; continue
        report=(decoded.get('report_v2') or {}) if isinstance(decoded,dict) else None
        if (not isinstance(report,dict) or any(not isinstance(report.get(field,{}),dict)
                for field in ('quality','metrics','profile_snapshot','start','end'))):
            excluded['invalid_structure']=excluded.get('invalid_structure',0)+1;continue
        reason = None
        if report.get('schema_version') != 2: reason = 'not_v2'
        elif report.get('decoder_version') != decoder: reason = 'decoder'
        elif report.get('partial') is not False: reason = 'partial'
        elif not _finite(report.get('end_time')) or not start_time-WINDOW_MS <= report['end_time'] < start_time: reason = 'time'
        elif report.get('quality', {}).get('upgrade_mid_session') or report.get('quality', {}).get('decoder_changed_mid_session'): reason = 'upgrade'
        if reason: excluded[reason] = excluded.get(reason, 0) + 1
        else: result.append((event_id, report))
    return result, excluded, len(rows) == limit


def _freeze(metric, current, pairs, note):
    pairs = [(event_id, value) for event_id, value in pairs if _finite(value)][:20]
    if len(pairs) < 5 or not _finite(current): return None
    baseline = median(value for _, value in pairs)
    difference=current-baseline
    if not _finite(baseline) or not _finite(difference):return None
    return {'metric': metric, 'n': len(pairs), 'median': baseline, 'current': current,
            'difference': difference, 'event_ids': [event_id for event_id, _ in pairs], 'note': note}


def compare(db, vehicle, report):
    kind, start = report['kind'], report['start_time']
    quality=report.get('quality', {})
    if (report.get('partial') is not False or quality.get('upgrade_mid_session')
            or quality.get('decoder_changed_mid_session')):
        return {'version':RULE_VERSION,'cutoff':start,'candidate_count':0,'truncated':False,
                'excluded':{'current_ineligible':1},'items':[],'available':False}
    candidates, excluded, truncated = _candidates(db, vehicle, kind, start, report['decoder_version'])
    metrics, items = report.get('metrics', {}), []
    if kind == 'trip_end' and _finite(metrics.get('distance_km')) and metrics['distance_km'] >= 10:
        distance = metrics['distance_km']
        near = [(eid, r) for eid, r in candidates if _finite(r.get('metrics', {}).get('distance_km'))
                and distance*.8 <= r['metrics']['distance_km'] <= distance*1.2]
        pace = _freeze('minutes_per_km', _pace(metrics.get('duration_seconds'),distance),
            [(eid, _pace(r['metrics'].get('duration_seconds'),r['metrics']['distance_km'])) for eid,r in near], '相近里程')
        if pace: items.append(pace)
        current_consumption, current_speed = metrics.get('estimated_kwh_100km'), metrics.get('average_speed_kmh')
        current_temp, energy = metrics.get('outside_temp_average'), []
        profile = report.get('profile_snapshot', {})
        if _finite(current_speed) and current_speed>0 and _finite(current_temp):
            for eid, r in near:
                hm = r.get('metrics', {})
                hp = r.get('profile_snapshot', {})
                if (_finite(hm.get('estimated_kwh_100km')) and _finite(hm.get('average_speed_kmh'))
                        and _finite(hm.get('outside_temp_average'))
                        and hp.get('battery_capacity_kwh') == profile.get('battery_capacity_kwh')
                        and current_speed*.75 <= hm['average_speed_kmh'] <= current_speed*1.25
                        and abs(hm['outside_temp_average']-current_temp) <= 5): energy.append((eid, hm['estimated_kwh_100km']))
        item = _freeze('estimated_kwh_100km', current_consumption, energy, '里程、平均速度及车外温度接近')
        if item: items.append(item)
    elif kind == 'charge_end':
        delta = metrics.get('soc_delta')
        start_soc, end_soc = report.get('start',{}).get('soc'), report.get('end',{}).get('soc')
        if _finite(delta) and delta >= 10 and _finite(start_soc) and _finite(end_soc):
            near = [(eid,r) for eid,r in candidates if _finite(r.get('start',{}).get('soc'))
                    and _finite(r.get('end',{}).get('soc'))
                    and abs(r['start']['soc']-start_soc) <= 3 and abs(r['end']['soc']-end_soc) <= 3
                    and r.get('start',{}).get('charging_mode') == report.get('start',{}).get('charging_mode')
                    and _finite(r.get('metrics',{}).get('soc_delta')) and r['metrics']['soc_delta'] >= 10]
            pace = _freeze('minutes_per_soc_point', _pace(metrics.get('duration_seconds'),delta) if _timing(metrics) else None,
                [(eid, _pace(r['metrics'].get('duration_seconds'),r['metrics']['soc_delta'])) for eid,r in near
                 if _timing(r['metrics'])], '相近电量区间')
            if pace: items.append(pace)
            power = _freeze('average_power_kw', metrics.get('average_power_kw'),
                [(eid,r.get('metrics',{}).get('average_power_kw')) for eid,r in near if _coverage(r.get('metrics',{}).get('power_coverage'))], '相近电量区间')
            if power: items.append(power)
    return {'version': RULE_VERSION, 'cutoff': start, 'candidate_count': len(candidates), 'truncated': truncated,
            'excluded': excluded, 'items': items[:2], 'available': bool(items)}


def select(db, vehicle, kind, start_time, metric, compatible='we86-v1', limit=500):
    candidates, _, _ = _candidates(db, vehicle, kind, start_time, compatible, limit)
    pairs = [(eid, r.get('metrics', {}).get(metric)) for eid, r in candidates]
    item = _freeze(metric, 0, pairs, '')
    return {'available': item is not None, 'n': len(item['event_ids']) if item else 0,
            'median': item['median'] if item else None, 'event_ids': item['event_ids'] if item else []}
