"""Bounded, deterministic same-vehicle comparisons for frozen v2 reports."""
import json
from statistics import median
from .trip_visibility import visible_clause

RULE_VERSION = 'history-v1'
WINDOW_MS = 90 * 86400 * 1000


def _candidates(db, vehicle, kind, start_time, decoder, limit=500):
    rows = db.execute('''SELECT e.id,e.summary FROM monitor_events e
                         JOIN report_metric_index i ON i.event_id=e.id
                         WHERE e.vehicle=? AND e.kind=? AND i.end_time<? AND '''+visible_clause(db,'e')+'''
                         GROUP BY e.id,e.summary ORDER BY i.end_time DESC,e.id DESC LIMIT ?''',
                      (vehicle, kind, start_time, limit)).fetchall()
    result, excluded = [], {}
    for event_id, encoded in rows:
        try:
            report = json.loads(encoded).get('report_v2') or {}
        except (TypeError, ValueError):
            excluded['invalid_json'] = excluded.get('invalid_json', 0) + 1; continue
        reason = None
        if report.get('schema_version') != 2: reason = 'not_v2'
        elif report.get('decoder_version') != decoder: reason = 'decoder'
        elif report.get('partial') is not False: reason = 'partial'
        elif type(report.get('end_time')) not in (int, float) or not start_time-WINDOW_MS <= report['end_time'] < start_time: reason = 'time'
        elif report.get('quality', {}).get('upgrade_mid_session') or report.get('quality', {}).get('decoder_changed_mid_session'): reason = 'upgrade'
        if reason: excluded[reason] = excluded.get(reason, 0) + 1
        else: result.append((event_id, report))
    return result, excluded, len(rows) == limit


def _freeze(metric, current, pairs, note):
    pairs = [(event_id, value) for event_id, value in pairs if type(value) in (int, float)][:20]
    if len(pairs) < 5 or type(current) not in (int, float): return None
    baseline = median(value for _, value in pairs)
    return {'metric': metric, 'n': len(pairs), 'median': baseline, 'current': current,
            'difference': current-baseline, 'event_ids': [event_id for event_id, _ in pairs], 'note': note}


def compare(db, vehicle, report):
    kind, start = report['kind'], report['start_time']
    candidates, excluded, truncated = _candidates(db, vehicle, kind, start, report['decoder_version'])
    metrics, items = report.get('metrics', {}), []
    if report.get('partial') is not False or report.get('quality', {}).get('upgrade_mid_session'):
        return {'version':RULE_VERSION,'cutoff':start,'candidate_count':0,'truncated':False,
                'excluded':{'current_ineligible':1},'items':[],'available':False}
    if kind == 'trip_end' and type(metrics.get('distance_km')) in (int, float) and metrics['distance_km'] >= 10:
        distance = metrics['distance_km']
        near = [(eid, r) for eid, r in candidates if type(r.get('metrics', {}).get('distance_km')) in (int,float)
                and distance*.8 <= r['metrics']['distance_km'] <= distance*1.2]
        pace = _freeze('minutes_per_km', metrics.get('duration_seconds')/60/distance,
            [(eid, r['metrics'].get('duration_seconds')/60/r['metrics']['distance_km']) for eid,r in near
             if r['metrics'].get('duration_seconds') is not None and r['metrics']['distance_km'] > 0], '相近里程')
        if pace: items.append(pace)
        current_consumption, current_speed = metrics.get('estimated_kwh_100km'), metrics.get('average_speed_kmh')
        current_temp, energy = metrics.get('outside_temp_average'), []
        profile = report.get('profile_snapshot', {})
        if current_speed and current_temp is not None:
            for eid, r in near:
                hm = r.get('metrics', {})
                hp = r.get('profile_snapshot', {})
                if (type(hm.get('estimated_kwh_100km')) in (int,float) and type(hm.get('average_speed_kmh')) in (int,float)
                        and type(hm.get('outside_temp_average')) in (int,float)
                        and hp.get('battery_capacity_kwh') == profile.get('battery_capacity_kwh')
                        and current_speed*.75 <= hm['average_speed_kmh'] <= current_speed*1.25
                        and abs(hm['outside_temp_average']-current_temp) <= 5): energy.append((eid, hm['estimated_kwh_100km']))
        item = _freeze('estimated_kwh_100km', current_consumption, energy, '里程、平均速度及车外温度接近')
        if item: items.append(item)
    elif kind == 'charge_end':
        delta = metrics.get('soc_delta')
        start_soc, end_soc = report.get('start',{}).get('soc'), report.get('end',{}).get('soc')
        if type(delta) in (int,float) and delta >= 10 and None not in (start_soc, end_soc):
            near = [(eid,r) for eid,r in candidates if type(r.get('start',{}).get('soc')) in (int,float)
                    and type(r.get('end',{}).get('soc')) in (int,float)
                    and abs(r['start']['soc']-start_soc) <= 3 and abs(r['end']['soc']-end_soc) <= 3
                    and r.get('start',{}).get('charging_mode') == report.get('start',{}).get('charging_mode')
                    and (r.get('metrics',{}).get('soc_delta') or 0) >= 10]
            current_timing_ok = (metrics.get('charging_time_coverage',0) >= .8
                and metrics.get('stop_detection_state_gap_seconds',999) <= 180
                and metrics.get('stop_detection_observed_gap_seconds',999) <= 180)
            pace = _freeze('minutes_per_soc_point', metrics.get('duration_seconds')/60/delta if current_timing_ok else None,
                [(eid, r['metrics']['duration_seconds']/60/r['metrics']['soc_delta']) for eid,r in near
                 if r.get('metrics',{}).get('charging_time_coverage',0) >= .8
                 and r.get('metrics',{}).get('stop_detection_state_gap_seconds',999) <= 180
                 and r.get('metrics',{}).get('stop_detection_observed_gap_seconds',999) <= 180
                 and r['metrics'].get('duration_seconds') and r['metrics'].get('soc_delta')], '相近电量区间')
            if pace: items.append(pace)
            power = _freeze('average_power_kw', metrics.get('average_power_kw'),
                [(eid,r.get('metrics',{}).get('average_power_kw')) for eid,r in near if r.get('metrics',{}).get('power_coverage',0) >= .8], '相近电量区间')
            if power: items.append(power)
    return {'version': RULE_VERSION, 'cutoff': start, 'candidate_count': len(candidates), 'truncated': truncated,
            'excluded': excluded, 'items': items[:2], 'available': bool(items)}


def select(db, vehicle, kind, start_time, metric, compatible='we86-v1', limit=500):
    candidates, _, _ = _candidates(db, vehicle, kind, start_time, compatible, limit)
    pairs = [(eid, r.get('metrics', {}).get(metric)) for eid, r in candidates]
    item = _freeze(metric, 0, pairs, '')
    return {'available': item is not None, 'n': len(item['event_ids']) if item else 0,
            'median': item['median'] if item else None, 'event_ids': item['event_ids'] if item else []}
