"""Explicit, numeric-only charging projection for current and saved observations."""
import math


# key, label, unit, group. Unknown enums are observations, never interpretations.
PARAMETERS = (
    ('chargeLevel', '动力电池 SOC', '%', '电量与续航'),
    ('distanceToEmptyOnBatteryOnly', '电池剩余续航', 'km', '电量与续航'),
    ('timeToFullyCharged', '预计充电剩余时间', '分钟', '电量与续航'),
    ('chargeUAct', '充电电压', 'V', '电压与电流'),
    ('chargeIAct', '充电电流', 'A', '电压与电流'),
    ('dcChargePileUAct', '直流桩侧电压', 'V', '电压与电流'),
    ('dcChargePileIAct', '直流桩侧电流', 'A', '电压与电流'),
    ('dcChargeIAct', '直流充电电流', 'A', '电压与电流'),
    ('chargeSts', '充电状态码', '', '状态与连接'),
    ('chargerState', '充电器工作状态码', '', '状态与连接'),
    ('statusOfChargerConnection', '充电枪连接状态码', '', '状态与连接'),
    ('dcChargeSts', '直流充电状态码', '', '状态与连接'),
    ('chargeHvSts', '高压充电相关状态码', '', '高压与供电'),
    ('hvTempLevel', '高压系统温度等级', '', '高压与供电'),
    ('ptReady', '动力系统就绪状态码', '', '高压与供电'),
    ('dcDcActvd', 'DC/DC 激活状态码', '', '高压与供电'),
    ('dcDcConnectStatus', 'DC/DC 连接状态码', '', '高压与供电'),
    ('chargeLidAcStatus', '交流慢充口盖', '', '充电口与预约'),
    ('chargeLidDcAcStatus', '直流快充口盖', '', '充电口与预约'),
    ('bookChargeSts', '预约充电状态码', '', '充电口与预约'),
    ('disChargeSts', '对外放电状态码', '', '对外放电'),
    ('disChargeConnectStatus', '放电连接状态码', '', '对外放电'),
    ('disChargeUAct', '放电电压', 'V', '对外放电'),
    ('disChargeIAct', '放电电流', 'A', '对外放电'),
    ('timeToTargetDisCharged', '放电剩余时间原值', '', '对外放电'),
    ('averPowerConsumption', '平均电耗原值', '', '其他能源参数'),
    ('indPowerConsumption', '瞬时电能消耗指标原值', '', '其他能源参数'),
)
METRICS = ('sampled_peak_kw', 'average_power_kw', 'power_sample_count',
           'power_covered_seconds', 'power_coverage', 'charging_time_covered_seconds',
           'charging_time_coverage', 'max_state_gap_seconds', 'max_observed_gap_seconds',
           'stop_detection_state_gap_seconds', 'stop_detection_observed_gap_seconds',
           'tail_power_drop_percent', 'range_delta_km')


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def capture_parameters(extra, electric):
    """Persist only listed numeric scalars; no raw payload, strings or identifiers."""
    from .vehicle_state import numeric
    return {key: numeric((extra if key == 'chargeHvSts' else electric).get(key), -1e9, 1e9)
            for key, _, _, _ in PARAMETERS}


def snapshot_details(snapshot):
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    saved = snapshot.get('charging_parameters')
    saved = saved if isinstance(saved, dict) else {}
    fallback = {'chargeLevel': snapshot.get('soc'),
                'distanceToEmptyOnBatteryOnly': snapshot.get('range_km'),
                'timeToFullyCharged': snapshot.get('remaining_minutes')}
    for key, metric in (('chargeUAct', 'ac_voltage'), ('chargeIAct', 'ac_current'),
                        ('dcChargePileUAct', 'voltage'), ('dcChargePileIAct', 'current')):
        value = snapshot.get(metric)
        if isinstance(value, dict) and value.get('validity') == 'valid':
            fallback[key] = value.get('value')
    rows = []
    for key, label, unit, group in PARAMETERS:
        value = number(saved.get(key, fallback.get(key)))
        note = '' if unit else '原始状态码，含义未确认'
        if key == 'timeToFullyCharged':
            if snapshot.get('charging') is not True or value is None or not 0 <= value <= 2046:
                value, note = None, '仅充电中且有效时展示；2047 不代表剩余时间'
        elif key in ('chargeLidAcStatus', 'chargeLidDcAcStatus'):
            note = {1: '已打开', 2: '已关闭'}.get(value, '原始状态码，含义未确认')
        elif key in ('averPowerConsumption', 'indPowerConsumption', 'timeToTargetDisCharged'):
            note = '单位或有效性未核验，不作充电功率或剩余时间使用'
        rows.append({'key': key, 'label': label, 'unit': unit, 'group': group,
                     'value': value, 'note': note})
    return {'state_time': number(snapshot.get('state_time')),
            'observed_at': number(snapshot.get('observed_at')),
            'charging': snapshot.get('charging') if type(snapshot.get('charging')) is bool else None,
            'mode': snapshot.get('charging_mode') if snapshot.get('charging_mode') in ('ac', 'dc') else None,
            'power_kw': number(snapshot.get('power_kw')),
            'power_source': snapshot.get('power_source') if snapshot.get('power_source') in ('ac_ui', 'dc_pile_ui') else None,
            'parameters': rows}


def history_details(report):
    if not isinstance(report, dict) or report.get('schema_version') != 2:
        return None
    if not all(isinstance(report.get(key), dict) for key in ('start', 'end')):
        return None
    metrics = report.get('metrics')
    metrics = metrics if isinstance(metrics, dict) else {}
    return {'start': snapshot_details(report['start']), 'end': snapshot_details(report['end']),
            'metrics': {key: number(metrics.get(key)) for key in METRICS}}
