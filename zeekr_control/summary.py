"""Conservative display of observed GW2 fields, without guessing enum meanings."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo


def section(value):
    return value if isinstance(value, dict) else {}


def number(value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            return None
        if minimum is not None and result < minimum:
            return None
        if maximum is not None and result > maximum:
            return None
        return result
    except InvalidOperation:
        return None


def display(value, unit='', minimum=None, maximum=None, grouped=False):
    result = number(value, minimum, maximum)
    if result is None:
        return '未知'
    # Avoid unbounded exponent formatting and meaningless excess precision.
    if abs(result) > Decimal('1e12'):
        return '未知'
    formatted = format(result, ',.3f' if grouped else '.3f').rstrip('0').rstrip('.')
    return formatted + unit


FIELD_LABELS = {
    'chargeSts': '充电状态',
    'chargerState': '充电器工作状态',
    'statusOfChargerConnection': '充电枪连接状态',
    'centralLockingStatus': '中控锁状态',
    'trunkOpenStatus': '尾门开闭状态',
}
for suffix, position in zip(('Driver', 'Passenger', 'DriverRear', 'PassengerRear'),
                            ('左前', '右前', '左后', '右后')):
    FIELD_LABELS['doorLockStatus' + suffix] = position + '门锁状态'
    FIELD_LABELS['doorOpenStatus' + suffix] = position + '门开闭状态'
    FIELD_LABELS['winPos' + suffix] = position + '车窗位置'


def raw_fields(data, fields):
    items = []
    for key in fields:
        value = data.get(key)
        if number(value) is not None:
            rendered = display(value)
            if rendered != '未知':
                items.append(FIELD_LABELS.get(key, key) + '=' + rendered)
    return '、'.join(items) + '（原始状态值，含义待核对）' if items else '未知'


def updated_at(value):
    milliseconds = number(value, 0)
    if milliseconds is None:
        return '未知'
    try:
        return datetime.fromtimestamp(float(milliseconds / 1000), ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S') + '（北京时间）'
    except (ValueError, OverflowError, OSError):
        return '未知'


SIDES = ('Driver', 'Passenger', 'DriverRear', 'PassengerRear')
POSITIONS = ('左前', '右前', '左后', '右后')


def confirmed_state(data, expected, label):
    """Only translate the complete combination confirmed by this vehicle's owner."""
    if all(number(data.get(key)) == value for key, value in expected.items()):
        return label + '（本车已核对，缓存）'
    raw = raw_fields(data, expected)
    return '未知' if raw == '未知' else '未知；' + raw


def charging_details(electric):
    fields = ('chargeSts', 'chargerState', 'statusOfChargerConnection')
    confirmed = all(number(electric.get(key)) == 0 for key in fields)
    lines = [confirmed_state(electric, dict.fromkeys(fields, 0), '未充电')]
    for key in fields:
        value = display(electric.get(key))
        if key == 'chargeSts' and confirmed:
            value = '未充电（组合已核对）'
        elif value != '未知':
            value += '（原值，含义待核对）'
        lines.append('  ' + FIELD_LABELS[key] + '：' + value)
    return '\n'.join(lines)


def tyre_pressures(maintenance):
    # Owner's official-app screenshot confirms kPa and wheel positions.
    # Keep API decimals; one screenshot cannot establish the app's rounding rule.
    return '、'.join(label + ' ' + display(maintenance.get('tyreStatus' + side), ' kPa', 0)
                   for label, side in zip(('左前', '右前', '左后', '右后'), SIDES))


def format_status(data):
    data = section(data)
    extra = section(data.get('additionalVehicleStatus'))
    electric = section(extra.get('electricVehicleStatus'))
    maintenance = section(extra.get('maintenanceStatus'))
    climate = section(extra.get('climateStatus'))
    safety = section(extra.get('drivingSafetyStatus'))
    lines = [
        '车辆状态（GW2 缓存，可能延迟）',
        '更新时间：' + updated_at(data.get('updateTime')),
        '动力电池：' + display(electric.get('chargeLevel'), '%', 0, 100),
        '电池续航：' + display(electric.get('distanceToEmptyOnBatteryOnly'), ' km', 0),
        '总里程：' + display(maintenance.get('odometer'), ' km', 0, grouped=True),
        '车内温度：' + display(climate.get('interiorTemp'), '°C', -80, 100),
        '车外温度：' + display(climate.get('exteriorTemp'), '°C', -80, 100),
        '充电：' + charging_details(electric),
        '门锁：' + confirmed_state(safety, {'centralLockingStatus': 2, **{'doorLockStatus' + side: 1 for side in SIDES}}, '中控锁已锁、' + '、'.join(position + '门已锁' for position in POSITIONS)),
        '车门：' + confirmed_state(safety, {'doorOpenStatus' + side: 0 for side in SIDES}, '、'.join(position + '门关闭' for position in POSITIONS)),
        '尾门：' + confirmed_state(safety, {'trunkOpenStatus': 0}, '关闭'),
        '车窗：' + confirmed_state(climate, {'winPos' + side: 0 for side in SIDES}, '、'.join(position + '窗关闭' for position in POSITIONS)),
        '胎压：' + tyre_pressures(maintenance),
    ]
    return '\n'.join(lines)
