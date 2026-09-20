"""Bounded, allowlisted research over local observations, never a vehicle poll."""
from bisect import bisect_left, bisect_right
from collections import Counter
import hashlib
import json
import math
import time

from .archive_reader import STALE_MS, _context
from .parameter_dictionary import FIELDS
from .summary import number
from .tracks import day_bounds
from .usage_events import UsageEvents
from .vehicle_parameters import GROUPS, MISSING, group_for, lookup, parameters
from .vehicle_state import decode

PUBLIC = {path: entry for path, entry in FIELDS.items() if not entry['private']}
STATUSES = ('known', 'pending', 'empty', 'invalid', 'missing')
SCENARIOS = ('driving', 'charging', 'parked', 'unknown')
PREFIX = 'additionalVehicleStatus.'
OUTSIDE = PREFIX + 'climateStatus.exteriorTemp'
INSIDE = PREFIX + 'climateStatus.interiorTemp'
SCENES = (
    ('cabin', '座舱与环境', ('空调与座舱', '空气质量')),
    ('tyres', '四轮观测', ('轮胎与保养',)),
    ('low-voltage', '低压电池', ('低压电池',)),
    ('closures', '门窗、灯光与座椅', ('门窗与安全', '灯光', '座椅与方向盘')),
    ('journeys', '行程与充电条件', ('基础车况与行驶', '能源与充放电')),
)
CLIMATE_CODES = tuple(PREFIX+'climateStatus.'+name for name in
                      ('cdsClimateActive', 'preClimateActive', 'airBlowerActive', 'defrost'))


class ResearchInputError(ValueError):
    """Fixed public messages, with no archive paths or owner data."""


def temperature_band(value):
    return '温度缺样' if value is None else '车外低于 10°C' if value < 10 else '车外 10–25°C' if value <= 25 else '车外高于 25°C'


def numeric():
    return dict(count=0, min=None, max=None, mean=None, _sum=0.0)


def add_number(stats, value):
    if value is None:
        return
    stats['count'] += 1
    stats['_sum'] += value
    stats['min'] = value if stats['min'] is None else min(stats['min'], value)
    stats['max'] = value if stats['max'] is None else max(stats['max'], value)


def finish_number(stats):
    return dict(count=stats['count'], min=stats['min'], max=stats['max'],
                mean=round(stats['_sum']/stats['count'], 6) if stats['count'] else None)


def sample_points(points, limit=600):
    """Discrete points only; retain each bucket's endpoints and numeric extrema."""
    if len(points) <= limit:
        return points
    result = []
    buckets = limit // 4
    for i in range(buckets):
        lo, hi = i*len(points)//buckets, (i+1)*len(points)//buckets
        indices = {lo, hi-1}
        values = [j for j in range(lo, hi) if points[j].get('number') is not None]
        if values:
            indices.update((min(values, key=lambda j: points[j]['number']),
                            max(values, key=lambda j: points[j]['number'])))
        result.extend(points[j] for j in sorted(indices))
    return result


def scenario(raw):
    state = decode(raw)
    if state['charging'] is True:
        return 'charging'
    if state['speed'] is not None and state['speed'] > 0:
        return 'driving'
    if state['off'] is True and state['speed'] == 0 and state['charging'] is False:
        return 'parked'
    return 'unknown'


def value_key(value):
    # Full identities distinguish truncated text, boolean/number and numeric strings.
    if type(value) in (int, float, bool, type(None)) or isinstance(value, str) and len(value) <= 120:
        return type(value).__name__, value
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return type(value).__name__, hashlib.sha256(encoded.encode()).digest()


def unknown_paths(raw):
    result = set()
    def walk(value, path='', depth=0):
        if depth > 20 or len(result) >= 10000:
            return
        if path in FIELDS:
            return  # Private containers and identities remain private.
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, path+'.'+key if path else key, depth+1)
        elif path:
            result.add(hashlib.sha256(path.encode()).digest())
    walk(raw)
    return result


def new_field(path, entry):
    return dict(path=path, name=entry['name'], group=group_for(path), kind=entry['kind'],
                unit=entry['unit'], applicability=entry['applicability'], note=entry['note'],
                read_counts=dict.fromkeys(STATUSES, 0), first_returned=None, last_returned=None,
                samples=0, known_samples=0, pending_samples=0, time_excluded=0, changes=0,
                numeric=numeric(), scenarios={name: dict(samples=0, numeric=numeric()) for name in SCENARIOS},
                cadence_seconds=numeric(), rate_per_minute=numeric(), delay_seconds=numeric(),
                _values={}, _other=0, _last=None, _last_stamp=None, _previous=None,
                _distinct=set(), _distinct_overflow=False)


def usable_number(field, raw_value):
    if field['status'] not in ('known', 'pending') or type(raw_value) is bool:
        return None
    value = number(raw_value) if PUBLIC[field['path']]['kind'] == 'number' else None
    return float(value) if value is not None and math.isfinite(value) and abs(value) <= 1e12 else None


class VehicleResearch:
    def __init__(self, archive, database=None, clock=None):
        self.archive = archive
        self.events = UsageEvents(database) if database is not None else None
        self.clock = clock or (lambda: int(time.time()*1000))

    def query(self, scope, vehicle, start, end, path='', current=None):
        _context(scope, vehicle)
        if path and path not in PUBLIC:
            raise ResearchInputError('请选择公开参数目录中的字段。')
        lower, _ = day_bounds(start)
        _, requested_upper = day_bounds(end)
        if not 0 < requested_upper-lower <= 31*86400000:
            raise ResearchInputError('请选择 1–31 天的研究范围。')
        now = self.clock()
        upper = min(requested_upper, now+1)
        rows = {p: new_field(p, entry) for p, entry in PUBLIC.items()}
        quality = dict.fromkeys(('new', 'repeat', 'revision', 'invalid'), 0)
        read_count = samples = 0
        unmapped, points, transitions, conditions = set(), [], [], []
        last_raw = last_projection = candidate = None
        high = None
        wheel_spread, cabin_delta = numeric(), numeric()
        climate_conditions = {}
        climate_other = 0
        last_point = last_point_signature = None

        def consume(record, raw, projection):
            nonlocal samples, last_point, last_point_signature, climate_other
            samples += 1
            mode = scenario(raw)
            values = {}
            codes = {}
            for field in projection['fields']:
                p = field['path']
                row = rows[p]
                if p.startswith('vehicleMetadata.'):
                    continue
                stamp, status = field['updated_time'], field['status']
                timed = (type(stamp) in (int, float) and stamp > 0 and
                         -60000 <= record['fetched_at']-stamp <= STALE_MS and
                         -60000 <= record['observed_at']-stamp <= STALE_MS)
                repeated_time = timed and row['_last_stamp'] is not None and stamp <= row['_last_stamp']
                valid = status in ('known', 'pending') and timed and not repeated_time
                value = lookup(raw, p)
                n = usable_number(field, value) if valid else None
                if valid:
                    previous = row['_previous']
                    if previous:
                        seconds = (stamp-previous['time'])/1000
                        if 0 < seconds <= 600 and record['observed_at']-previous['observed_at'] <= STALE_MS:
                            add_number(row['cadence_seconds'], seconds)
                            if n is not None and previous['number'] is not None and previous['index'] == samples-1:
                                add_number(row['rate_per_minute'], (n-previous['number'])/(seconds/60))
                    add_number(row['delay_seconds'], (record['fetched_at']-stamp)/1000)
                    row['_previous'] = dict(time=stamp, observed_at=record['observed_at'],number=n,index=samples)
                    row['samples'] += 1
                    row[status+'_samples'] += 1
                    row['_last_stamp'] = stamp
                    row['scenarios'][mode]['samples'] += 1
                    add_number(row['numeric'], n)
                    add_number(row['scenarios'][mode]['numeric'], n)
                    key = value_key(value)
                    if len(row['_distinct']) < 256:
                        row['_distinct'].add(key)
                    elif key not in row['_distinct']:
                        row['_distinct_overflow'] = True
                    if key in row['_values']:
                        row['_values'][key]['count'] += 1
                    elif len(row['_values']) < 20:
                        row['_values'][key] = dict(raw=field['raw'], value=field['value'],
                                                  status=status, count=1)
                    else:
                        row['_other'] += 1
                    if row['_last'] is not None and row['_last'] != key:
                        row['changes'] += 1
                    row['_last'] = key
                    if status == 'known' and n is not None:
                        values[p] = n
                    if p in CLIMATE_CODES:
                        codes[p] = (key, field['raw'])
                elif status in ('known', 'pending'):
                    row['time_excluded'] += 1
                if p == path:
                    signature = ('missing',) if value is MISSING else value_key(value)
                    point = dict(key=record['key'], time=stamp, observed_at=record['observed_at'],
                                 state_time=record['state_time'], number=n, raw=field['raw'],
                                 value=field['value'], status=status, usable=valid, scenario=mode,
                                 time_source=field['time_source'], gap_before=False,
                                 delay_seconds=(record['fetched_at']-stamp)/1000 if timed else None)
                    if last_point:
                        point['gap_before'] = (not valid or not last_point['usable'] or
                            record['observed_at']-last_point['observed_at'] > STALE_MS or
                            stamp is None or last_point['time'] is None or
                            not 0 < stamp-last_point['time'] <= STALE_MS)
                        if (signature, status) != (last_point_signature, last_point['status']):
                            if len(transitions) < 100:
                                transitions.append(dict(before=last_point['key'], after=point['key'],
                                    from_time=last_point['time'], to_time=stamp, before_raw=last_point['raw'],
                                    after_raw=field['raw'], gap=point['gap_before'],
                                    display_limited=field['raw']==last_point['raw']))
                    points.append(point)
                    last_point = point
                    last_point_signature = signature
            tyres = [values.get(PREFIX+'maintenanceStatus.tyreStatus'+side)
                     for side in ('Driver', 'Passenger', 'DriverRear', 'PassengerRear')]
            if all(v is not None for v in tyres):
                add_number(wheel_spread, max(tyres)-min(tyres))
            if INSIDE in values and OUTSIDE in values:
                add_number(cabin_delta, values[INSIDE]-values[OUTSIDE])
                for code_path, (code_key, display) in codes.items():
                    band = temperature_band(values[OUTSIDE])
                    identity = (code_path, code_key, band, mode)
                    if identity not in climate_conditions and len(climate_conditions) >= 100:
                        climate_other += 1
                        continue
                    condition = climate_conditions.setdefault(identity, dict(path=code_path,
                        name=PUBLIC[code_path]['name'], raw=display, outside_band=band, scenario=mode,
                        inside=numeric(), outside=numeric(), delta=numeric()))
                    add_number(condition['inside'], values[INSIDE])
                    add_number(condition['outside'], values[OUTSIDE])
                    add_number(condition['delta'], values[INSIDE]-values[OUTSIDE])
            conditions.append(dict(time=record['state_time'], outside=values.get(OUTSIDE),
                                   scenario=mode))

        if upper > lower:
            for record, raw in self.archive.iter_records(scope, vehicle, lower, upper):
                read_count += 1
                if raw is not last_raw:
                    last_projection = self.archive._project(record, raw)
                    last_raw = raw
                    if len(unmapped) < 10000:
                        unmapped.update(unknown_paths(raw))
                        if len(unmapped) > 10000:
                            unmapped = set(list(unmapped)[:10000])
                projection = last_projection
                for field in projection['fields']:
                    row = rows[field['path']]
                    row['read_counts'][field['status']] += 1
                    if field['status'] != 'missing':
                        if row['first_returned'] is None:
                            row['first_returned'] = record['observed_at']
                        row['last_returned'] = record['observed_at']
                stamp = record['state_time']
                if record['flags'] or stamp is None or record['change'] == 'regression' or (high is not None and stamp < high):
                    quality['invalid'] += 1
                    continue
                if stamp == high:
                    if record['change'] in ('repeat', 'revision'):
                        quality[record['change']] += 1
                        if candidate is not None and record['change'] == 'revision':
                            candidate = (record, raw, projection)
                    else:
                        quality['invalid'] += 1
                    continue
                if record['change'] in ('repeat', 'revision'):
                    # Its original is outside the selected range; don't invent a new sample.
                    quality[record['change']] += 1
                    high = stamp
                    continue
                if candidate is not None:
                    consume(*candidate)
                quality['new'] += 1
                high = stamp
                candidate = (record, raw, projection)
        if candidate is not None:
            consume(*candidate)

        current_fields = {f['path']: f for f in (current or {}).get('fields', [])}
        for p, row in rows.items():
            for key in ('numeric', 'cadence_seconds', 'rate_per_minute', 'delay_seconds'):
                row[key] = finish_number(row[key])
            row['scenarios'] = {key: dict(samples=v['samples'], numeric=finish_number(v['numeric']))
                                for key, v in row['scenarios'].items()}
            row['distribution'] = sorted(row.pop('_values').values(), key=lambda v: -v['count'])
            row['distribution_other'] = row.pop('_other')
            row['distinct'] = len(row.pop('_distinct'))
            row['distinct_is_lower_bound'] = row.pop('_distinct_overflow')
            row['current'] = current_fields.get(p) if p.startswith('vehicleMetadata.') else None
            row['uses'] = ['返回率与数据质量']
            if p.startswith('vehicleMetadata.'):
                row['disposition'] = 'configuration'
                row['reason'] = '当前档案用于配置背景；历史归档未包含档案，不推断配置已装配。'
                row['uses'].append('配置与适用性背景')
            elif row['samples']:
                row['disposition'] = 'analyzed'
                row['uses'].extend(['原值分布与变化', '场景分组'])
                if row['numeric']['count']:
                    row['uses'].append('数值范围与历史')
                if row['kind'] == 'timestamp':
                    row['uses'].append('更新时间与新旧程度')
                row['reason'] = ('含义或单位待核实；仅描述原值变化。' if row['pending_samples']
                                 else '按有效观测统计；不表示连续覆盖。')
            else:
                row['disposition'] = 'insufficient'
                row['reason'] = ('所选范围未返回该字段。' if row['first_returned'] is None else
                                 '已返回，但值或来源时间不足以形成有效分析样本。')
            row.pop('_last'); row.pop('_last_stamp'); row.pop('_previous')

        fields = list(rows.values())
        scenes = []
        for identity, name, groups in SCENES:
            included = [r for r in fields if r['group'] in groups and
                        (identity != 'tyres' or 'tyre' in r['path'])]
            scenes.append(dict(id=identity, name=name, paths=[r['path'] for r in included],
                               available_fields=sum(r['samples'] > 0 for r in included),
                               total_fields=len(included)))
        scenes[0]['paired_delta'] = finish_number(cabin_delta)
        scenes[0]['conditions'] = [dict(row, **{key:finish_number(row[key]) for key in ('inside','outside','delta')})
                                   for row in climate_conditions.values()]
        scenes[0]['conditions_other'] = climate_other
        scenes[1]['wheel_spread'] = finish_number(wheel_spread)
        detail = None
        if path:
            numbers = [p['number'] for p in points if p['number'] is not None]
            histogram = []
            if numbers:
                lo, hi = min(numbers), max(numbers)
                if hi == lo:
                    histogram = [dict(min=lo, max=hi, count=len(numbers))]
                else:
                    width = (hi-lo)/10
                    bins = Counter(min(9, int((n-lo)/width)) for n in numbers)
                    histogram = [dict(min=lo+i*width, max=lo+(i+1)*width, count=bins[i]) for i in range(10)]
            detail = dict(field=rows[path], points=sample_points(points), point_count=len(points),
                          transitions=transitions, histogram=histogram)
        events = self.event_conditions(vehicle, lower, upper, conditions) if upper > lower else dict(events=[], groups=[], total=0)
        return dict(start_date=start, end_date=end, as_of=now, quality=quality,
                    counts=dict(catalog=len(fields), reads=read_count, samples=samples,
                                returned_fields=sum(r['first_returned'] is not None for r in fields),
                                analyzed_fields=sum(r['samples'] > 0 for r in fields),
                                unmapped_paths=len(unmapped), unmapped_is_lower_bound=len(unmapped)>=10000),
                    fields=fields, groups=list(GROUPS),
                    scenes=scenes, detail=detail, event_conditions=events,
                    limits=dict(points=600, transitions=100, distribution=20, days=31))

    def event_conditions(self, vehicle, lower, upper, observations):
        result = self.events.between(vehicle, lower, upper) if self.events else {'events': []}
        stamps = [r['time'] for r in observations]
        rows, groups = [], {}
        for event in result['events']:
            start, end = event['start_time'], event['end_time']
            observed = observations[bisect_left(stamps, start):bisect_right(stamps, end)] if start is not None else []
            temperatures = [r['outside'] for r in observed if r['outside'] is not None]
            outside = sum(temperatures)/len(temperatures) if temperatures else None
            row = dict(event, observed_samples=len(observed), temperature_samples=len(temperatures),
                       outside_mean=round(outside, 3) if outside is not None else None,
                       range_partial=start is None or start < lower)
            rows.append(row)
            usable = event['estimated_kwh'] is not None
            consumption = None
            if usable and event['kind'] == 'trip_end' and (event['distance_km'] or 0) >= 10 and (event['soc_delta'] or 0) <= -3:
                consumption = event['estimated_kwh']/event['distance_km']*100
            temp_group = temperature_band(outside)
            soc = event['start_soc']
            soc_group = '起始电量未知' if soc is None else '起始电量低于 30%' if soc < 30 else '起始电量 30–70%' if soc <= 70 else '起始电量高于 70%'
            for dimension, label in [('temperature', temp_group), ('soc', soc_group), ('mode', event['charge_mode'] or '方式未知')]:
                key = (event['kind'], dimension, label)
                group = groups.setdefault(key, dict(kind=event['kind'], dimension=dimension, label=label,
                    events=0, usable_events=0, consumption=numeric(), energy=numeric()))
                group['events'] += 1
                group['usable_events'] += int(usable)
                add_number(group['consumption'], consumption)
                add_number(group['energy'], event['estimated_kwh'] if usable else None)
        for group in groups.values():
            group['consumption'] = finish_number(group['consumption'])
            group['energy'] = finish_number(group['energy'])
        return dict(total=len(rows), events=rows[:100], groups=list(groups.values()),
                    unreadable_or_undated=result.get('unreadable_or_undated', 0))
