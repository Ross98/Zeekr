"""User-entered charging bills; precise money and separately labelled estimates."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import uuid

from .tracks import day_bounds
from .usage_events import UsageEvents
from .usage_reports import period_window, date_label, total


def decimal_input(value,places,maximum):
    if value is None or value=='':return None
    if type(value) not in (str,int,float) or isinstance(value,str) and len(value)>40:
        raise ValueError('金额、电量或电价格式无效。')
    try:
        number=Decimal(str(value))
        if not number.is_finite() or not 0<=number<=maximum or number!=number.quantize(Decimal(10)**-places):
            raise ValueError
    except (InvalidOperation,ValueError):
        raise ValueError('金额最多两位小数，电量三位，电价四位；数值须为有效非负数。') from None
    return number


def cents(value):
    return int((value*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if value is not None else None


def sum_optional(values):
    values=[value for value in values if value is not None]
    return sum(values) if values else None


class ChargeLedger:
    def __init__(self,store,database):
        self.store=store
        self.events=UsageEvents(database)

    def update(self,owner,vehicle,data,guard=None):
        action=data.get('action')
        identity=data.get('id')
        body=None
        if action=='save':
            date=data.get('date')
            if not isinstance(date,str) or len(date)!=10:
                raise ValueError('账单日期应为 YYYY-MM-DD。')
            day_bounds(date)
            source=data.get('source')
            if source not in ('home','public','unknown'):
                raise ValueError('请选择家充、外充或未分类。')
            note=data.get('note','')
            if not isinstance(note,str) or len(note)>1000:
                raise ValueError('备注应不超过 1000 字。')
            event_id=data.get('event_id')
            if event_id is not None and not isinstance(event_id,str):
                raise ValueError('关联充电记录无效。')
            event=self.events.get(vehicle,event_id) if event_id else None
            if event is not None and event['kind']!='charge_end':
                raise ValueError('只能关联已结束充电记录。')
            if event is not None:
                expected='charge_'+hashlib.sha256(event_id.encode()).hexdigest()
                if identity and identity!=expected:
                    raise ValueError('修改关联记录时，请另建账单。')
                identity=expected
            elif not identity:
                identity='manual_'+uuid.uuid4().hex
            elif not isinstance(identity,str) or not identity.startswith('manual_'):
                raise ValueError('手工账单编号无效。')
            amount=decimal_input(data.get('amount'),2,1000000)
            energy=decimal_input(data.get('metered_kwh'),3,10000)
            price=decimal_input(data.get('unit_price'),4,1000)
            fee=decimal_input(data.get('service_fee'),2,1000000)
            body={'date':date,'source':source,'note':note.strip(),'actual_cents':cents(amount),
                  'metered_kwh':float(energy) if energy is not None else None,
                  'unit_price':str(price) if price is not None else None,'service_fee_cents':cents(fee),'event':event}
        result=self.store.change(owner,vehicle,'charges',action,identity,body,data.get('revision'),guard=guard)
        return {'revision':result['revision'],'can_undo':result['can_undo'],'id':identity,
                'saved_date':body['date'] if body else None,'action':action}

    @staticmethod
    def entry(record):
        body=record['body']
        event=body.get('event')
        energy=body.get('metered_kwh')
        basis='metered_price' if energy is not None else 'soc_price'
        if energy is None and event:energy=event.get('estimated_kwh')
        price=body.get('unit_price')
        estimated=(cents(Decimal(str(energy))*Decimal(price))+(body.get('service_fee_cents') or 0)
                   if energy is not None and price is not None else None)
        return dict(body,id=record['id'],updated_at=record['updated_at'],deleted=record['deleted'],
                    estimated_cents=estimated,estimate_basis=basis if estimated is not None else None)

    @staticmethod
    def totals(entries):
        actual=[row['actual_cents'] for row in entries if row['actual_cents'] is not None]
        estimates=[row['estimated_cents'] for row in entries if row['actual_cents'] is None and row['estimated_cents'] is not None]
        return {'count':len(entries),'actual_cents':sum_optional(actual),'actual_count':len(actual),
                'unbilled_estimated_cents':sum_optional(estimates),'estimated_count':len(estimates),
                'unpriced_count':sum(row['actual_cents'] is None and row['estimated_cents'] is None for row in entries),
                'metered_kwh':total(row['metered_kwh'] for row in entries),
                'metered_count':sum(row['metered_kwh'] is not None for row in entries)}

    def query(self,owner,vehicle,date):
        window=period_window('month',date)
        saved=self.store.read(owner,vehicle,'charges')
        entries=[self.entry(record) for record in saved['records']]
        month=window['start_date'][:7]
        current=[row for row in entries if row['date'].startswith(month) and not row['deleted']]
        trash=[row for row in entries if row['date'].startswith(month) and row['deleted']]
        current.sort(key=lambda row:(row['date'],row['updated_at'],row['id']),reverse=True)
        events=self.events.between(vehicle,window['start'],window['end'])['events']
        trips=[row for row in events if row['kind']=='trip_end' and row['distance_km'] is not None]
        distance=total(row['distance_km'] for row in trips)
        totals=self.totals(current)
        actual=totals['actual_cents']
        combined=sum_optional((totals['actual_cents'],totals['unbilled_estimated_cents']))
        booked={row['event']['id']:row for row in entries if row.get('event') and not row['deleted']}
        choices=[dict(row,recorded=row['id'] in booked,bill_date=booked.get(row['id'],{}).get('date'))
                 for row in events if row['kind']=='charge_end']
        trend=[];period=window
        for _ in range(6):
            rows=[row for row in entries if row['date'].startswith(period['start_date'][:7]) and not row['deleted']]
            trend.append(dict(self.totals(rows),month=period['start_date'][:7]))
            period=period_window('month',period['previous_date'])
        return {'window':window,'revision':saved['revision'],'can_undo':saved['can_undo'],
                'entries':current,'trash':trash,'events':choices,'totals':totals,'trend':list(reversed(trend)),
                'sources':{key:self.totals([row for row in current if row['source']==key]) for key in ('home','public','unknown')},
                'cost_per_km':{'distance_km':distance,'distance_samples':len(trips),
                    'partial_distance_samples':sum(row['partial'] for row in trips),
                    'actual_yuan':round(actual/100/distance,6) if actual is not None and distance and distance>0 else None,
                    'including_estimates_yuan':round(combined/100/distance,6) if combined is not None and distance and distance>0 else None}}
