"""Complete, allowlisted parameter view of one cached vehicle snapshot."""
import json
import math

from .parameter_dictionary import FIELDS
from .summary import number


GROUPS = ('门窗与安全', '轮胎与保养', '空调与座舱', '座椅与方向盘', '空气质量',
          '能源与充放电', '低压电池', '基础车况与行驶', '灯光', '报警与通知',
          '定位状态', '通信与备用电池', '车辆档案', '平台配置与其他')
MISSING = object()


def group_for(path):
    key = path.rsplit('.', 1)[-1]
    if path.startswith('vehicleMetadata.'):
        return '车辆档案'
    if '.mainBatteryStatus.' in path:
        return '低压电池'
    if '.position.' in path:
        return '定位状态'
    if path.startswith('temStatus.'):
        return '通信与备用电池'
    if any(part in path for part in ('vehicleAlarm.', 'theftNotification.', 'notification.')):
        return '报警与通知'
    for part, group in (('electricVehicleStatus.', '能源与充放电'), ('maintenanceStatus.', '轮胎与保养'),
                        ('runningStatus.', '灯光'), ('pollutionStatus.', '空气质量'),
                        ('drivingSafetyStatus.', '门窗与安全')):
        if part in path:
            return group
    if 'climateStatus.' in path:
        if key.startswith(('winPos', 'winStatus')) or any(word in key.lower() for word in ('sunroof', 'curtain')):
            return '门窗与安全'
        if key.startswith(('drv', 'pass', 'rl', 'rr', 'steerWhl')):
            return '座椅与方向盘'
        return '空调与座舱'
    if path.startswith('basicVehicleStatus.') or 'drivingBehaviourStatus.' in path:
        return '基础车况与行驶'
    return '平台配置与其他'


def lookup(raw, path):
    current = raw
    for key in path.split('.'):
        if not isinstance(current, dict) or key not in current:
            return MISSING
        current = current[key]
    return current


def raw_text(value):
    if value is MISSING:
        return '—'
    if isinstance(value, (dict, list)):
        return '[非标量值]'
    if isinstance(value, float) and not math.isfinite(value):
        return '[无效数值]'
    if isinstance(value, str):
        value = value[:120]
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def parameters(raw, model):
    """Never return raw containers, undocumented identities or private paths."""
    model = model or {}
    observed = {f['path']: f for f in model.get('fields', [])}
    rows = []
    counts = dict.fromkeys(('known', 'pending', 'empty', 'invalid', 'missing'), 0)
    for path, entry in FIELDS.items():
        if entry['private']:
            continue
        field = observed.get(path)
        metadata = path.startswith('vehicleMetadata.')
        value = field.get('raw', MISSING) if metadata and field else lookup(raw, path)
        rendered = field.get('value', '未知') if field else '未知'
        evidence = field.get('evidence', '待核实') if field else '待核实'
        if value is MISSING:
            status, display, evidence = 'missing', '本次未返回', '本次未返回'
        elif value is None or metadata and field and field.get('raw_json') == 'null':
            status, display, evidence = 'empty', '暂无数据', '返回空值'
        elif (isinstance(value, (dict, list)) or value == '' or
              isinstance(value, float) and not math.isfinite(value) or
              entry['kind'] == 'number' and number(value) is None or
              rendered == '未知'):
            status, display, evidence = 'invalid', '暂无有效值', '无效或无法解释的值'
        elif evidence in ('待核实', '未知'):
            status, display = 'pending', '含义待核实'
        else:
            status, display = 'known', rendered
        updated_time, time_source = model.get('updated_time'), '整车快照'
        if metadata:
            updated_time, time_source = None, '档案更新时间未提供'
        elif path.rsplit('.', 1)[-1] in ('interiorTemp', 'exteriorTemp', 'temperatureUpdateTime'):
            updated_time, time_source = model.get('temperature_updated_time'), '温度状态'
        elif 'pollutionStatus.' in path:
            time_source = '整车快照；独立更新时间未提供'
        if status == 'missing':
            updated_time, time_source = None, '本次未返回'
        rows.append({'path': path, 'name': entry['name'], 'group': group_for(path),
                     'value': str(display)[:160],
                     'raw': field.get('raw_json', raw_text(value)) if metadata and field else raw_text(value),
                     'status': status, 'evidence': evidence, 'unit': entry['unit'],
                     'note': entry['note'], 'basis': entry['basis'],
                     'updated_time': updated_time, 'time_source': time_source})
        counts[status] += 1
    counts.update(total=len(rows), returned=len(rows) - counts['missing'])
    return {'fields': rows, 'counts': counts, 'has_snapshot': raw is not None,
            'updated_time': model.get('updated_time'),
            'groups': [{'name': group, 'count': sum(row['group'] == group for row in rows)} for group in GROUPS]}
