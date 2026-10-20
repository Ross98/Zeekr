"""Read-only battery-side consumption between consecutive saved charges."""
import json
from bisect import bisect_right

from .analysis_cancel import check_cancelled
from .trip_visibility import visible_clause
from .usage_events import UsageEvents, MAX_SUMMARY_BYTES, MAX_SCAN, MAX_EVENTS, number, project, total
from .usage_reports import DAY, date_label

MIN_DISTANCE_KM = 10
MIN_SOC_DROP = 3


def _object(value):
    return value if isinstance(value, dict) else {}


def _boundary(event, side):
    point = _object(event['report'].get(side))
    stamp = event['start_time'] if side == 'start' else event['end_time']
    state = number(point.get('state_time'), 1, 32503680000000)
    observed = number(point.get('observed_at'), 1, 32503680000000)
    soc = number(point.get('soc'), 0, 100)
    expected_soc = event['start_soc'] if side == 'start' else event['end_soc']
    odometer = number(point.get('odometer'), 0, 10000000)
    if (stamp is None or state != stamp or observed is None or not -30000 <= observed-state <= 180000
            or soc is None or soc != expected_soc or odometer is None
            or point.get('charging') is not (side == 'start')):
        return None
    return dict(soc=soc, odometer=odometer, decoder=point.get('decoder_version'))


class ChargingIntervals:
    def __init__(self, database):
        self.events = UsageEvents(database)

    def _charges(self, vehicle, lower, upper):
        events, invalid, scanned, starts = [], 0, 0, []
        with self.events.connect() as db:
            if db is None:
                return events, invalid, starts
            # Include hidden charges as barriers: deletion must never bridge an actual recharge.
            cursor = db.execute('SELECT id,kind,CASE WHEN length(CAST(summary AS BLOB))<=? THEN summary END,'
                                'length(CAST(summary AS BLOB)),('+visible_clause(db)+') '
                                "FROM monitor_events WHERE vehicle=? AND kind IN ('charge_end','charge_start') ORDER BY created,id",
                                (MAX_SUMMARY_BYTES, vehicle))
            while True:
                check_cancelled()
                batch = cursor.fetchmany(8)
                if not batch:break
                for identity, kind, encoded, size, visible in batch:
                    scanned += 1
                    if scanned > MAX_SCAN:raise ValueError('充电历史过大，需先建立归期索引。')
                    try:raw = json.loads(encoded) if isinstance(encoded,str) and size <= MAX_SUMMARY_BYTES else None
                    except (ValueError,TypeError,RecursionError):raw = None
                    if kind == 'charge_start':
                        stamp=number(raw.get('start_time'),1,32503680000000) if isinstance(raw,dict) else None
                        if stamp is None:invalid += 1
                        elif lower<=stamp<upper:
                            starts.append(stamp)
                            if len(starts)+len(events)>MAX_EVENTS:raise ValueError('区间内充电记录过多。')
                        continue
                    event = project(identity, 'charge_end', raw)
                    if event is None:
                        invalid += 1
                        continue
                    if lower <= event['end_time'] < upper:
                        report=_object(raw.get('report_v2'));quality=_object(report.get('quality'))
                        clean={'quality':{k:quality.get(k) is True for k in ('decoder_changed_mid_session','upgrade_mid_session')}}
                        for side in ('start','end'):
                            point=_object(report.get(side));version=point.get('decoder_version')
                            clean[side]={k:point.get(k) if type(point.get(k)) in (int,float,bool) else None
                                         for k in ('state_time','observed_at','soc','odometer','charging')}
                            clean[side]['decoder_version']=version if isinstance(version,str) and len(version)<=128 else None
                        event.update(report=clean, visible=bool(visible))
                        events.append(event)
                        if len(events)+len(starts)>MAX_EVENTS:raise ValueError('区间内充电记录过多。')
        events.sort(key=lambda e:(e['end_time'],e['id']))
        return events, invalid, sorted(starts)

    @staticmethod
    def _interval(previous, current, books, invalid, starts):
        row = dict(id=current['id'], previous_id=previous['id'] if previous and previous['visible'] else None,
                   start_time=previous['end_time'] if previous and previous['visible'] else None, end_time=current['start_time'],
                   closed_time=current['end_time'], cross_month=False, start_soc=None, end_soc=None,
                   soc_drop=None, distance_km=None, estimated_kwh=None, kwh_per_100km=None,
                   reference_cents_per_kwh=None, estimated_cents=None, reason=None)
        def reject(reason):
            row['reason']=reason
            return row
        if previous is None:return reject('missing_previous')
        if not previous['visible']:return reject('hidden_charge')
        if invalid:return reject('undated_charge')
        if current['start_time'] is None or previous['end_time']>=current['start_time']:return reject('overlap')
        next_start=bisect_right(starts,previous['end_time'])
        if next_start<len(starts) and starts[next_start]<current['start_time']:return reject('unclosed_charge')
        row['cross_month']=date_label(previous['end_time'])[:7]!=date_label(current['start_time'])[:7]
        # A partial closing charge may already have added energy before its first observation.
        if current['partial']:return reject('late_start')
        quality = [_object(e['report'].get('quality')) for e in (previous,current)]
        if any(q.get('decoder_changed_mid_session') or q.get('upgrade_mid_session') for q in quality):
            return reject('decoder_changed')
        left,right=_boundary(previous,'end'),_boundary(current,'start')
        if left is None or right is None:return reject('missing_endpoint')
        if left['decoder'] and right['decoder'] and left['decoder']!=right['decoder']:return reject('decoder_changed')
        cap,other=previous['battery_capacity_kwh'],current['battery_capacity_kwh']
        if cap is None or other is None:return reject('missing_capacity')
        if abs(cap-other)>.000001:return reject('capacity_changed')
        distance=right['odometer']-left['odometer'];drop=left['soc']-right['soc']
        row.update(start_soc=left['soc'],end_soc=right['soc'],soc_drop=drop,distance_km=round(distance,6))
        if distance<0:return reject('odometer_reset')
        if distance==0:return reject('no_distance')
        if distance/((current['start_time']-previous['end_time'])/3600000)>400:return reject('odometer_jump')
        if drop<0:return reject('soc_increase')
        if drop<MIN_SOC_DROP:return reject('soc_resolution')
        if distance<MIN_DISTANCE_KM:return reject('short_distance')
        energy=cap*drop/100
        row.update(estimated_kwh=round(energy,6), kwh_per_100km=energy/distance*100)
        book=books.get(previous['id'],{})
        fee=number(book.get('actual_cents'),0,100000000);meter=number(book.get('metered_kwh'),.000001,10000)
        if fee is not None and meter is not None:
            price=fee/meter
            row.update(reference_cents_per_kwh=price,estimated_cents=energy*price)
        return row

    def query(self, vehicle, window, now, books):
        upper=max(window['start'],min(window['end'],now+1))
        charges,invalid,starts=self._charges(vehicle,max(0,window['start']-180*DAY),min(upper,now+1))
        rows=[];previous=None
        for charge in charges:
            check_cancelled()
            if charge['visible'] and window['start']<=charge['end_time']<upper:
                rows.append(self._interval(previous,charge,books,invalid,starts))
            previous=charge
        valid=[r for r in rows if r['reason'] is None]
        priced=[r for r in valid if r['estimated_cents'] is not None]
        distance=total(r['distance_km'] for r in valid);energy=total(r['estimated_kwh'] for r in valid)
        priced_distance=total(r['distance_km'] for r in priced);cents=total(r['estimated_cents'] for r in priced)
        current_month=window['start']<=now<window['end']
        open_interval=(dict(start_time=previous['end_time'],status='waiting')
                       if current_month and previous and previous['visible'] else None)
        return dict(records=list(reversed(rows)),open_interval=open_interval,
                    rules=dict(min_distance_km=MIN_DISTANCE_KM,min_soc_drop=MIN_SOC_DROP,history_days=180),
                    quality=dict(undated_charge_count=invalid),
                    summary=dict(interval_count=len(rows),valid_count=len(valid),excluded_count=len(rows)-len(valid),
                                 distance_km=distance,estimated_kwh=energy,
                                 kwh_per_100km=energy/distance*100 if distance and energy is not None else None,
                                 priced_count=len(priced),priced_distance_km=priced_distance,estimated_cents=cents,
                                 cents_per_100km=cents/priced_distance*100 if priced_distance and cents is not None else None))
