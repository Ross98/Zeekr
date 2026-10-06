"""Hypothesis-driven, read-only comparisons; no inferred meaning changes decoding."""
from collections import Counter
import json
import math
from .parameter_dictionary import FIELDS
from .vehicle_parameters import lookup, group_for, MISSING
from .web_model import fields_for, parse_location
from .parameter_studies import evidence_profiles, study_for, NO_OPTION, FUEL, heading_profile

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
        values = {}; quality={}
        for path in PUBLIC:
            value = lookup(raw,path)
            if value is MISSING:
                quality[path]='missing';continue
            if value is None:
                quality[path]='empty';continue
            if type(value) not in (str,int,float,bool) or isinstance(value,str) and (not value or len(value)>120) or isinstance(value,float) and not math.isfinite(value):
                quality[path]='invalid';continue
            if PUBLIC[path]['kind'] in ('number','timestamp'):
                try: valid=type(value) is not bool and math.isfinite(float(value))
                except (ValueError,TypeError):valid=False
                if not valid:
                    quality[path]='invalid';continue
            values[path] = json.dumps(value,ensure_ascii=False,allow_nan=False)
        location = parse_location(raw)
        position = (location['latitude'],location['longitude'],location['coordinate_system']) if location['valid'] else None
        effective[stamp] = {'time':stamp,'values':values,'_position':position,'_trusted':location['trusted'],'_quality':quality}
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
    heading=heading_profile(ordered)
    for row in ordered:
        row.pop('_position');row.pop('_trusted')
    known = {f['path']:f['evidence'] for f in fields_for(latest) if f['evidence'] not in ('待核实','未知')}
    presence={p:dict(valid=0,empty=0,missing=0,invalid=0) for p in PUBLIC}
    for row in ordered:
        for path in PUBLIC:presence[path][row['_quality'].get(path,'valid')]+=1
        row.pop('_quality')
    fields = [{'presence':presence[p],'path':p,'name':e['name'],'group':group_for(p),'kind':e['kind'],
               'evidence':known.get(p,'待解释'),'pending':p not in known} for p,e in PUBLIC.items()]
    return {'heading_profile':heading,'fields':fields,'samples':ordered,'reads':reads,'excluded':excluded,
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
    'propulsionType': {'4':'纯电驱动（本车车型对照）'},
    'fuelType': {'4':'电力（本车能源类型对照）'},
    'gearAutoStatus': {'0':'P 挡（驻车）','1':'R 挡（倒车）','2':'N 挡（空挡）','3':'D 挡（前进）'},
    'gearManualStatus': {'0':'不适用（纯电车型无手动挡）'},
    'electricParkBrakeStatus': {'0':'驻车制动释放','1':'驻车制动生效'},
    'usageMode': {'0':'休眠／默认模式','1':'停放模式','2':'充电相关模式','13':'行驶模式'},
    'centralLockingStatus': {'0':'未锁止','1':'解锁状态','2':'已锁止'},
    'chargerState': {'0':'空闲','1':'待机／连接准备','2':'交流充电','4':'交流充电停止','15':'直流充电工作态（与dcChargeSts=2及电流联合判断）','24':'直流充电进行中','26':'直流充电停止'},
    'dcChargeSts': {'0':'未进行直流充电','2':'直流充电运行码（与chargerState=15及电流联合判断）','12':'直流充电进行中','10':'直流充电结束'},
    'dcDcConnectStatus': {'0':'非充电连接态','1':'连接过渡态（推断）','3':'充电连接态'},
    'interiorPM25Level': {'0':'优','1':'良','2':'轻度污染','3':'中度污染','4':'重度污染'},
    'exteriorPM25Level': {'0':'优','1':'良','2':'轻度污染','3':'中度污染','4':'重度污染'},
    'hvTempLevel': {'0':'常规／默认温度等级','1':'非常规温度等级（方向未定）'},
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
        if key in NO_OPTION and row['status']=='single_value':
            meaning='本车未选装／不适用功能的占位码 '+normalized
            source='本车配置约束下的推断'
        elif key in FUEL and row['status']=='single_value' and key!='gearManualStatus':
            meaning='纯电车型兼容字段的固定返回 '+normalized+'（不是实测发动机/燃油量）'
            source='本车动力形式约束下的候选'
        elif key in ('drvHeatDetail','passHeatingDetail') and normalized=='2':
            meaning='保留的加热设定／默认编码2（不代表正在加热）'
            source='同组编码对照（未实车确认）'
        elif key in ('drvVentSts','passVentSts') and normalized=='1':
            meaning='通风已激活／运行允许（不保证设定档位非零）'
        elif key=='relHumSts':
            meaning='湿度原始指标 '+str(code)+'（百分比缩放未标定）'
            source='量纲检查'
        elif key=='dcChargeIAct':
            try:
                amps=float(code)
                direction='放电' if amps>0 else '充电／能量回收' if amps<0 else '无净电流'
                meaning=str(abs(amps))+' A（电池侧'+direction+'）'
                source='跨字段符号对照推断'
            except (ValueError,TypeError):pass
        elif key in ('chargeSts','statusOfChargerConnection','ptReady') and normalized=='0':
            meaning='本车该协议下的固定兼容码0（不单独判断活动状态）'
            source='跨活动场景的常量对照'
        elif '.mainBatteryStatus.' in row['path'] and key in ('stateOfCharge','stateOfHealth','energyLevel','powerLevel'):
            meaning='未标定的固定等级码 '+normalized+'（不是百分比或开关）'
            source='等级字段单值候选'
        elif key in ('brakeFluidLevelStatus','engineCoolantLevelStatus') and normalized=='3':
            meaning='固定液位码3（正常/未知枚举尚未区分）'
            source='常量液位字段，未标定'
        elif key in ('timeToFullyCharged','timeToTargetDisCharged') and normalized=='2047':
            meaning='暂无有效时间估计（哨兵2047）'
            source='既有字典哨兵解释'
        elif row['path'] in ('parkTime.status','theftNotification.time'):
            try:
                scale=1000 if row['path']=='parkTime.status' else 1
                meaning=datetime.fromtimestamp(float(code)/scale,BEIJING).strftime('%Y-%m-%d %H:%M:%S')+'（停车相关时刻）' if scale==1000 else datetime.fromtimestamp(float(code),BEIJING).strftime('%Y-%m-%d %H:%M:%S')+'（历史防盗通知时刻）'
                source='时间尺度推断与换算'
            except (ValueError,TypeError,OverflowError,OSError):meaning='无效时间值'
        if key=='gearAutoStatus' and meaning:
            source='用户指定映射'
        if meaning is None and kind=='timestamp':
            try:meaning=datetime.fromtimestamp(float(code)/1000,BEIJING).strftime('%Y-%m-%d %H:%M:%S')+'（北京时间）'
            except (ValueError,TypeError,OverflowError,OSError):meaning='无效时间戳'
            source='时间换算'
        elif meaning is None and kind=='text':
            meaning=str(code)
            source='文本原值'
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
        if normalized=='0' and ('OpenStatus' in key) and key not in NO_OPTION:
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
        studies=evidence_profiles(prepared['samples'])
        studies['direction']=prepared['heading_profile']
        for row in result['candidates']:
            row['study']=study_for(row,studies)
            keys=sorted(set(row['inside'])|set(row['outside'])|set(row['unknown']),key=lambda k:-(row['inside'].get(k,0)+row['outside'].get(k,0)+row['unknown'].get(k,0)))
            row['displayed_values']=keys[:20]
            row['other_values']=max(0,len(keys)-20)
            row['proposal']=propose(row)
            for group in ('inside','outside','unknown'):
                row[group]={k:row[group][k] for k in keys[:20] if k in row[group]}
        result['candidates'].sort(key=lambda r:(r['study']['stage']=='cross_checked',r['status']=='varied',r['kind'] in ('enum','boolean'),r['transitions']['both'],r['count']),reverse=True)
        result['study_counts']={stage:sum(r['study']['stage']==stage for r in result['candidates']) for stage in ('cross_checked','scenario_only','constant_only','no_data','existing_interpretation')}
        result.update(start_date=start,end_date=end,state=state,anchor=anchor,value=value,
                      catalog=len(PUBLIC),reads=prepared['reads'],valid_samples=len(prepared['samples']),
                      excluded=prepared['excluded'],collapsed=prepared['collapsed'],
                      boundary_unknown=sum(r.get('start_time') is None for r in history),
                      source='保存的事件边界与有效车辆时间；缺少事件记录不能证明没有活动；未确认假设不改变运行解码')
        return result
