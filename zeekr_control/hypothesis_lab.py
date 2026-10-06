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


# Explicit research mappings; no runtime decoder consumes this table.
CODE_MEANINGS = {
    'gearAutoStatus': {'0':'P 挡（驻车）','1':'R 挡（倒车）','2':'N 挡（空挡）','3':'D 挡（前进）'},
    'gearManualStatus': {'0':'不适用（纯电车型无手动挡）'},
    'electricParkBrakeStatus': {'0':'驻车制动释放','1':'驻车制动生效'},
    'usageMode': {'0':'休眠／默认模式','1':'停放模式','2':'充电相关模式','13':'行驶模式'},
    'centralLockingStatus': {'0':'未锁止','1':'解锁状态','2':'已锁止'},
    'chargerState': {'0':'空闲','1':'待机／连接准备','2':'交流充电','4':'交流充电停止','15':'直流充电准备阶段','24':'直流充电进行中','26':'直流充电停止'},
    'dcChargeSts': {'0':'未进行直流充电','2':'直流充电初始阶段','12':'直流充电进行中','10':'直流充电结束'},
    'dcDcConnectStatus': {'0':'未连接','1':'待机连接','3':'充电供电连接'},
    'interiorPM25Level': {'0':'优','1':'良','2':'轻度污染','3':'中度污染','4':'重度污染'},
    'exteriorPM25Level': {'0':'优','1':'良','2':'轻度污染','3':'中度污染','4':'重度污染'},
    'hvTempLevel': {'0':'正常温度等级','1':'升高温度等级'},
}


def value_meanings(row):
    from datetime import datetime
    from .snapshot_archive import BEIJING
    key=row['path'].rsplit('.',1)[-1]
    entry=PUBLIC.get(row['path'],{})
    name=row['name'];kind=row['kind']
    codes=row.get('displayed_values') or list(dict.fromkeys(list(row['inside'])+list(row['outside'])+list(row['unknown'])))[:20]
    result=[]
    for raw in codes:
        code=json.loads(raw)
        normalized=str(code).lower() if type(code) is bool else str(code)
        source='推断映射'
        meaning=CODE_MEANINGS.get(key,{}).get(normalized)
        if key=='gearAutoStatus' and meaning:
            source='用户指定映射'
        if meaning is None and kind=='timestamp':
            try:meaning=datetime.fromtimestamp(float(code)/1000,BEIJING).strftime('%Y-%m-%d %H:%M:%S')+'（北京时间）'
            except (ValueError,TypeError,OverflowError,OSError):meaning='无效时间戳'
            source='时间换算'
        elif meaning is None and kind=='number':
            unit=entry.get('unit','—')
            meaning=str(code)+(' '+unit if unit not in ('—','') else '（原始数值）')
            source='字段单位解释'
        elif meaning is None and key.startswith('seatBeltStatus'):
            meaning={'true':'已系','false':'未系','1':'已系','0':'未系'}.get(normalized)
        elif meaning is None and ('VentSts' in key or 'HeatingSts' in key):
            meaning={'1':'运行','2':'关闭','0':'未启用'}.get(normalized)
        elif meaning is None and ('VentDetail' in key or 'HeatingDetail' in key or '加热档位' in name or '通风档位' in name):
            meaning={'0':'关闭','1':'低档','2':'中档','3':'高档'}.get(normalized)
        elif meaning is None and key.startswith('winStatus'):
            meaning={'1':'打开','2':'关闭'}.get(normalized)
        elif meaning is None and key.startswith('chargeLid'):
            meaning={'1':'打开','2':'关闭'}.get(normalized)
        elif meaning is None and 'OpenStatus' in key:
            meaning={'0':'关闭','1':'打开'}.get(normalized)
        elif meaning is None and 'LockStatus' in key:
            meaning={'0':'未锁','1':'已锁'}.get(normalized)
        elif meaning is None and key=='posCanBeTrusted':
            meaning={'true':'定位可信','false':'定位不可信'}.get(normalized)
        elif meaning is None and any(word in name for word in ('报警','警告','故障')):
            meaning={'0':'未触发／正常','1':'已触发','false':'未触发／正常','true':'已触发'}.get(normalized)
        elif meaning is None:
            meaning={'0':'关闭／未启用','1':'开启／启用','false':'关闭／未启用','true':'开启／启用'}.get(normalized)
        if meaning is None:
            meaning='未解释编码 '+str(code)
            source='待核实'
        if normalized=='0' and ('OpenStatus' in key):
            source='本车已核对'
        result.append({'raw':raw,'meaning':meaning,'source':source})
    return result


def propose(row):
    """A deliberately bold first draft, labelled and independent of runtime enums."""
    mappings=value_meanings(row)
    meaning='；'.join(str(json.loads(item['raw']))+'='+item['meaning'] for item in mappings)
    if not meaning:
        meaning='尚无返回值；没有已出现的编码可解释。'
    if row['status']=='single_value' and not row['path'].endswith('gearAutoStatus'):
        meaning+='。单一值解释按推断使用，缺省返回仍须核对。'
    if len(meaning)>200:
        meaning=meaning[:180]+'…；完整逐值解释见码表。'
    tr=row['transitions']
    return {'source':'自动假设，未确认','meaning':meaning,'value_meanings':mappings,
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
            keys=sorted(set(row['inside'])|set(row['outside'])|set(row['unknown']),key=lambda k:-(row['inside'].get(k,0)+row['outside'].get(k,0)+row['unknown'].get(k,0)))
            row['displayed_values']=keys[:20]
            row['other_values']=max(0,len(keys)-20)
            row['proposal']=propose(row)
            for group in ('inside','outside','unknown'):
                row[group]={k:row[group][k] for k in keys[:20] if k in row[group]}
        result.update(start_date=start,end_date=end,state=state,anchor=anchor,value=value,
                      catalog=len(PUBLIC),reads=prepared['reads'],valid_samples=len(prepared['samples']),
                      excluded=prepared['excluded'],collapsed=prepared['collapsed'],
                      boundary_unknown=sum(r.get('start_time') is None for r in history),
                      source='保存的事件边界与有效车辆时间；缺少事件记录不能证明没有活动；未确认假设不改变运行解码')
        return result
