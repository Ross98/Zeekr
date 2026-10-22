# -*- coding: utf-8 -*-
"""Independent resource conditions. Missing evidence never proves recovery."""
import math

MIB = 1024**2
RANK = {'healthy': 0, 'unknown': 1, 'warning': 2, 'critical': 3}


def observations(sample, previous=None):
    previous = previous or {}
    result = {}

    def add(key, level, reason, category):
        result[key] = dict(observed=level, reason=reason, category=category)

    def numeric(key, field, warning, hard, reason, category, complete=True):
        value = sample.get(field)
        old = previous.get(key, {}).get('level', 'healthy')
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            errors = sample.get('sample_errors', [])
            level = 'unknown' if key in errors or key.startswith('app_') and 'processes' in errors else 'warming_up'
        elif hard is not None and (value >= hard or old == 'critical' and value >= hard-5):
            level = 'critical'
        elif value >= warning*(.9 if old in ('warning', 'critical') else 1):
            level = 'warning'
        else:
            level = 'healthy' if complete else 'warming_up'
        add(key, level, reason, category)

    # Heartbeat-only observations belong to a separate writer/state file.
    if 'observer_health' in sample:
        add('observer', 'healthy' if sample['observer_health'] else 'unknown', '资源巡检心跳过期或不可读', 'monitoring')
        return result
    numeric('host_cpu', 'host_cpu_percent', 85, 95, '主机 CPU 持续高占用', 'system')
    numeric('app_cpu', 'app_cpu_percent', 100, None, 'Zeekr 进程树 CPU 持续超预算', 'budget', sample.get('app_cpu_complete', False))
    numeric('app_rss', 'app_rss_bytes', 512*MIB, None, 'Zeekr 进程树内存持续超预算', 'budget')
    if sample.get('app_cpu_complete') is not True:
        # One warm-up window is normal; three independently spaced incomplete
        # windows mean we cannot keep calling an unmeasurable metric warm-up.
        add('window:app_cpu', 'unknown', '进程 CPU 窗口持续不完整，无法证明低占用或恢复', 'monitoring')
    else:
        add('window:app_cpu', 'healthy', '进程 CPU 窗口持续不完整，无法证明低占用或恢复', 'monitoring')
    pressure = sample.get('memory_pressure')
    level = {'normal': 'healthy', 'warning': 'warning', 'critical': 'critical'}.get(pressure, 'unknown')
    add('memory_pressure', level, '系统内存压力严重' if level == 'critical' else '系统内存压力升高', 'system')
    labels = ('local.zeekr.web', 'local.zeekr.monitor', 'local.zeekr.reports')
    for label in labels:
        add('service:'+label, 'critical' if label in sample.get('missing_services', []) else 'healthy', label+' 服务任务不可用', 'availability')
    for endpoint, ok in sample.get('endpoints', {}).items():
        add('endpoint:'+endpoint, 'healthy' if ok else 'critical', ('本机网页' if endpoint == 'local' else 'HTTPS 入口')+'访问或认证边界异常', 'availability')
    # A sensor's failure has its own confirmation, independently of a previous
    # pressure alarm. Warm-up is not failure and cannot clear that alarm.
    for key, observation in list(result.items()):
        if observation['category']=='monitoring':continue
        if observation['observed'] in ('unknown', 'warming_up'):
            failed = observation['observed'] == 'unknown'
            add('sensor:'+key, 'unknown' if failed else 'healthy', key+' 指标不可用，不能判断压力或恢复', 'monitoring')
        else:
            add('sensor:'+key, 'healthy', key+' 指标不可用，不能判断压力或恢复', 'monitoring')
    return result


def advance(records, current, consecutive, confirmations):
    for key, observation in current.items():
        record = records.setdefault(key, dict(level='healthy'))
        observed = observation['observed']
        count = record.get('streak', 0)+1 if consecutive and record.get('observed') == observed else 1
        old_reason=record.get('reason')
        record.update(observation, streak=count)
        # Unknown is only a confirmed incident for monitoring conditions. For
        # resource conditions retain the last known pressure until measured.
        if count >= confirmations and (observed not in ('unknown', 'warming_up') or observation['category'] == 'monitoring'):
            record['level'] = observed
        elif old_reason is not None and record.get('level')!='healthy':
            record['reason']=old_reason
    return records


def active_conditions(records):
    return {key: value for key, value in records.items() if value.get('level') in ('warning', 'critical', 'unknown')}


def signature(records):
    return '|'.join(key+'='+value['level'] for key, value in sorted(active_conditions(records).items()))


def overall(records):
    return max((record.get('level', 'healthy') for record in records.values()), key=lambda level: RANK.get(level, 0), default='healthy')
