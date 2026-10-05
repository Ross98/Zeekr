"""Hypothesis-driven, read-only comparisons; no inferred meaning changes decoding."""
from collections import Counter
import json
import math
from .parameter_dictionary import FIELDS
from .vehicle_parameters import lookup, group_for
from .web_model import fields_for, parse_location

PUBLIC = {p:e for p,e in FIELDS.items() if not e['private']}
MAX_GAP = 600000


def prepare(samples, trips, charges):
    effective, reads, excluded, latest = {}, 0, 0, {}
    for record, raw in samples:
        reads += 1
        if reads > 150000:
            raise ValueError('读取超过 150000 条，请缩小日期范围。')
        stamp = record.get('state_time')
        if type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp <= 0 or record.get('flags') or record.get('change')=='regression':
            excluded += 1
            continue
        values = {}
        for path in PUBLIC:
            value = lookup(raw,path)
            if type(value) not in (str,int,float,bool) or isinstance(value,str) and len(value)>120 or isinstance(value,float) and not math.isfinite(value):
                continue
            values[path] = json.dumps(value,ensure_ascii=False,allow_nan=False)
        location = parse_location(raw)
        position = (location['latitude'],location['longitude'],location['coordinate_system']) if location['valid'] else None
        effective[stamp] = {'time':stamp,'values':values,'_position':position}
        latest = raw
    ordered = sorted(effective.values(),key=lambda r:r['time'])
    def contains(events,t):
        return any(type(r.get('start_time')) in (int,float) and type(r.get('end_time')) in (int,float)
                   and r['start_time']<=t<r['end_time'] for r in events)
    previous = None
    for row in ordered:
        trip = contains(trips,row['time'])
        charge = contains(charges,row['time'])
        parked = False if trip or charge else None if not previous or row['_position'] is None or previous['_position'] is None else row['_position']==previous['_position']
        row['states'] = {'trip':trip,'charging':False if trip else charge,'parked':parked}
        previous = row
    for row in ordered:
        row.pop('_position')
    known = {f['path']:f['evidence'] for f in fields_for(latest) if f['evidence'] not in ('待核实','未知')}
    fields = [{'path':p,'name':e['name'],'group':group_for(p),'kind':e['kind'],
               'evidence':known.get(p,'待解释'),'pending':p not in known} for p,e in PUBLIC.items()]
    return {'fields':fields,'samples':ordered,'reads':reads,'excluded':excluded,
            'collapsed':reads-excluded-len(ordered)}


def investigate(data, state, *, anchor=None, value=None):
    if state not in ('trip','charging','parked','anchor') or state=='anchor' and anchor not in PUBLIC:
        raise ValueError('请选择已知状态或公开参数作为对照。')
    samples = data['samples']
    target = [(None if anchor not in r['values'] else r['values'][anchor]==value)
              if state=='anchor' else r['states'][state] for r in samples]
    candidates = []
    for field in data['fields']:
        path = field['path']
        if state=='anchor' and path==anchor:
            continue
        inside,outside,unknown = Counter(),Counter(),Counter()
        transitions = dict(both=0,state_only=0,field_only=0,neither=0,gaps=0,unavailable=0)
        examples = {k:[] for k in ('both','state_only','field_only')}
        previous = None
        for row,active in zip(samples,target):
            code=row['values'].get(path)
            if code is not None:
                (inside if active is True else outside if active is False else unknown)[code]+=1
            if previous:
                old,old_active=previous;old_code=old['values'].get(path)
                if row['time']-old['time']>MAX_GAP:
                    transitions['gaps']+=1
                elif code is None or old_code is None or active is None or old_active is None:
                    transitions['unavailable']+=1
                else:
                    a,b=active!=old_active,code!=old_code
                    key='both' if a and b else 'state_only' if a else 'field_only' if b else 'neither'
                    transitions[key]+=1
                    if key in examples and len(examples[key])<8:
                        examples[key].append({'before':old['time'],'after':row['time'],
                                              'before_value':old_code,'after_value':code,
                                              'before_state':old_active,'after_state':active})
            previous=row,active
        all_values=inside+outside+unknown
        # Queue order is evidence availability, not a probability of a meaning.
        candidates.append(dict(field,distinct=len(all_values),count=sum(all_values.values()),
            status='missing' if not all_values else 'single_value' if len(all_values)==1 else 'varied',
            inside=dict(inside),outside=dict(outside),unknown=dict(unknown),transitions=transitions,examples=examples))
    candidates.sort(key=lambda r:(r['status']=='varied',r['transitions']['both'],r['count']),reverse=True)
    return {'candidates':candidates,'target_true':sum(v is True for v in target),
            'target_false':sum(v is False for v in target),'target_unknown':sum(v is None for v in target)}


def propose(row):
    """A deliberately bold first draft, labelled and independent of runtime enums."""
    name,path=row['name'],row['path']
    if row['status']=='missing':
        meaning=f'可能对应{name}；尚无返回值，暂不能推断编码。'
    elif row['kind']=='number':
        meaning=f'可能为{name}的直接量值；单位、缩放和无效哨兵值需用实车对照核实。'
    elif row['status']=='single_value':
        meaning=f'当前常量可能是未启用、缺省或本车不适用的返回；暂不直接当作关闭。'
    elif path.endswith('gearAutoStatus'):
        meaning='暂按用户指定：0=P 驻车、1=R 倒车、2=N 空挡、3=D 前进。'
    elif path.endswith('electricParkBrakeStatus'):
        meaning='大胆假设：0=驻车制动释放，1=驻车制动生效。'
    elif path.endswith('usageMode'):
        meaning='大胆假设：13=行驶模式，1=停放模式，2=充电相关模式，0=休眠或缺省模式。'
    elif any(word in name for word in ('开闭','口盖','打开','开关','激活','启用')):
        meaning=f'大胆假设：0=关闭或未启用，1=打开或启用；其他编码可能为细分状态。'
    elif any(word in name for word in ('锁','锁止')):
        meaning=f'大胆假设：较常见停车编码代表锁止，行程编码代表解锁；需查锁车操作前后。'
    else:
        meaning=f'大胆假设：这是{name}的状态枚举；在目标场景集中出现的编码可能代表该功能生效。'
    tr=row['transitions']
    return {'source':'自动假设，未确认','meaning':meaning,
            'basis':f"同一有效间隔内状态与参数都变 {tr.get('both',0)} 次；只有状态变 {tr.get('state_only',0)} 次；只有参数变 {tr.get('field_only',0)} 次。",
            'next':'优先回看两种反例和状态切换前后；实际操作与编码不吻合时，修改或推翻假设。'}


class HypothesisLab:
    def __init__(self,archive,database):
        self.archive,self.database=archive,database

    def query(self,scope,vehicle,start,end,state='trip',anchor='',value=''):
        from .tracks import day_bounds
        from .usage_events import UsageEvents
        lower,_=day_bounds(start);_,upper=day_bounds(end)
        if not 0<upper-lower<=31*86400000:
            raise ValueError('请选择不超过 31 天的研究范围。')
        if state not in ('trip','charging','parked','anchor') or state=='anchor' and (anchor not in PUBLIC or not isinstance(value,str) or len(value)>130):
            raise ValueError('请选择公开字段和有效对照条件。')
        history=UsageEvents(self.database).between(vehicle,max(0,lower-31*86400000),upper+31*86400000)['events']
        def samples():
            cursor=lower
            while cursor<upper:
                stop=min(cursor+86400000,upper)
                yield from self.archive.iter_records(scope,vehicle,cursor,stop)
                cursor=stop
        prepared=prepare(samples(),[r for r in history if r['kind']=='trip_end'],[r for r in history if r['kind']=='charge_end'])
        result=investigate(prepared,state,anchor=anchor,value=value)
        for row in result['candidates']:
            row['proposal']=propose(row)
            keys=sorted(set(row['inside'])|set(row['outside'])|set(row['unknown']),key=lambda k:-(row['inside'].get(k,0)+row['outside'].get(k,0)+row['unknown'].get(k,0)))
            row['displayed_values']=keys[:20]
            row['other_values']=max(0,len(keys)-20)
            for group in ('inside','outside','unknown'):
                row[group]={k:row[group][k] for k in keys[:20] if k in row[group]}
        result.update(start_date=start,end_date=end,state=state,anchor=anchor,value=value,
                      catalog=len(PUBLIC),reads=prepared['reads'],valid_samples=len(prepared['samples']),
                      excluded=prepared['excluded'],collapsed=prepared['collapsed'],
                      boundary_unknown=sum(r.get('start_time') is None for r in history),
                      source='保存的事件边界与有效车辆时间；缺少事件记录不能证明没有活动；未确认假设不改变运行解码')
        return result
