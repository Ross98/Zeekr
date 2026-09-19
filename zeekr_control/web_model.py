"""Presentation data with conservative, vehicle-specific interpretations."""
from .summary import SIDES, POSITIONS, display, number, section, updated_at
from .vehicle_state import decode
from .parameter_dictionary import definition, reference


LABELS = {
    'chargeLevel': '电量', 'distanceToEmptyOnBatteryOnly': '电池续航', 'odometer': '总里程',
    'averPowerConsumption': '平均电耗', 'indPowerConsumption': '瞬时电耗',
    'tripMeter1': '小计里程 1', 'tripMeter2': '小计里程 2', 'avgSpeed': '平均速度指标',
    'distanceToEmpty': '通用续航', 'stateOfCharge': '低压电池荷电状态', 'voltage': '低压电压',
    'energyLevel': '能量等级', 'stateOfHealth': '低压电池健康指标', 'powerLevel': '功率等级',
    'chargeSts': '充电状态', 'chargerState': '充电器工作状态', 'statusOfChargerConnection': '充电枪连接状态',
    'chargeUAct': '充电电压', 'chargeIAct': '充电电流', 'dcChargeSts': '直流充电状态',
    'dcChargeIAct': '直流充电电流', 'dcChargePileUAct': '桩侧电压', 'dcChargePileIAct': '桩侧电流',
    'timeToFullyCharged': '预计充电剩余时间', 'bookChargeSts': '预约充电状态',
    'chargeLidAcStatus': '交流慢充口盖', 'chargeLidDcAcStatus': '直流快充口盖',
    'disChargeSts': '对外放电状态', 'disChargeConnectStatus': '放电连接状态',
    'disChargeUAct': '放电电压', 'disChargeIAct': '放电电流', 'timeToTargetDisCharged': '放电剩余时间',
    'dcDcActvd': 'DC/DC 激活状态', 'dcDcConnectStatus': 'DC/DC 连接状态',
    'hvTempLevel': '高压温度等级', 'ptReady': '动力就绪状态', 'chargeHvSts': '高压充电相关状态',
    'centralLockingStatus': '中控锁', 'trunkOpenStatus': '尾门开闭', 'trunkLockStatus': '尾门锁',
    'engineHoodOpenStatus': '前舱盖', 'sunroofPos': '天窗位置', 'sunroofOpenStatus': '天窗状态',
    'curtainPos': '遮阳帘位置', 'curtainOpenStatus': '遮阳帘状态',
    'sunCurtainRearPos': '后遮阳帘位置', 'sunCurtainRearOpenStatus': '后遮阳帘状态',
    'interiorTemp': '车内温度', 'exteriorTemp': '车外温度', 'temperatureUpdateTime': '温度更新时间',
    'preClimateActive': '预调温标记', 'airBlowerActive': '鼓风机标记', 'defrost': '除霜标记',
    'climateOverHeatProActive': '过热保护相关标记', 'cabinTempReductionStatus': '座舱降温状态',
    'cdsClimateActive': '空调内部标记', 'fragActive': '香氛相关标记',
    'drvHeatSts': '主驾加热状态', 'drvHeatDetail': '主驾加热细节',
    'passHeatingSts': '副驾加热状态', 'passHeatingDetail': '副驾加热细节',
    'rlHeatingSts': '左后加热状态', 'rlHeatingDetail': '左后加热细节',
    'rrHeatingSts': '右后加热状态', 'rrHeatingDetail': '右后加热细节',
    'drvVentSts': '主驾通风状态', 'drvVentDetail': '主驾通风细节',
    'passVentSts': '副驾通风状态', 'passVentDetail': '副驾通风细节',
    'rlVentSts': '左后通风状态', 'rlVentDetail': '左后通风细节',
    'rrVentSts': '右后通风状态', 'rrVentDetail': '右后通风细节',
    'steerWhlHeatingSts': '方向盘加热', 'interiorPM25': '车内 PM2.5 指标',
    'interiorPM25Level': '车内 PM2.5 等级', 'exteriorPM25Level': '车外 PM2.5 等级', 'relHumSts': '相对湿度指标',
    'direction': '方向字段', 'speed': '车速', 'speedValidity': '车速有效性', 'engineStatus': '动力状态',
    'engineSpeed': '转速字段', 'gearAutoStatus': '自动挡位状态', 'gearManualStatus': '手动挡位状态',
    'usageMode': '使用模式', 'carMode': '车辆模式', 'daysToService': '保养剩余天数指标',
    'distanceToService': '保养剩余里程指标', 'engineHrsToService': '保养运行小时指标',
    'serviceWarningStatus': '保养提醒状态', 'brakeFluidLevelStatus': '制动液液位状态',
    'washerFluidLevelStatus': '玻璃水液位状态', 'electricParkBrakeStatus': '电子驻车',
    'srsCrashStatus': '碰撞系统状态', 'alrmSt': '报警状态', 'alrmTrgSrc': '报警来源',
    'notifForEmgyCallStatus': '紧急呼叫通知状态', 'tankFlapStatus': '油箱盖通用字段',
    'loBeam': '近光灯', 'hiBeam': '远光灯', 'frntFog': '前雾灯', 'reFog': '后雾灯', 'drl': '日行灯',
    'trunIndrLe': '左转向灯', 'trunIndrRi': '右转向灯', 'stopLi': '刹车灯', 'reverseLi': '倒车灯',
    'welcome': '迎宾灯', 'goodbye': '告别照明', 'approach': '接近照明', 'homeSafe': '伴我回家',
    'ltgShow': '灯光秀', 'flash': '闪灯字段', 'ahbc': '自动远光相关字段',
    'ahl': '灯光 AHL 字段', 'afs': '灯光 AFS 字段', 'dbl': '灯光 DBL 字段',
    'hwl': '灯光 HWL 字段', 'cornrgLi': '转弯照明字段',
    'indFuelConsumption': '瞬时油耗通用字段', 'fuelEnLevel': '燃油能量等级',
    'fuelLevelPct': '燃油比例通用字段', 'fuelEnCns': '燃油消耗通用字段',
    'fuelEnCnsFild': '燃油消耗扩展字段', 'engineCoolantLevelStatus': '冷却液通用字段',
    'propulsionType': '动力配置编码', 'fuelType': '能源配置编码',
}
for side, name in zip(SIDES, POSITIONS):
    for key, label in (('doorLockStatus', '门锁'), ('doorOpenStatus', '车门开闭'),
                       ('doorPos', '车门位置'), ('winPos', '车窗位置'), ('winStatus', '车窗状态'),
                       ('tyreStatus', '胎压'), ('tyreTemp', '胎温'), ('seatBeltStatus', '安全带标记')):
        LABELS[key + side] = name + label
LABELS.update({'seatBeltStatusMidRear': '后排中间安全带标记',
               'seatBeltStatusThDriverRear': '第三排左侧通用安全带标记',
               'seatBeltStatusThPassengerRear': '第三排右侧通用安全带标记'})

GROUPS = {'electricVehicleStatus': '能源与充电', 'maintenanceStatus': '保养与轮胎',
          'climateStatus': '空调与舒适', 'drivingSafetyStatus': '门锁与安全',
          'runningStatus': '行驶与灯光', 'pollutionStatus': '空气质量',
          'drivingBehaviourStatus': '行驶指标', 'configuration': '平台配置',
          'trailerStatus': '拖车通用字段', 'temStatus': '通信模块',
          'vehicleAlarm': '报警', 'theftNotification': '防盗通知', 'notification': '通知'}


def scalar(value):
    if value is None:
        return '未知'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)) or (isinstance(value, str) and number(value) is not None):
        return display(value)
    return str(value)[:120] if isinstance(value, str) else '未知'


def fields_for(data):
    """Only documented scalar names are exposed; unknown identities stay server-side."""
    result = []
    state = decode(section(data))

    def walk(value, path='', group='其他参数'):
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            full = path + '.' + key if path else key
            current = '低压电池' if key == 'mainBatteryStatus' else GROUPS.get(key, group)
            if key == 'position':
                current = '定位状态'
            elif key == 'backupBattery':
                current = '通信模块备用电池'
            if isinstance(item, dict):
                walk(item, full, current)
            elif definition(full):
                entry = definition(full)
                rendered, evidence = scalar(item), '待核实'
                numeric = number(item)
                calibrated = None
                if path == 'additionalVehicleStatus.electricVehicleStatus':
                    if key == 'chargeLidAcStatus' and numeric in (1, 2):
                        calibrated = ('打开' if numeric == 1 else '关闭', '本车场景观察')
                    elif key == 'chargeLidDcAcStatus' and numeric in (1, 2):
                        calibrated = ('打开' if numeric == 1 else '关闭', '本车场景观察')
                    elif key in ('dcChargePileUAct', 'dcChargePileIAct'):
                        unit, minimum, maximum = (' V', 0, 1500) if key.endswith('UAct') else (' A', -2000, 2000)
                        calibrated = (display(item, unit, minimum, maximum), '本车已核对')
                    elif key == 'timeToFullyCharged' and numeric != 2047:
                        calibrated = (display(item, ' 分钟', 0, 2046) if state['charging'] is True else '未知', '本车已核对')
                elif path == 'additionalVehicleStatus.drivingSafetyStatus':
                    locked = number(value.get('centralLockingStatus')) == 2 and all(
                        number(value.get('doorLockStatus' + side)) == 1 for side in SIDES)
                    if locked and key in ['centralLockingStatus'] + ['doorLockStatus' + side for side in SIDES]:
                        calibrated = ('已锁车' if key == 'centralLockingStatus' else '已锁', '本车已核对（组合）')
                    elif numeric == 0 and key in ['trunkOpenStatus'] + ['doorOpenStatus' + side for side in SIDES]:
                        calibrated = ('关闭', '本车已核对')
                    elif key == 'electricParkBrakeStatus' and numeric in (0, 1):
                        calibrated = ('行驶样本值 0' if numeric == 0 else '停车／充电样本值 1', '本车场景观察')
                elif path == 'additionalVehicleStatus.climateStatus':
                    if numeric == 0 and key in ['winPos' + side for side in SIDES]:
                        calibrated = ('关闭', '本车已核对')
                elif path == 'additionalVehicleStatus.drivingBehaviourStatus':
                    if key == 'gearAutoStatus' and numeric == 3:
                        calibrated = ('D 挡（挂 D 时观察到）', '本车场景观察')
                elif path == 'basicVehicleStatus':
                    if key == 'engineStatus' and item in ('engine_running', 'engine_off'):
                        calibrated = ('动力运行' if item == 'engine_running' else '动力关闭', '本车场景观察')
                    elif key == 'speed':
                        calibrated = (display(state['speed'], ' km/h', 0, 400), '已返回（有效车速）')
                    elif key == 'speedValidity' and (isinstance(item, bool) or item in ('true', 'false')):
                        calibrated = ('有效' if item is True or item == 'true' else '无效', '已返回')
                    elif key == 'usageMode' and numeric in (1, 2, 13):
                        calibrated = ({1: '到达锁车样本值 1', 2: '直流充电样本值 2', 13: '行驶样本值 13'}[numeric], '本车场景观察')
                if calibrated is not None:
                    rendered, evidence = calibrated
                elif key in ('timeToFullyCharged', 'timeToTargetDisCharged') and number(item) == 2047:
                    rendered, evidence = '暂无有效时间估计', '社区解释'
                elif key == 'temperatureUpdateTime':
                    rendered, evidence = updated_at(item), '已返回'
                elif key.startswith('tyreStatus'):
                    rendered, evidence = display(item, ' kPa', 0), '本车已核对'
                elif key.startswith('tyreTemp'):
                    rendered, evidence = display(item, '°C', -80, 150), '本车已核对'
                elif key in ('interiorTemp', 'exteriorTemp'):
                    rendered, evidence = display(item, '°C', -80, 100), '已返回'
                elif key == 'chargeLevel' and current == '能源与充电':
                    rendered, evidence = display(item, '%', 0, 100), '已返回'
                elif key in ('odometer', 'distanceToEmptyOnBatteryOnly'):
                    rendered, evidence = display(item, ' km', 0), '已返回'
                if rendered == '未知':
                    evidence = '未知'
                result.append({'key': key, 'path': full, 'name': entry['name'], 'group': current,
                               'raw': scalar(item), 'value': rendered, 'evidence': evidence,
                               'reference': reference(entry)})
    walk(section(data))
    return result


def timestamp(value):
    return int(number(value, 0)) if updated_at(value) != '未知' else None


def metric_detail(value, unit, time, minimum=None, maximum=None):
    valid = number(value, minimum, maximum)
    if valid is not None and abs(valid) > 1e12:
        valid = None
    return {'value': float(valid) if valid is not None else None, 'unit': unit,
            'updated_time': time, 'evidence': '已返回' if valid is not None else '未知'}


def metadata_fields(vehicle):
    """Expose only known non-sensitive vehicle metadata under a separate namespace."""
    result = []

    def walk(value, path='vehicleMetadata'):
        for key, item in section(value).items():
            full = path + '.' + key
            if isinstance(item, dict):
                walk(item, full)
            else:
                entry = definition(full)
                if entry:
                    raw = scalar(item) if item != '' else '未知'
                    result.append({'key': key, 'path': full, 'name': entry['name'], 'group': '车辆档案',
                                   'raw': raw, 'value': raw, 'evidence': '未知' if raw == '未知' else '待核实',
                                   'reference': reference(entry)})
    walk(vehicle)
    return result


def build_model(data, vehicle=None):
    data = section(data)
    extra = section(data.get('additionalVehicleStatus'))
    electric = section(extra.get('electricVehicleStatus'))
    maintenance = section(extra.get('maintenanceStatus'))
    climate = section(extra.get('climateStatus'))
    safety = section(extra.get('drivingSafetyStatus'))
    locked = number(safety.get('centralLockingStatus')) == 2 and all(
        number(safety.get('doorLockStatus' + side)) == 1 for side in SIDES)
    door_states = ['关闭' if number(safety.get('doorOpenStatus' + side)) == 0 else '未知' for side in SIDES]
    window_states = ['关闭' if number(climate.get('winPos' + side)) == 0 else '未知' for side in SIDES]
    def closure(states):
        known = states.count('关闭')
        return '关闭' if known == len(states) else '已知关闭 %d 项，%d 项未知' % (known, len(states) - known) if known else '未知'
    vehicle_state = decode(data)
    charging = vehicle_state['charging']
    stopped = vehicle_state['charging_phase'] == 'stopped'
    dc_charging = charging is True and vehicle_state['charging_mode'] == 'dc'
    ac_charging = charging is True and vehicle_state['charging_mode'] == 'ac'
    remaining = number(electric.get('timeToFullyCharged'), 0, 2046)
    remaining_time = ('暂无有效时间估计' if number(electric.get('timeToFullyCharged')) == 2047
                      else display(electric.get('timeToFullyCharged'), ' 分钟') if charging is True and remaining is not None else '未知')
    status_time = timestamp(data.get('updateTime'))
    temperature_time = timestamp(climate.get('temperatureUpdateTime'))
    return {
        'updated_time': status_time, 'temperature_updated_time': temperature_time,
        'metric_details': {
            'battery': metric_detail(electric.get('chargeLevel'), '%', status_time, 0, 100),
            'range': metric_detail(electric.get('distanceToEmptyOnBatteryOnly'), 'km', status_time, 0),
            'odometer': metric_detail(maintenance.get('odometer'), 'km', status_time, 0),
            'inside': metric_detail(climate.get('interiorTemp'), '°C', temperature_time, -80, 100),
            'outside': metric_detail(climate.get('exteriorTemp'), '°C', temperature_time, -80, 100)},
        'closure': {'doors': closure(door_states),
                    'windows': closure(window_states),
                    'trunk': '关闭' if number(safety.get('trunkOpenStatus')) == 0 else '未知'},
        'updated_at': updated_at(data.get('updateTime')),
        'temperature_updated_at': updated_at(climate.get('temperatureUpdateTime')),
        'metrics': {'battery': display(electric.get('chargeLevel'), '%', 0, 100),
                    'range': display(electric.get('distanceToEmptyOnBatteryOnly'), ' km', 0),
                    'odometer': display(maintenance.get('odometer'), ' km', 0, grouped=True),
                    'inside': display(climate.get('interiorTemp'), '°C', -80, 100),
                    'outside': display(climate.get('exteriorTemp'), '°C', -80, 100)},
        'lock': {'value': '已锁车' if locked else '未知', 'confirmed': locked},
        'charging': {'value': '充电已停止' if stopped else '直流充电中' if dc_charging else '交流充电中' if ac_charging else '充电中' if charging is True else '未充电' if charging is False else '未知',
                     'confirmed': charging is not None, 'mode': vehicle_state['charging_mode'],
                     'remaining_time': remaining_time,
                     'work_state': '已停止' if stopped else '工作中' if charging is True else '空闲' if charging is False else '未知',
                     'connection_state': '接口未提供有效连接判断',
                     'detail': '匹配本车已观察的直流停止组合；不能仅据此判断停止原因或是否已拔枪。' if stopped else '直流口盖、充电状态与桩侧电压电流组合已核对；通用零值不代表未充电。' if dc_charging else
                               '匹配本车交流充电实测组合，电压电流已对照本车App；连接码不单独解释。' if ac_charging else
                               '匹配充电证据；数据来自车辆云端缓存。' if charging is True else
                               '匹配未充电证据，已排除充电冲突；连接码不单独解释。' if charging is False else
                               '证据缺失或冲突，暂无法确认是否正在充电。'},
        'doors': [{'name': name, 'door': door_states[index],
                   'lock': '已锁' if locked else '未知', 'window': window_states[index],
                   'raw': {'door': scalar(safety.get('doorOpenStatus' + side)),
                           'lock': scalar(safety.get('doorLockStatus' + side)),
                           'window': scalar(climate.get('winPos' + side))}}
                  for index, (side, name) in enumerate(zip(SIDES, POSITIONS))],
        'trunk': '关闭' if number(safety.get('trunkOpenStatus')) == 0 else '未知',
        'hood': '未知',
        'tyres': [{'name': name, 'pressure': display(maintenance.get('tyreStatus' + side), ' kPa', 0),
                   'pressure_value': metric_detail(maintenance.get('tyreStatus' + side), 'kPa', status_time, 0)['value'],
                   'temperature': display(maintenance.get('tyreTemp' + side), '°C', -80, 150)}
                  for side, name in zip(SIDES, POSITIONS)],
        'fields': fields_for(data) + metadata_fields(vehicle),
    }


def boolean(value):
    """GW2 uses both JSON booleans and literal true/false strings; other enums stay unknown."""
    if type(value) is bool:
        return value
    if isinstance(value, str) and value.lower() in ('true', 'false'):
        return value.lower() == 'true'
    return None


def parse_location(data):
    data = section(data)
    # GW2 places position on the status envelope; some responses nest under basic status.
    position = section(data.get('position')) or section(section(data.get('basicVehicleStatus')).get('position'))
    latitude, longitude = number(position.get('latitude')), number(position.get('longitude'))
    valid = latitude is not None and longitude is not None
    if valid:
        # Do not silently reinterpret degree values as the observed integer format.
        valid = (latitude == latitude.to_integral_value() and longitude == longitude.to_integral_value()
                 and not (-90 <= latitude <= 90 and -180 <= longitude <= 180))
    if valid:
        latitude, longitude = latitude / 3600000, longitude / 3600000
        valid = -90 <= latitude <= 90 and -180 <= longitude <= 180 and (latitude != 0 or longitude != 0)
    system = boolean(position.get('marsCoordinates'))
    # GCJ-02 is retained but not plotted on the WGS84 base map without a verified transform.
    return {'valid': bool(valid), 'plottable': bool(valid and system is False),
            'latitude': float(latitude) if valid else None, 'longitude': float(longitude) if valid else None,
            'raw_latitude': str(position.get('latitude')) if valid else None,
            'raw_longitude': str(position.get('longitude')) if valid else None,
            'trusted': boolean(position.get('posCanBeTrusted')) is True, 'gps_time': None,
            'coordinate_system': 'WGS84（社区解释）' if system is False else 'GCJ-02（社区解释）' if system is True else '未知',
            'transform': '原始整数 / 3600000；坐标系按社区解释，尚待地图对齐核验',
            'updated_at': updated_at(data.get('updateTime'))}
