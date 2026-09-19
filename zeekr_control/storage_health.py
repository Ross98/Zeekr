"""Local filesystem health and persistent, rate-limited WeCom alerts."""
import json
import os
from pathlib import Path
import shutil
import stat
import time

from .notifications import DeliveryError
from .storage import load, save

GIB = 1024**3
INTERVAL = 300
REMINDER = 86400


def tree_bytes(root):
    total, complete = 0, True
    if root.is_symlink(): return 0, False
    if not root.exists(): return 0, True
    try:
        for entry in os.scandir(root):
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(info.st_mode): total += info.st_size
            elif stat.S_ISDIR(info.st_mode):
                size, ok = tree_bytes(Path(entry.path))
                total += size
                complete = complete and ok
            else: complete = False
    except OSError:
        complete = False
    return total, complete


def severity(sample, previous='healthy'):
    if sample.get('disk_used_percent') is None:
        return 'unknown'
    used, free = sample['disk_used_percent'], sample['disk_free_bytes']
    inode = sample.get('inode_used_percent') or 0
    if used >= 90 or free <= 2*GIB or inode >= 90: return 'critical'
    if previous == 'critical' and (used >= 88 or free <= 2.5*GIB or inode >= 88): return 'critical'
    if used >= 80 or free <= 5*GIB or inode >= 80: return 'warning'
    if previous in ('warning', 'critical') and (used >= 78 or free <= 6*GIB or inode >= 78): return 'warning'
    return 'healthy' if sample.get('scan_complete') else 'unknown'


class StorageHealth:
    def __init__(self, root, sender=None):
        self.root = Path(root)
        self.path = self.root/'storage-health.json'
        self.sender = sender
        self.next_check = 0

    def _state(self):
        value = load(self.path).get('state')
        return json.loads(value) if value else {}

    def _save(self, state):
        save(self.path, {'state': json.dumps(state, ensure_ascii=False, allow_nan=False)})

    def measure(self):
        usage = shutil.disk_usage(self.root)
        filesystem = os.statvfs(self.root)
        data, complete = tree_bytes(self.root)
        archive, archive_ok = tree_bytes(self.root/'snapshot-archive')
        trash, trash_ok = tree_bytes(self.root/'snapshot-trash')
        return {'checked_at': time.time(), 'disk_total_bytes': usage.total,
                'disk_used_bytes': usage.used, 'disk_free_bytes': usage.free,
                'disk_used_percent': usage.used/usage.total*100 if usage.total else None,
                'inode_used_percent': (1-filesystem.f_favail/filesystem.f_files)*100 if filesystem.f_files else None,
                'data_bytes': data, 'archive_bytes': archive, 'trash_bytes': trash,
                'scan_complete': complete and archive_ok and trash_ok}

    def cached(self):
        state = self._state()
        result = dict(state.get('sample') or {'status': 'not_checked', 'checked_at': None})
        result['notification_state'] = state.get('notification_state', 'none')
        result['last_notification_at'] = state.get('attempt_at')
        result['monitor_fresh'] = bool(result.get('checked_at') and time.time()-result['checked_at'] <= 900)
        return result

    def _message(self, sample):
        labels = {'critical': '严重', 'warning': '提醒', 'healthy': '恢复正常', 'unknown': '巡检失败'}
        parts = ['极氪服务器存储：'+labels[sample['status']]]
        if sample.get('disk_used_percent') is not None:
            parts += ['磁盘使用 %.1f%%，剩余 %.2f GiB。' % (sample['disk_used_percent'], sample['disk_free_bytes']/GIB)]
        if sample.get('inode_used_percent') is not None:
            parts += ['inode 使用 %.1f%%。' % sample['inode_used_percent']]
        parts += ['未自动删除任何数据。请在设置的存储管理中检查。']
        return '\n'.join(parts)

    def tick(self, now=None):
        now = time.time() if now is None else now
        if now < self.next_check: return
        self.next_check = now+INTERVAL
        state = self._state()
        if now-state.get('last_check', 0) < INTERVAL: return
        try:
            sample = self.measure()
        except OSError:
            sample = {'scan_complete': False, 'disk_used_percent': None}
        sample['checked_at'] = now
        sample['status'] = severity(sample, state.get('sample', {}).get('status'))
        history = [x for x in state.get('history', []) if now-7*86400 <= x['time'] < now]
        recent = [x for x in history if now-86400 <= x['time'] <= now-21600]
        sample['data_growth_bytes_per_day'] = sample['estimated_disk_days'] = None
        if recent and sample.get('scan_complete'):
            start = recent[0]
            factor = 86400/(now-start['time'])
            sample['data_growth_bytes_per_day'] = (sample['data_bytes']-start['data_bytes'])*factor
            disk_growth = (start['free_bytes']-sample['disk_free_bytes'])*factor
            if disk_growth > 0: sample['estimated_disk_days'] = sample['disk_free_bytes']/disk_growth
        if sample.get('scan_complete'):
            history.append({'time': now, 'data_bytes': sample['data_bytes'], 'free_bytes': sample['disk_free_bytes']})
        state.update(sample=sample, history=history[-2016:], last_check=now)
        # A worker interrupted during send must not retry an uncertain delivery.
        if state.get('notification_state') == 'sending': state['notification_state'] = 'uncertain'
        level = sample['status']
        prior = state.get('notification_level', 'healthy')
        changed = level != prior
        due = changed or (level != 'healthy' and now-state.get('attempt_at', 0) >= REMINDER)
        if state.get('notification_state') == 'failed' and level == prior:
            due = now >= state.get('retry_at', now+3600)
        if not due or self.sender is None:
            self._save(state)
            return
        state.update(notification_state='sending', notification_level=level, attempt_at=now)
        self._save(state)  # Durable intent before network; errors never silently hide disk trouble.
        try:
            self.sender(self._message(sample))
            state['notification_state'] = 'sent'
        except DeliveryError as exc:
            state['notification_state'] = 'uncertain' if exc.ambiguous else 'failed'
            state['retry_at'] = now+(3600 if exc.permanent else 900)
        except Exception:
            state['notification_state'] = 'uncertain'
        self._save(state)
