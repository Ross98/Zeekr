"""Read-only start timing audit; no client, monitor, notifications or DB writes.

python3 -m zeekr_control.start_audit --days 7
python3 -m zeekr_control.start_audit --event EVENT_ID --actual-start 2026-09-20T08:00:30+08:00
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3
import time

from .start_evidence import comparison
from .storage import DEFAULT_PATH
from .usage_events import UsageEvents


def reference_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError
        return int(parsed.timestamp()*1000)
    except (TypeError, ValueError, OverflowError):
        raise argparse.ArgumentTypeError('实际开始时间需带时区，例如 2026-09-20T08:00:30+08:00。') from None


def audit(root, *, days=7, limit=20, event=None, actual_start=None, now=None):
    if type(days) is not int or not 1 <= days <= 31 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('日期范围应为 1–31 天，记录上限应为 1–100。')
    if actual_start is not None and not event:
        raise ValueError('实测时间必须明确对应一条事件。')
    root = Path(root)
    binding_path = root / 'monitor-binding.json'
    try:
        binding = json.loads(binding_path.read_text())
        vehicle = binding.get('vehicle_key') if isinstance(binding, dict) else None
    except FileNotFoundError:
        vehicle = None
    if not isinstance(vehicle, str) or not vehicle:
        raise ValueError('没有当前绑定车辆，无法选择核验记录。')
    store = UsageEvents(root / 'tracks.sqlite3')
    if event:
        records = [store.get(vehicle, event)]
    else:
        now = int(time.time()*1000) if now is None else now
        records = store.between(vehicle, now-days*86400000, now+1)['events'][:limit]
    rows = [dict(event_id=row['id'], kind=row['kind'], record_start_time=row['start_time'],
                 record_end_time=row['end_time'], **comparison(row, actual_start)) for row in records]
    ages = sorted(row['start_evidence']['sample_age_seconds'] for row in rows
                  if row['start_evidence']['sample_age_seconds'] is not None)
    percentile = lambda p: ages[max(0, math.ceil(len(ages)*p)-1)] if ages else None
    return {'reference_source': 'user_supplied' if actual_start is not None else None,
            'reference_start_time': actual_start, 'record_count': len(rows),
            'evidence_count': sum(row['start_evidence']['basis'] != 'legacy' for row in rows),
            'sample_age_p50_seconds': percentile(.5), 'sample_age_p95_seconds': percentile(.95),
            'note': '样本年龄不等于真实开始延迟；实测基准单独提供，原记录未修改。', 'records': rows}


def main():
    parser = argparse.ArgumentParser(description='只读核验当前绑定车辆的行程/充电起点，不查询车辆或发通知。')
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_PATH.parent)
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--event')
    parser.add_argument('--actual-start', type=reference_time)
    args = parser.parse_args()
    try:
        result = audit(args.data_dir, days=args.days, limit=args.limit,
                       event=args.event, actual_start=args.actual_start)
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(2, '起点核验失败：请检查本地数据权限、车辆绑定、事件和时间参数。\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
