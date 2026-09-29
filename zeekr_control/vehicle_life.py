"""Private expense records and user-scheduled, in-app vehicle tasks."""
import time
import uuid

from .charge_ledger import cents, decimal_input
from .tracks import day_bounds
from .usage_events import number
from .usage_reports import date_label, period_window
from .vehicle_state import decode

DEFAULT_CATEGORIES=('保险','停车','洗车','保养','轮胎','其他')


def text(data,key,maximum,required=False):
    value=data.get(key,'')
    if not isinstance(value,str) or len(value)>maximum or required and not value.strip():
        raise ValueError('名称、分类或备注无效，请检查必填内容和字数限制。')
    return value.strip()


def date_input(value,optional=False):
    if optional and value=='':return None
    if not isinstance(value,str):raise ValueError('日期格式应为 YYYY-MM-DD。')
    day_bounds(value)
    return value


def odometer(raw,fetched_at,now):
    state=decode(raw if isinstance(raw,dict) else {})
    stamp=number(state['time'],1,32503680000000)
    fetched=number(fetched_at,1,32503680000000)
    fresh=(stamp is not None and fetched is not None and -60000<=now-stamp<=600000
           and -60000<=now-fetched<=600000 and -60000<=fetched-stamp<=600000)
    km=state['km']
    return dict(value=km if fresh else None,state_time=stamp,fetched_at=fetched,
                reason='fresh' if fresh and km is not None else 'missing' if km is None or stamp is None or fetched is None else 'stale_or_invalid_time')


def reminder_status(body,current,today):
    reasons=[]
    if body['due_date'] and body['due_date']<=today:reasons.append('date')
    if body['due_km'] is not None and current['value'] is not None and current['value']>=body['due_km']:reasons.append('mileage')
    status=('completed' if body['completed_at'] is not None else 'due' if reasons
            else 'unknown' if body['due_km'] is not None and current['value'] is None else 'upcoming')
    return dict(status=status,due_reasons=reasons if status=='due' else [])


class VehicleLife:
    def __init__(self,store,clock=None):
        self.store=store
        self.clock=clock or (lambda:int(time.time()*1000))

    def update(self,owner,vehicle,data,guard=None):
        collection=data.get('collection')
        if collection not in ('expenses','reminders'):raise ValueError('生活账本记录类型无效。')
        action=data.get('action');identity=data.get('id');body=None;save_action=action
        if action in ('save','complete','reopen'):
            saved=self.store.read(owner,vehicle,collection)
            existing=next((r for r in saved['records'] if r['id']==identity),None) if identity else None
            if identity and existing is None:raise ValueError('记录不存在或不属于当前账号车辆。')
            if existing and existing['deleted']:raise ValueError('请先恢复已删除的记录。')
            if action in ('complete','reopen'):
                if collection!='reminders' or existing is None:raise ValueError('请选择有效待办。')
                body=dict(existing['body'])
                if (body['completed_at'] is not None)==(action=='complete'):raise ValueError('待办状态已变化，请重新读取。')
                body['completed_at']=self.clock() if action=='complete' else None
                save_action='save'
            else:
                title=text(data,'title',80,True);note=text(data,'note',1000)
                if collection=='expenses':
                    category=text(data,'category',24,True)
                    categories=set(DEFAULT_CATEGORIES)|{r['body']['category'] for r in saved['records']}
                    if category not in categories and len(categories)>=100:raise ValueError('自定义分类数量已达上限。')
                    amount=decimal_input(data.get('amount'),2,10000000)
                    if amount is None:raise ValueError('请填写实际金额；免费项目可填 0。')
                    km=decimal_input(data.get('odometer'),1,10000000)
                    body=dict(title=title,category=category,date=date_input(data.get('date')),amount_cents=cents(amount),
                              odometer=float(km) if km is not None else None,note=note)
                else:
                    date=date_input(data.get('due_date',''),optional=True)
                    km=decimal_input(data.get('due_km'),1,10000000)
                    if date is None and km is None:raise ValueError('请至少填写到期日期或里程。')
                    body=dict(title=title,due_date=date,due_km=float(km) if km is not None else None,note=note,
                              completed_at=existing['body']['completed_at'] if existing else None)
                if not identity:identity=collection+'_'+uuid.uuid4().hex
        result=self.store.change(owner,vehicle,collection,save_action,identity,body,data.get('revision'),guard=guard)
        return dict(collection=collection,id=identity,revision=result['revision'],can_undo=result['can_undo'],
                    saved_date=body.get('date') if body else None)

    def query(self,owner,vehicle,date,raw=None,fetched_at=None,end=None):
        if end is None:
            window=period_window('month',date)
        else:
            day_bounds(date);day_bounds(end)
            if end<date:raise ValueError('结束日期不能早于开始日期。')
            window=dict(start_date=date,end_date=end,period='range')
        now=self.clock();current=odometer(raw,fetched_at,now)
        costs=self.store.read(owner,vehicle,'expenses');saved=self.store.read(owner,vehicle,'reminders')
        rows=[dict(r['body'],id=r['id'],deleted=r['deleted'],updated_at=r['updated_at']) for r in costs['records']]
        categories=sorted(set(DEFAULT_CATEGORIES)|{r['category'] for r in rows})
        rows=[r for r in rows if window['start_date']<=r['date']<=window['end_date']]
        entries=sorted((r for r in rows if not r['deleted']),key=lambda r:(r['date'],r['updated_at'],r['id']),reverse=True)
        by_category={}
        for row in entries:
            group=by_category.setdefault(row['category'],dict(count=0,amount_cents=0))
            group['count']+=1;group['amount_cents']+=row['amount_cents']
        reminders=[dict(r['body'],id=r['id'],deleted=r['deleted'],updated_at=r['updated_at'],
                        **reminder_status(r['body'],current,date_label(now))) for r in saved['records']]
        counts={key:sum(r['status']==key and not r['deleted'] for r in reminders) for key in ('due','upcoming','unknown','completed')}
        return dict(window=window,as_of=now,odometer=current,category_choices=categories,
                    expenses=dict(revision=costs['revision'],can_undo=costs['can_undo'],entries=entries,
                                  trash=[r for r in rows if r['deleted']],total_cents=sum(r['amount_cents'] for r in entries),categories=by_category),
                    reminders=dict(revision=saved['revision'],can_undo=saved['can_undo'],records=reminders,counts=counts))
