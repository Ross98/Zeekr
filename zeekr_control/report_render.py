"""Readable WeCom summaries; detailed evidence remains in the saved report."""
from datetime import datetime
from zoneinfo import ZoneInfo
import re
from .start_evidence import project as project_start
from .notification_location import reference_suffix
from .usage_events import number

TARGET_BYTES = 1900
HARD_BYTES = 2048


def clean_text(value, limit=100):
    text = re.sub(r'[\x00-\x1f\x7f]+', ' ', str(value or ''))
    return re.sub(r'\s+', ' ', text).strip()[:limit]


def _time(value):
    if value is None:
        return '未知'
    return datetime.fromtimestamp(value / 1000, ZoneInfo('Asia/Shanghai')).strftime('%m月%d日 %H:%M')


def _num(value, digits=1):
    if value is None:
        return '未知'
    rendered = '%.*f' % (digits, value)
    return rendered.rstrip('0').rstrip('.') if digits else rendered


def _range(start, end):
    if start is None or end is None:
        return '%s—%s' % (_time(start), _time(end))
    left = datetime.fromtimestamp(start/1000, ZoneInfo('Asia/Shanghai'))
    right = datetime.fromtimestamp(end/1000, ZoneInfo('Asia/Shanghai'))
    if left.date() == right.date():
        return left.strftime('%m月%d日 %H:%M—') + right.strftime('%H:%M')
    pattern = '%Y年%m月%d日 %H:%M' if left.year != right.year else '%m月%d日 %H:%M'
    return left.strftime(pattern) + '—' + right.strftime(pattern)


def _place(value, reference=None):
    text = clean_text(value)
    if not text:
        return '位置未知'
    return (text if text.endswith('附近') else text+'附近') + reference_suffix(reference)


def _start_note(report):
    evidence = project_start(report.get('start_evidence'))
    if evidence['basis'] == 'bounded':
        return '开始时间为相邻观测范围：' + _range(evidence['earliest_time'], evidence['latest_time'])
    return '实际开始时间未知；以上从首次观测起记录。'


def _parking(report):
    snapshot = report.get('parking') or report.get('end') or {}
    attention = report.get('attention') or {}
    stamp = snapshot.get('state_time')
    now = report.get('event_created_at', attention.get('reference_time'))
    if (attention.get('fresh') is not True or number(stamp, 1, 32503680000000) is None
            or number(now, 1, 32503680000000) is None or not -30000 <= now-stamp <= 180000):
        return []
    closures = snapshot.get('closures') or {}
    confirmed = []
    if snapshot.get('locked') is True:
        confirmed.append('已锁车')
    if (closures.get('doors') == ['closed']*4 and closures.get('windows') == ['closed']*4
            and snapshot.get('trunk') == 'closed'):
        confirmed.append('四门、四窗、尾门已关闭')
    return ['', '【停车状态】', ' · '.join(confirmed)] if confirmed else []


def _status_alerts(report, include_cover=True):
    attention = report.get('attention') or {}
    if attention.get('fresh') is not True:
        return []
    pending = set(attention.get('pending_capabilities', []))
    current = report.get('parking') or report.get('end') or {}
    items = []
    for item in attention.get('items', []):
        if item.get('key') in pending:
            continue
        verified = item.get('level') in ('warning', 'critical')
        if include_cover and item.get('level') == 'status' and item.get('key') == 'dc_lid':
            verified = current.get('dc_lid') == 'open' and current.get('charging') is False
        text = clean_text(item.get('text'))
        if verified and text:
            items.append(text)
    return ['', '【需留意】'] + list(dict.fromkeys(items)) if items else []


def _fit(blocks, target):
    """Drop whole optional blocks, never cut a negation or reference suffix."""
    omitted = []
    def assemble():
        return '\n'.join(line for _, lines in blocks for line in lines)
    text = assemble()
    for key in ('parking', 'location'):
        if len(text.encode()) <= min(target, HARD_BYTES):
            break
        if any(name == key and lines for name, lines in blocks):
            blocks = [(name, lines) for name, lines in blocks if name != key]
            omitted.append(key)
            text = assemble()
    if len(text.encode()) > HARD_BYTES:
        raise ValueError('报告核心模板超过2048字节')
    return text, omitted


def render(kind, report, event_id, address=None, target=TARGET_BYTES, references=None):
    titles = {'trip_start':'🚗 行程开始', 'trip_end':'🚗 行程结束',
              'charge_start':'⚡ 开始充电', 'charge_end':'🔋 充电已停止'}
    if kind not in titles:
        raise ValueError('未知通知类型')
    m = report.get('metrics') or {}
    start, end = report.get('start') or {}, report.get('end') or {}
    partial = report.get('partial') or m.get('partial')
    starting = kind.endswith('_start')
    trip = kind.startswith('trip_')
    address, references = address or {}, references or {}
    duration = number(m.get('duration_seconds'), 0, 366*86400)
    title = titles[kind] + ('｜部分记录' if partial else '')
    if not starting:
        distance = number(m.get('distance_km'))
        headline = ('%s 公里 · ' % _num(distance) if trip else '')
        title += '｜' + headline + '%s 分钟' % _num(duration/60 if duration is not None else None, 0)
    core = [title, ('首次观测：'+_time(report.get('start_time')) if starting else
                    '记录区间：'+_range(report.get('start_time'), report.get('end_time')))]
    location = ['出发地：'+_place(address.get('start'), references.get('start'))] if trip else [
        '充电地点：'+_place(address.get('start'), references.get('start'))]
    if kind == 'trip_end':
        location.append('到达地：'+_place(address.get('end'), references.get('end')))
    if not starting:
        core += ['', '【电量与能耗】' if trip else '【充电概况】']
    a, b = number(start.get('soc'), 0, 100), number(end.get('soc'), 0, 100)
    core.append('当前电量：%s%%' % _num(a) if starting else
                '电量：%s%% → %s%%' % (_num(a), _num(b)))
    if not starting and a is not None and b is not None:
        change = b-a
        core[-1] += '（%s%s 个百分点）' % ('增加 ' if change >= 0 else '消耗 ', _num(abs(change)))
    if not trip:
        core.append('充电方式：'+{'dc':'直流快充', 'ac':'交流充电'}.get(start.get('charging_mode'), '未确认'))
    if starting and trip:
        remaining = number(start.get('range_km'))
        if remaining is not None:
            core.append('云端续航：%s km' % _num(remaining))
    if not starting:
        energy = number(m.get('estimated_kwh'))
        core.append(('估算耗电：约 ' if trip else '估算充入：约') + _num(energy) + ' kWh'
                    if energy is not None else ('估算耗电' if trip else '估算充入')+'：未知（观测条件不足）')
        rate = number(m.get('estimated_kwh_100km'))
        if trip and rate is not None:
            core.append('估算百公里耗电：约 %s kWh/100km' % _num(rate))
        if trip and m.get('charge_overlap'):
            core.append('途中有充电，电量变化不用于驾驶耗电统计。')
    alerts = _status_alerts(report, include_cover=trip)
    notes = []
    if partial:
        notes.append('部分记录：以上仅汇总已观测区间。')
    notes.append(_start_note(report))
    notes.append('云端观测，可能延迟。' + ('' if starting else
                 ('耗电' if trip else '充入电量')+'按 SOC × 容量估算，非电表计量。'))
    return _fit([('heading', core[:2]), ('location', location), ('metrics', core[2:]),
                 ('parking', _parking(report) if kind == 'trip_end' else []),
                 ('alerts', alerts), ('notes', notes)], target)
