"""Stable v2 Chinese text rendering with a measured UTF-8 budget."""
from datetime import datetime
from zoneinfo import ZoneInfo
import re
from .start_evidence import project as project_start
from .notification_location import reference_suffix

TARGET_BYTES = 1900
HARD_BYTES = 2048


def clean_text(value, limit=100):
    text = re.sub(r'[\x00-\x1f\x7f]+', ' ', str(value or ''))
    return re.sub(r'\s+', ' ', text).strip()[:limit]


def _time(value, full=False):
    if value is None:
        return '未知'
    dt = datetime.fromtimestamp(value / 1000, ZoneInfo('Asia/Shanghai'))
    return dt.strftime('%Y年%m月%d日 %H:%M' if full else '%m月%d日 %H:%M')


def _num(value, digits=1):
    if value is None:
        return '未知'
    rendered = '%.*f' % (digits, value)
    return rendered.rstrip('0').rstrip('.') if digits else rendered


def _range(start, end):
    if start is None or end is None: return '%s—%s' % (_time(start), _time(end))
    left=datetime.fromtimestamp(start/1000,ZoneInfo('Asia/Shanghai')); right=datetime.fromtimestamp(end/1000,ZoneInfo('Asia/Shanghai'))
    if left.date()==right.date(): return left.strftime('%m月%d日 %H:%M—')+right.strftime('%H:%M')
    pattern='%Y年%m月%d日 %H:%M' if left.year!=right.year else '%m月%d日 %H:%M'
    return left.strftime(pattern)+'—'+right.strftime(pattern)


def _place(value, reference=None):
    text=clean_text(value,100)
    if not text: return '位置未知'
    return (text if text.endswith('附近') else text+'附近') + reference_suffix(reference)


def _start_timing(report):
    value = project_start(report.get('start_evidence'))
    def clock(stamp):
        return datetime.fromtimestamp(stamp/1000, ZoneInfo('Asia/Shanghai')).strftime('%m月%d日 %H:%M:%S')
    if value['basis'] == 'legacy':
        return ['起点证据未保存，实际开始时间未知。']
    lines = (['可能开始范围：%s—%s（相邻观测）' % (clock(value['earliest_time']), clock(value['latest_time']))]
             if value['basis'] == 'bounded' else ['实际开始时间未知；首次看到时已开始。'])
    lines.append('首次活动样本：%s；系统首次发现：%s' % (clock(value['first_state_time']), clock(value['detected_at'])))
    if value['sample_age_seconds'] is None:
        lines.append('样本时间超前，发现延迟待核验。')
    elif value['delay_max_seconds'] is not None:
        lines.append('发现延迟范围：%s—%s秒；未取得精确开始事件。' % (_num(value['delay_min_seconds']), _num(value['delay_max_seconds'])))
    else:
        lines.append('首次样本年龄：%s秒；真实开始可能更早。' % _num(value['sample_age_seconds']))
    return lines


def _status(snapshot):
    if not snapshot:
        return ['停车状态：未取得更新状态']
    doors, windows = snapshot.get('closures', {}).get('doors', []), snapshot.get('closures', {}).get('windows', [])
    def closed(items,noun):
        if not items: return noun+'状态未确认'
        return noun+'关闭' if all(v=='closed' for v in items) else noun+'：%d 项确认关闭，%d 项未确认' % (items.count('closed'),len(items)-items.count('closed'))
    return [('动力已下电' if snapshot.get('off') is True else '动力状态未确认') +
            (' · 已确认锁车' if snapshot.get('locked') is True else ' · 锁车未确认'),
            closed(doors, '四门') + ' · ' + closed(windows, '四窗') + ' · 尾门' + ('关闭' if snapshot.get('trunk') == 'closed' else '未确认')]


def _temperatures(report):
    start, end = report.get('start', {}), report.get('end', {})
    lines = []
    values = []
    for key, name in (('inside_temp','车内'), ('outside_temp','车外')):
        left, right = start.get(key, {}), end.get(key, {})
        if right.get('value') is not None:
            values.append('%s：%s → %s℃' % (name, _num(left.get('value')), _num(right.get('value'))))
    if values: lines += ['', '【温度与轮胎】', '；'.join(values)]
    temp_fields=[end.get('inside_temp',{}),end.get('outside_temp',{})]
    if values and any(x.get('field_time') is None for x in temp_fields if x.get('value') is not None):
        lines.append('温度时间未单独提供。')
    elif values and any(x.get('validity')=='stale' for x in temp_fields):
        times=[x.get('field_time') for x in temp_fields if x.get('field_time') is not None]
        if times: lines.append('温度为旧观测（%s）。' % _time(max(times)).split()[-1])
    tyres = end.get('tyres', [])
    pressures = ['%s%s%s' % (x.get('position'), _num(x.get('pressure',{}).get('value')),
                 '（零值待确认）' if x.get('pressure',{}).get('value') == 0 else '') for x in tyres]
    temps = ['%s%s' % (x.get('position'), _num(x.get('temperature',{}).get('value'))) for x in tyres]
    if tyres: lines.append('结束胎压 kPa：' + ' / '.join(pressures))
    if tyres: lines.append('结束胎温 ℃：' + ' / '.join(temps))
    return lines


def _comparison(report):
    block = report.get('comparison', {})
    if not block.get('items'): return []
    lines = ['', '【本车历史参考】']
    for item in block['items']:
        labels = {'minutes_per_km':'每公里用时', 'estimated_kwh_100km':'估算百公里耗电',
                  'minutes_per_soc_point':'每百分点观测用时', 'average_power_kw':'观测区间平均功率'}
        units = {'minutes_per_km':'分钟/公里', 'estimated_kwh_100km':'kWh/100km',
                 'minutes_per_soc_point':'分钟/百分点', 'average_power_kw':'kW'}
        lines.append('%s%d次：本次%s，历史中位数%s %s。' %
                     (item['note'], item['n'], _num(item['current']), _num(item['median']), units[item['metric']]))
    lines.append('仅为本车观测差异，路况、温度、桩等条件未完整匹配。')
    return lines


def _fit(lines, report, event_id, partial, target):
    text='\n'.join(lines)
    if len(text.encode()) <= target: return text, []
    omitted=[]
    optional_prefixes=('额定续航达成率','后段较前段','结束胎温','结束胎压','车内：','本次估算','相近里程','里程、平均','相近电量','仅为本车')
    reduced=[]; in_history=False
    for line in lines:
        if line=='【本车历史参考】': in_history=True; omitted.append('history'); continue
        if in_history and (line.startswith('独立观测') or line.startswith('数据不完整') or line.startswith('状态来自')): in_history=False
        if in_history or line.startswith(optional_prefixes): omitted.append('optional_details'); continue
        if (line.startswith(('出发地：','到达地：','充电地点：')) and len(line)>28
                and '（参考位置，' not in line):
            line=line[:27]+'…'; omitted.append('address_shortened')
        reduced.append(line)
    marker='部分参数因消息长度省略。'
    if marker not in reduced: reduced.insert(-2,marker)
    text='\n'.join(reduced)
    if len(text.encode()) <= target: return text, sorted(set(omitted))
    m=report.get('metrics',{}); start=report.get('start',{}); end=report.get('end',{})
    title=lines[0]
    core=[title,_range(report.get('start_time'),report.get('end_time')),
          '电量：%s%% → %s%%（变化%s个百分点）' % (_num(start.get('soc')),_num(end.get('soc')),_num(m.get('soc_delta')))]
    if report.get('kind')=='trip_end': core.append('停车状态：锁车、门窗及尾门以报告中的未确认项为准。')
    elif report.get('kind')=='charge_start': core += ['实际开始时间未知；首次观测时已在充电。','目标电量／充电枪连接：未确认']
    else: core += ['目标电量：暂未取得','停止原因／充电枪连接：未确认']
    if partial: core.append('部分记录：以上仅汇总已观测区间。')
    core += _start_timing(report)
    core += [marker,'状态来自车辆云端缓存，时间可能延迟。','编号：'+event_id[:12]]
    text='\n'.join(core)
    if len(text.encode())>HARD_BYTES: raise ValueError('报告核心模板超过2048字节')
    return text, sorted(set(omitted+['core_fallback']))


def render(kind, report, event_id, address=None, target=TARGET_BYTES, references=None):
    report = dict(report)
    report.setdefault('kind', kind)
    m = report.get('metrics', {})
    partial = report.get('partial') or m.get('partial')
    suffix = '｜部分记录' if partial else ''
    lines = []
    if kind == 'trip_end':
        duration=m.get('duration_seconds')
        lines.append('🚗 行程结束%s｜%s 公里 · %s 分钟' % (suffix, _num(m.get('distance_km')), _num(duration/60 if duration is not None else None, 0)))
        lines += ['出发地：%s' % _place((address or {}).get('start'), (references or {}).get('start')),
                  '到达地：%s' % _place((address or {}).get('end'), (references or {}).get('end')),
                  _range(report.get('start_time'), report.get('end_time')), '', '【电量与续航】',
                  '电量：%s%% → %s%%（变化 %s 个百分点）' % (_num(report.get('start', {}).get('soc')), _num(report.get('end', {}).get('soc')), _num(m.get('soc_delta')))]
        if m.get('charge_overlap'):
            lines.append('途中有充电，电量变化不用于驾驶耗电统计。')
        if m.get('estimated_kwh') is not None:
            lines.append('估算耗电：约 %s kWh' % _num(m['estimated_kwh']))
        else:
            lines.append('kWh：暂无可靠数据')
        if m.get('estimated_kwh_100km') is not None:
            lines.append('估算百公里耗电：约 %s kWh/100km' % _num(m['estimated_kwh_100km']))
        if m.get('range_delta_km') is not None:
            lines.append('云端续航：%s → %s 公里（变化 %s 公里）' % (_num(report['start'].get('range_km')), _num(report['end'].get('range_km')), _num(m['range_delta_km'])))
        if m.get('range_attainment_percent') is not None:
            lines.append('额定续航达成率：约%s%%（基于SOC与%s估算）' % (_num(m['range_attainment_percent']), clean_text(report.get('profile_snapshot',{}).get('range_standard')) or '额定续航'))
        if m.get('average_speed_kmh') is not None:
            lines.append('平均速度：%s km/h（含途中停车）' % _num(m['average_speed_kmh']))
        if m.get('sampled_max_speed_kmh') is not None:
            note = '（仅1次有效车速观测）' if m.get('speed_samples') == 1 else ''
            lines.append('采样最高速度：%s km/h%s' % (_num(m['sampled_max_speed_kmh']), note))
        parking = report.get('parking') or {}
        updated = report.get('quality',{}).get('parking_samples',0) > 0
        label = '停车后状态' if updated else '结束点状态'
        lines += ['', '【%s · %s】' % (label,_time(parking.get('state_time')).split()[-1])] + _status(report.get('parking'))
        if not updated: lines.append('未取得更新停车状态。')
        lines += _temperatures(report)
    elif kind == 'charge_start':
        mode = {'dc': '｜直流', 'ac': '｜交流'}.get(report.get('start', {}).get('charging_mode'), '')
        location = _place((address or {}).get('start'), (references or {}).get('start'))
        lines = ['⚡ 检测到开始充电%s%s' % (mode, suffix), '充电地点：%s' % location,
                 '记录起点：' + _time(report.get('start_time')), '电量：%s%%' % _num(report.get('start', {}).get('soc'))]
        if partial:
            lines.append('实际开始时间未知；首次观测时已在充电。')
        start = report.get('start', {})
        if start.get('charging_mode') == 'ac':
            lines += ['接口观测电压：%s V' % _num(start.get('ac_voltage', {}).get('value')),
                      '接口观测电流：%s A' % _num(start.get('ac_current', {}).get('value'))]
            if start.get('power_kw') is not None:
                lines.append('交流观测功率：%s kW（电压×电流）' % _num(start['power_kw']))
        elif start.get('power_kw') is not None:
            lines += ['桩侧观测电压：%s V' % _num(start['voltage']['value']), '桩侧观测电流：%s A' % _num(start['current']['value']),
                      '按电压×电流计算功率：%s kW' % _num(start['power_kw'])]
        if start.get('remaining_minutes') is not None:
            lines.append('截至%s，车辆估计剩余%s分钟。' % (_time(start.get('state_time')).split()[-1], _num(start['remaining_minutes'], 0)))
            estimated_end = start.get('state_time') + start['remaining_minutes']*60000
            age = report.get('event_created_at', start.get('observed_at')) - start.get('state_time')
            if -30000 <= age <= 180000 and estimated_end > report.get('event_created_at', 0):
                lines.append('按本次估计约%s结束，估计可能变化。' % _time(estimated_end).split()[-1])
        lines += ['目标电量：暂未取得', '充电枪连接：未确认']
        lines += ['', '【车辆状态 · %s】' % _time(start.get('state_time')).split()[-1]] + _status(start)
        lines.append('直流口盖%s · 交流口盖%s' %
                      ('打开' if start.get('dc_lid')=='open' else '关闭' if start.get('dc_lid')=='closed' else '未确认',
                      '打开' if start.get('ac_lid')=='open' else '关闭' if start.get('ac_lid')=='closed' else '未确认'))
        lines += _temperatures(report)
    else:
        lines = ['🔋 充电已停止%s｜电量%s%%' % (suffix, _num(report.get('end', {}).get('soc'))),
                 '充电地点：%s' % _place((address or {}).get('start'), (references or {}).get('start')),
                 _range(report.get('start_time'), report.get('end_time')), '', '【补电结果】',
                 '电量：%s%% → %s%%（增加%s个百分点）' % (_num(report.get('start', {}).get('soc')), _num(report.get('end', {}).get('soc')), _num(m.get('soc_delta')))]
        if m.get('estimated_kwh') is not None:
            lines.append(('%s估算充入：约%s kWh' % ('已记录区间' if partial else '', _num(m['estimated_kwh']))))
        if m.get('range_delta_km') is not None:
            lines.append('云端续航：%s → %s 公里（增加%s公里）' % (_num(report['start'].get('range_km')), _num(report['end'].get('range_km')), _num(m['range_delta_km'])))
        lines += ['', '【充电过程】', '类型：%s' %
                  {'dc': '直流', 'ac': '交流'}.get(report.get('start', {}).get('charging_mode'), '未确认')]
        if report.get('start', {}).get('charging_mode') == 'ac':
            lines.append('交流功率由同次接口电压×电流计算。')
        if m.get('sampled_peak_kw') is not None:
            lines.append('最高采样功率：%s kW' % _num(m['sampled_peak_kw']))
        if m.get('average_power_kw') is not None:
            lines.append('观测区间平均功率：%s kW' % _num(m['average_power_kw']))
        if m.get('tail_power_drop_percent') is not None:
            lines.append('后段较前段观测功率下降约%s%%' % _num(m['tail_power_drop_percent'], 0))
        covered,total,ratio=m.get('power_covered_seconds'),m.get('duration_seconds'),m.get('power_coverage')
        lines += ['功率有效覆盖：%s/%s分钟（%s%%）' % (_num(covered/60 if covered is not None else None, 0), _num(total/60 if total is not None else None, 0), _num(100*ratio if ratio is not None else None, 0)),
                  '目标电量：暂未取得', '停止原因：未确认', '充电枪连接：未确认']
        stopped=report.get('end',{})
        ac = report.get('start', {}).get('charging_mode') == 'ac'
        voltage = stopped.get('ac_voltage' if ac else 'voltage', {}).get('value')
        current = stopped.get('ac_current' if ac else 'current', {}).get('value')
        if voltage is not None or current is not None:
            lines.append('停止观测：%s电压%s V · 电流%s A' %
                         ('接口' if ac else '桩侧', _num(voltage), _num(current)))
        lines += ['', '【停止状态 · %s】' % _time(stopped.get('state_time')).split()[-1]] + _status(stopped)
        lines += _temperatures(report)
    lines += _comparison(report)
    attention = report.get('attention', {})
    for change in attention.get('changes', []):
        lines.append('%s：%s。' % (_time(change.get('time')).split()[-1], change['text']))
    if any(item.get('key') == 'stale' for item in attention.get('items', [])):
        lines.append('停车状态为旧观测，仅作记录，不代表当前状态。')
    quality = report.get('quality', {})
    count = quality.get('observation_count')
    if count is not None:
        gap = m.get('max_gap_seconds')
        lines.append('独立观测%s次%s。' % (count, '，最大间隔%s秒' % _num(gap,0) if gap is not None else ''))
    if partial:
        lines.append('数据不完整：以上仅汇总已观测区间。')
    lines += _start_timing(report)
    lines += ['状态来自车辆云端缓存，时间可能延迟。', '编号：' + event_id[:12]]
    return _fit(lines, report, event_id, partial, target)
