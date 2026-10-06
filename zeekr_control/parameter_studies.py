"""Per-field research register and reproducible cross-field checks, not a decoder."""
import json
import math
from collections import Counter
from statistics import median
from datetime import datetime
from .parameter_dictionary import FIELDS
from .snapshot_archive import BEIJING

P='additionalVehicleStatus.'

def number(row,path):
    try:
        raw=json.loads(row['values'][path])
        if type(raw) not in (int,float,str):return None
        value=float(raw)
        return value if math.isfinite(value) else None
    except (KeyError,ValueError,TypeError):return None


def evidence_profiles(samples):
    out={}
    odo=P+'maintenanceStatus.odometer'
    for key,plus in [('distanceToService',True),('tripMeter1',False)]:
        path=P+('maintenanceStatus.' if plus else 'runningStatus.')+key
        pairs=[(number(r,path),number(r,odo)) for r in samples]
        pairs=[(a,b) for a,b in pairs if a is not None and b is not None]
        if pairs:
            offsets=[a+b if plus else a-b for a,b in pairs]
            out[key]={'pairs':len(pairs),'spread':round(max(offsets)-min(offsets),3),'anchor_span':max(b for a,b in pairs)-min(b for a,b in pairs)}
    current=P+'electricVehicleStatus.dcChargeIAct';pile=P+'electricVehicleStatus.dcChargePileIAct'
    sign=Counter();ratios=[]
    for r in samples:
        a,b=number(r,current),number(r,pile)
        if a is None:continue
        state='charge' if r['states']['charging'] else 'trip' if r['states']['trip'] else 'other'
        sign[state+'_negative' if a<0 else state+'_positive' if a>0 else state+'_zero']+=1
        if state=='charge' and a<0 and b is not None and b>0:ratios.append(-a/b)
    out['dcChargeIAct']=dict(sign,paired_charge=len(ratios),ratio_median=round(median(ratios),4) if ratios else None)
    h=P+'pollutionStatus.relHumSts';vals=[number(r,h) for r in samples];vals=[v for v in vals if v is not None]
    if vals:out['relHumSts']={'samples':len(vals),'min':min(vals),'max':max(vals),'over_100':sum(v>100 for v in vals)}
    days=P+'maintenanceStatus.daysToService';vals=[(r['time'],number(r,days)) for r in samples if number(r,days) is not None]
    if vals:
        day_delta=(datetime.fromtimestamp(vals[-1][0]/1000,BEIJING).date()-datetime.fromtimestamp(vals[0][0]/1000,BEIJING).date()).days
        out['daysToService']={'samples':len(vals),'calendar_days':day_delta,'decrease':vals[0][1]-vals[-1][1],'distinct':len({v for t,v in vals})}
    stamp_path='parkTime.status';engine_path='basicVehicleStatus.engineStatus'
    changes=[];off_times=[];park_times=[];previous=None
    for r in samples:
        park_stamp=number(r,stamp_path)
        engine=r['values'].get(engine_path);gear=r['values'].get(P+'drivingBehaviourStatus.gearAutoStatus')
        if previous:
            if engine=='"engine_off"' and engine!=previous['values'].get(engine_path):off_times.append(r['time'])
            if gear=='"0"' and gear!=previous['values'].get(P+'drivingBehaviourStatus.gearAutoStatus'):park_times.append(r['time'])
            if park_stamp is not None and park_stamp!=number(previous,stamp_path):changes.append(park_stamp)
        previous=r
    def matched(times):
        differences=[min(abs(v-t) for t in times)/1000 for v in changes] if times else []
        return sum(v<=600 for v in differences)
    out['parkTime.status']={'timestamp_changes':len(changes),'near_power_off':matched(off_times),'near_p_gear':matched(park_times)}
    for key,state in [('drvHeatDetail','drvHeatSts'),('passHeatingDetail','passHeatingSts'),('rlHeatingDetail','rlHeatingSts'),('rrHeatingDetail','rrHeatingSts')]:
        off=Counter();path=P+'climateStatus.'+key;anchor=P+'climateStatus.'+state
        for r in samples:
            a,b=number(r,path),number(r,anchor)
            if a is not None and b in (0,2):off[str(int(a))]+=1
        out[key]={'returned_while_off':dict(off),'off_samples':sum(off.values())}
    meter=P+'runningStatus.tripMeter2';vals=[(r['time'],number(r,meter)) for r in samples if number(r,meter) is not None]
    out['tripMeter2']={'samples':len(vals),'reset_windows':sum(b<a-1 for (t,a),(u,b) in zip(vals,vals[1:])),
                     'max':max((v for t,v in vals),default=None)}
    v=P+'maintenanceStatus.mainBatteryStatus.voltage';soc=P+'maintenanceStatus.mainBatteryStatus.chargeLevel'
    out['aux_voltage']={'low_voltage_zero_soc':sum(number(r,v) is not None and number(r,v)<8 and number(r,soc)==0 for r in samples)}
    def code(r,path):
        try:
            v=json.loads(r['values'][path])
            return str(v).lower() if type(v) is bool else str(v)
        except (KeyError,ValueError):return None
    def joint(path,anchor):
        counts=Counter((code(r,path),code(r,anchor)) for r in samples)
        return [{'value':a,'anchor':b,'count':n} for (a,b),n in counts.items() if a is not None and b is not None]
    for side in ('Driver','Passenger','DriverRear','PassengerRear'):
        k='winStatus'+side
        out[k]={'anchor':'winPos'+side,'joint':joint(P+'climateStatus.'+k,P+'climateStatus.winPos'+side)}
    for seat in ('drv','pass'):
        k=seat+'VentSts'
        out[k]={'anchor':seat+'VentDetail','joint':joint(P+'climateStatus.'+k,P+'climateStatus.'+seat+'VentDetail')}
    out['reverseLi']={'anchor':'gearAutoStatus (用户指定映射)','joint':joint(P+'runningStatus.reverseLi',P+'drivingBehaviourStatus.gearAutoStatus')}
    out['ahbc']={'anchor':'hiBeam','joint':joint(P+'runningStatus.ahbc',P+'runningStatus.hiBeam')}
    out['chargerState']={'anchor':'dcChargeSts','joint':joint(P+'electricVehicleStatus.chargerState',P+'electricVehicleStatus.dcChargeSts')}
    charge_pairs=Counter()
    for r in samples:
        state=code(r,P+'electricVehicleStatus.dcChargeSts');amps=number(r,P+'electricVehicleStatus.dcChargePileIAct')
        if state is not None and amps is not None:charge_pairs[(state,'正电流' if amps>0 else '负电流' if amps<0 else '零电流')]+=1
    out['dcChargeSts']={'anchor':'桩侧电流符号','joint':[{'value':a,'anchor':b,'count':n} for (a,b),n in charge_pairs.items()]}
    out['dcDcConnectStatus']={'anchor':'dcDcActvd','joint':joint(P+'electricVehicleStatus.dcDcConnectStatus',P+'electricVehicleStatus.dcDcActvd')}
    for side in ('Driver','Passenger','DriverRear','PassengerRear'):
        k='seatBeltStatus'+side
        counts=Counter((code(r,P+'drivingSafetyStatus.'+k),r['states']['trip']) for r in samples)
        out[k]={'anchor':'保存的行程区间','joint':[{'value':a,'anchor':'行程内' if b else '行程外','count':n} for (a,b),n in counts.items() if a is not None]}
    return out


DEFINITIONS={
 'chargerState':('充电器工作码；15+dcChargeSts=2与24+dcChargeSts=12都可对应实际直流充电。','结合桩侧电压/电流判断是否实际充电，不把15一概当准备态。'),
 'dcChargeSts':('直流充电工作码；2在实际充电样本中大量出现，不仅是初始阶段。','与充电器阶段、电流和SOC变化联合核对。'),
 'propulsionType':('本车动力形式码4对应纯电驱动；其他枚举没有车型对照。','依据已记录2023 WE86纯电车型；不套用其他厂商编码。'),
 'fuelType':('本车能源类型码4对应电力；不是汽油燃油标号。','依据实际纯电车型、充电与里程资料。'),
 'theftNotification.activated':('历史防盗通知的保留状态码，不作当前布防/报警开关。','与历史通知时间一起看；本期没有状态变化，枚举3不能认作实时已布防。'),
 'dcChargeIAct':('电池侧高压电流：正值放电，负值充电或能量回收；不是桩侧电流。','对照保存的充电区间、桩侧电流符号及行程中电流变化。'),
 'distanceToService':('距下次保养的剩余里程，单位 km。','检查它与总里程的和是否保持不变。'),
 'daysToService':('距下次保养的剩余天数。','对照日历经过天数与原值递减。'),
 'tripMeter1':('累计小计里程 A，单位 km；观察期未见清零，不是总里程。','对照与总里程的增量及差值稳定性。'),
 'tripMeter2':('可复位的驾驶周期小计里程 B，单位 km；不是固定自然日里程。','回看归零时刻与启动、行程开始；归零机制尚需实车核对。'),
 'relHumSts':('湿度传感器原始指标；百分比缩放未标定，不直接显示为 %RH。','比较直接百分比、0.5缩放、字节量程等假设；缺少独立湿度读数时不选择换算系数。'),
 'parkTime.status':('最近一次停车相关事件时间，Unix 毫秒；触发是挂P或下电尚待区分。','与行程结束和动力关闭的边界对照，不当停车持续时长。'),
 'theftNotification.time':('防盗通知的历史时间，Unix 秒；不表示此刻仍有报警。','核对时间数量级、通知时间是否变化；常量只证明旧时间被保留。'),
 'direction':('车辆航向角原值，按度解释；0–360的方向约定尚需轨迹对照。','用移动轨迹方位核对0北/顺时针假设；静止和定位漂移不用于标定。'),
 'altitude':('定位海拔高度，单位 m 候选；允许负值，GPS噪声不当作楼层变化。','需要可信定位和独立地形高度；本期只有量级支持，绝对高度未标定。'),
 'speed':('车速，单位 km/h；只有 speedValidity 有效时才是有效车速。','原值与有效标记必须一起看，无效标记下不确认车辆移动。'),
 'avgSpeed':('平均速度统计量，单位 km/h 候选；统计窗口未知。','不能把它当瞬时速度，需对照小计里程和驾驶周期。'),
 'averPowerConsumption':('平均电耗统计量，单位 kWh/100km 候选；99.9为显示上限候选。','核对与里程、SOC变化的关系；没有电表量或清零动作时不确认窗口与上限语义。'),
 'hvTempLevel':('高压相关温度等级标记：0常规/默认，1非常规等级；高温或低温方向未定。','没有独立高压温度，不能将1直接解释成温度升高。'),
 'ahbc':('自动远光控制的启用/待命标记，不等同于远光灯当前点亮。','与hiBeam实际灯状态分开对照，检查控制启用时远光仍关闭的样本。'),
 'ahl':('前照灯自适应/调平相关工作标记；具体是哪一种功能尚未区分。','对照近光、转向和行程；没有照射高度数据时不确认自动调平。'),
 'cornrgLi':('转角辅助照明激活标记，0未激活、1激活。','对照转向灯、低速和航向变化；具体触发条件仍需操作实验。'),
 'fragActive':('香氛功能激活标记，false未激活、true激活；不保证正在喷香。','激活与风机/工作模式分开看，实际释放需车内操作对照。'),
 'dcDcActvd':('DC/DC转换器激活标记，0未激活、1激活。','对照行程、充电与低压电压；停车中仍可激活，不能当作行程标记。'),
 'chargeSts':('平台充电兼容状态字段；本期0在充电与非充电均出现，不可将0解释为未充电。','充电判断用已核对的组合和实测电流，此字段常量需其他枚举样本。'),
 'statusOfChargerConnection':('平台连接兼容字段；本期0不能独立证明未插枪。','已有充电记录时仍为0，需与口盖、桩电流和充电器阶段联合核对。'),
 'ptReady':('动力就绪平台字段；本期0不能独立证明动力关闭。','行程和非行程均为0，需结合engineStatus与有效车速。'),
}

NO_OPTION={'rlHeatingSts','rrHeatingSts','rlHeatingDetail','rrHeatingDetail','steerWhlHeatingSts',
           'sunroofPos','sunroofOpenStatus','curtainPos','curtainOpenStatus','sunCurtainRearPos','sunCurtainRearOpenStatus'}
FUEL={'gearManualStatus','engineSpeed','indFuelConsumption','fuelEnLevel','fuelLevelPct','fuelEnCns','fuelEnCnsFild','engineHrsToService'}


def study_for(row,evidence):
    path=row['path'];key=path.rsplit('.',1)[-1];lookup_key=path if path in DEFINITIONS else key
    entry=FIELDS.get(path,{})
    definition,test=DEFINITIONS.get(lookup_key,(entry.get('name',row['name'])+'：'+entry.get('note','含义需独立场景对照。'),
                                               '核对已出现原值、场景及两种反例；名称和通用规则不算专门论证。'))
    ev=evidence.get(lookup_key,evidence.get(key,{}))
    if key in {'drvHeatDetail','passHeatingDetail'}:
        definition='加热设定/默认编码；设备关闭时仍保留，不能将编码2当作正在中档加热。'
        test='核对加热运行状态为0/2时，设定值是否仍返回；具体档位需真实操作标定。'
    if key in NO_OPTION:
        definition='本车未选装/不适用的功能字段；固定返回不能当作真实开闭或加热状态。'
        test='依据本车已记录配置：无机械可开启天窗、无电动遮阳帘、未选装方向盘/后排加热；车型配置优先。'
    if '.mainBatteryStatus.' in path and key in ('stateOfCharge','stateOfHealth','energyLevel','powerLevel'):
        definition='低压电池的等级/状态编码，不是电量、健康百分比或功率实测值；固定0/1不当作开关。'
        test='对照另一个chargeLevel与voltage字段的变化；没有更多等级值时不标定枚举。'
    if key in ('brakeFluidLevelStatus','engineCoolantLevelStatus'):
        definition='液位状态编码，本期固定3；不能据此判断正常、缺液或不适用。'
        test='查看已有保养/液位记录与报警对照，不靠固定码猜液位。'
    if key in ('airBlowerActive','cdsClimateActive','preClimateActive','defrost'):
        definition='平台空调/风机/预调节/除霜标记；本期固定false不独立证明设备关闭。'
        test='需要已知开关动作和子系统有效更新时间，不用室温相近自证开关码。'
    if key in NO_OPTION and row['status']=='varied':
        definition='此字段出现变化，与既有未选装/不适用资料冲突；需重新核对配置与权益，停止沿用固定占位假设。'
    if key in FUEL:
        definition='燃油/手动传动兼容字段，本车纯电不适用；默认值不是电机或燃油实测值。'
    if key in FUEL and row['status']=='varied':
        definition='兼容字段出现动态值；需复核对象/单位，不继续按恒定不适用解释。'
    if '.mainBatteryStatus.voltage' in path:
        definition='低压辅助电池电压；低电压与SOC=0同时出现时，先排查无效/缺省读数。'
        ev=evidence.get('aux_voltage',{})
    if key.startswith('winStatus'):
        definition='车窗状态：1打开、2关闭；与同侧位置原值非零/零交叉对照。'
        test='开闭码与位置值分开核对，位置数值单位仍需标定。'
    if key in ('drvVentSts','passVentSts'):
        definition='通风激活状态：1已激活/运行允许、2关闭；1不保证当前设定档位非零。'
        test='核对非零设定档位与状态1，保留状态1但档位0的反例。'
    if key.startswith('seatBeltStatus'):
        definition='安全带扣状态：true已扣、false未扣；不等同于座位有人。'
        test='用行程内外分布辅助；乘客/后排没有人时未扣不意味着故障。'
    if key=='dcDcConnectStatus':
        definition='充电相关连接状态：3充电连接态、1连接过渡候选、0非充电连接态；0不证明DC/DC转换器没工作。'
        test='行程中dcDcActvd为1而连接码为0，两个字段不能混同。'
    if key=='reverseLi':
        definition='倒车灯激活标记：0未激活、1激活。'
        test='与用户指定R档码1交叉对照；挂R而未采到灯亮的样本保留。'
    stage='no_data' if row['status']=='missing' else 'constant_only' if row['status']=='single_value' else 'scenario_only'
    supported=(key=='distanceToService' and ev.get('anchor_span',0)>1 and ev.get('spread',99)<=1
               or key=='tripMeter1' and ev.get('anchor_span',0)>1 and ev.get('spread',99)<=1.1
               or key=='daysToService' and ev.get('calendar_days',0)>1 and abs(ev.get('calendar_days',0)-ev.get('decrease',0))<=1
               or key=='dcChargeIAct' and ev.get('charge_negative',0)>0 and ev.get('trip_positive',0)>0 and ev.get('paired_charge',0)>0)
    if path=='parkTime.status' and ev.get('timestamp_changes',0)>2 and max(ev.get('near_power_off',0),ev.get('near_p_gear',0))>2:
        supported=True
    if key=='direction' and ev.get('paired_motion',0)>=10 and ev.get('best_offset')==0 and ev.get('median_angle_error',180)<35:
        definition='车辆航向角：0北、90东、180南、270西；顺时针，单位度。'
        supported=True
    if supported or ev.get('joint') and row['status']=='varied':stage='cross_checked'
    elif not row.get('pending',True) and stage!='no_data':stage='existing_interpretation'
    return {'stage':stage,'definition':definition,'test':test,'cross_evidence':ev,
            'method':'逐项记录；交叉对照不等同于实车确认，常量或缺样不升级为已验证。'}


def heading_profile(rows):
    errors={offset:[] for offset in (0,90,180,270)}
    for before,after in zip(rows,rows[1:]):
        a,b=before.get('_position'),after.get('_position')
        gap=after['time']-before['time']
        if not a or not b or a[2]!=b[2] or not before.get('_trusted') or not after.get('_trusted') or not 0<gap<=600000:
            continue
        if not before['states']['trip'] or not after['states']['trip']:continue
        heading=number(after,'basicVehicleStatus.direction')
        if heading is None or not 0<=heading<=360:continue
        lat1,lat2=math.radians(a[0]),math.radians(b[0]);dl=math.radians(b[1]-a[1]);dp=lat2-lat1
        hav=math.sin(dp/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dl/2)**2
        distance=6371000*2*math.asin(math.sqrt(min(1,max(0,hav))))
        if not 30<=distance<=2000 or distance/(gap/1000)*3.6>200:continue
        bearing=math.degrees(math.atan2(math.sin(dl)*math.cos(lat2),math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(dl)))%360
        for offset in errors:errors[offset].append(abs((heading+offset-bearing+180)%360-180))
    medians={str(k):round(median(v),3) for k,v in errors.items() if v}
    best=min(medians,key=medians.get) if medians else None
    return {'paired_motion':len(errors[0]),'median_angle_error':medians.get('0'),
            'best_offset':int(best) if best is not None else None,'offset_errors':medians}
