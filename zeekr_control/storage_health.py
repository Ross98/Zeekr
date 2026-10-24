"""Local filesystem health and persistent, rate-limited WeCom alerts."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

from .notifications import DeliveryError
from .errors import ApiError
from .storage import load, save
from .delivery_state import delivery_clock

GIB = 1024**3
INTERVAL = 300
REMINDER = 86400

# Foundation includes space macOS expects to reclaim. Run a fixed, non-UI script;
# the path is an argument, never JavaScript source. No files are purged here.
MACOS_CAPACITY_SCRIPT = '''function run(argv) {
 ObjC.import("Foundation");
 var url = $.NSURL.fileURLWithPath(argv[0]);
 var keys = $(["NSURLVolumeTotalCapacityKey", "NSURLVolumeAvailableCapacityForImportantUsageKey"]);
 var values = url.resourceValuesForKeysError(keys, null);
 if (!values) throw Error("capacity unavailable");
 return JSON.stringify(ObjC.deepUnwrap(values));
}'''


def alert_capacity(root, usage):
    if sys.platform != 'darwin':
        return {'capacity_basis': 'filesystem_free', 'capacity_available_bytes': usage.free,
                'capacity_used_percent': usage.used/usage.total*100 if usage.total else None,
                'reclaimable_bytes': None}
    try:
        result = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', MACOS_CAPACITY_SCRIPT,
                                 '--', str(root)], capture_output=True, text=True, check=True, timeout=5)
        values = json.loads(result.stdout)
        available = values['NSURLVolumeAvailableCapacityForImportantUsageKey']
        total = values['NSURLVolumeTotalCapacityKey']
        if (type(available) is not int or type(total) is not int or
                total != usage.total or not 0 <= available <= total or total <= 0):
            raise ValueError('Invalid capacity')
        return {'capacity_basis': 'macos_important_usage', 'capacity_available_bytes': available,
                'capacity_used_percent': (1-available/total)*100,
                'reclaimable_bytes': max(0, available-usage.free)}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return {'capacity_basis': 'unavailable', 'capacity_available_bytes': None,
                'capacity_used_percent': None, 'reclaimable_bytes': None}


def capacity_lines(sample):
    if sample.get('capacity_basis') in ('macos_important_usage', 'unavailable'):
        lines = ['即时空闲：%.2f GiB（当前已腾出）。' % (sample['disk_free_bytes']/GIB)]
        available = sample.get('capacity_available_bytes')
        if available is None:
            lines.append('macOS估算可用：读取失败；空间告警口径未知。')
        else:
            lines += ['macOS估算可用：%.2f GiB（含系统预计可回收空间，并非已全部腾空）。' % (available/GIB),
                      '告警口径使用率：%.1f%%。' % sample['capacity_used_percent']]
        return lines
    return []


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
    inode = sample.get('inode_used_percent') or 0
    if inode >= 90: return 'critical'
    if sample.get('capacity_basis') == 'unavailable': return 'unknown'
    used = sample.get('capacity_used_percent', sample.get('disk_used_percent'))
    free = sample.get('capacity_available_bytes', sample.get('disk_free_bytes'))
    if used is None or free is None: return 'unknown'
    if used >= 90 or free <= 2*GIB: return 'critical'
    if previous == 'critical' and (used >= 88 or free <= 2.5*GIB or inode >= 88): return 'critical'
    if used >= 80 or free <= 5*GIB or inode >= 80: return 'warning'
    if previous in ('warning', 'critical') and (used >= 78 or free <= 6*GIB or inode >= 78): return 'warning'
    return 'healthy' if sample.get('scan_complete') else 'unknown'


class StorageHealth:
    def __init__(self, root, sender=None, alert_sender=None):
        self.root = Path(root)
        self.path = self.root/'storage-health.json'
        self.sender = sender
        self.alert_sender = alert_sender
        self.next_check = 0

    def _state(self):
        value = load(self.path).get('state')
        state=json.loads(value) if value else {}
        if not isinstance(state,dict):raise ValueError('存储巡检状态格式错误。')
        return state

    def _save(self, state):
        # Old readers know one deadline: keep it conservative for rollback.
        deadlines=[state[key.replace('_state','_retry_at')]
                   for key in ('notification_state','alert_notification_state')
                   if state.get(key) in ('pending','failed') and key.replace('_state','_retry_at') in state]
        if deadlines:state['retry_at']=max(deadlines)
        save(self.path, {'state': json.dumps(state, ensure_ascii=False, allow_nan=False)})

    def measure(self):
        usage = shutil.disk_usage(self.root)
        filesystem = os.statvfs(self.root)
        data, complete = tree_bytes(self.root)
        archive, archive_ok = tree_bytes(self.root/'snapshot-archive')
        trash, trash_ok = tree_bytes(self.root/'snapshot-trash')
        return {**alert_capacity(self.root, usage), 'checked_at': time.time(), 'disk_total_bytes': usage.total,
                'disk_used_bytes': usage.used, 'disk_free_bytes': usage.free,
                'disk_used_percent': usage.used/usage.total*100 if usage.total else None,
                'inode_used_percent': (1-filesystem.f_favail/filesystem.f_files)*100 if filesystem.f_files else None,
                'data_bytes': data, 'archive_bytes': archive, 'trash_bytes': trash,
                'scan_complete': complete and archive_ok and trash_ok}

    def cached(self):
        try:
            state = self._state()
            sample=state.get('sample')
            if sample is None:sample={'status':'not_checked','checked_at':None}
            if not isinstance(sample,dict):raise ValueError('存储巡检样本格式错误。')
            result=dict(sample)
        except (ApiError,ValueError,TypeError):
            # Read-only fallback: never erase uncertain delivery history or
            # manufacture a fresh sample while displaying current disk usage.
            return {'status':'unknown','checked_at':None,'monitor_fresh':False,
                    'notification_state':'unavailable','alert_notification_state':'unavailable',
                    'last_notification_at':None,'error_code':'storage_state_unavailable'}
        result['notification_state'] = state.get('notification_state', 'none')
        result['alert_notification_state'] = state.get('alert_notification_state', 'none')
        result['last_notification_at'] = state.get('attempt_at')
        checked=result.get('checked_at')
        valid_time=type(checked) in (int,float) and 0<checked<=32503680000
        if not valid_time:result['checked_at']=None
        result['monitor_fresh'] = valid_time and 0<=time.time()-checked<=900
        return result

    def _message(self, sample):
        labels = {'critical': '严重', 'warning': '提醒', 'healthy': '恢复正常', 'unknown': '巡检失败'}
        parts = ['极氪服务器存储：'+labels[sample['status']]]
        if sample.get('capacity_basis') in ('macos_important_usage', 'unavailable'):
            parts += capacity_lines(sample)
        elif sample.get('disk_used_percent') is not None:
            parts += ['磁盘使用 %.1f%%，剩余 %.2f GiB。' % (sample['disk_used_percent'], sample['disk_free_bytes']/GIB)]
        if sample.get('inode_used_percent') is not None:
            parts += ['inode 使用 %.1f%%。' % sample['inode_used_percent']]
        parts += ['未自动删除任何数据。请在设置的存储管理中检查。']
        return '\n'.join(parts)

    def _alert(self, sample):
        healthy = sample['status'] == 'healthy'
        title = '✅ Zeekr 服务器存储恢复' if healthy else '⚠️ Zeekr 服务器存储异常'
        parts = []
        if sample.get('capacity_basis') in ('macos_important_usage', 'unavailable'):
            parts += capacity_lines(sample)
        elif sample.get('disk_used_percent') is not None:
            parts.append('磁盘使用率：%.1f%%' % sample['disk_used_percent'])
        if sample.get('capacity_basis') not in ('macos_important_usage', 'unavailable') and sample.get('disk_free_bytes') is not None:
            parts.append('磁盘剩余：%.2f GiB' % (sample['disk_free_bytes']/GIB))
        if sample.get('inode_used_percent') is not None:
            parts.append('inode 使用率：%.1f%%' % sample['inode_used_percent'])
        parts.append('恢复详情由企业微信发送' if healthy else '具体异常由企业微信发送')
        return title, '\n'.join(parts)

    def tick(self, now=None, can_send=None):
        now = time.time() if now is None else now
        elapsed_clock=delivery_clock(int(now*1000))
        current_time=lambda:elapsed_clock()/1000
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
        basis = sample.get('capacity_basis', 'filesystem_free')
        recent = [x for x in history if now-86400 <= x['time'] <= now-21600
                  and x.get('capacity_basis', 'filesystem_free') == basis]
        sample['data_growth_bytes_per_day'] = sample['estimated_disk_days'] = None
        if recent and sample.get('scan_complete'):
            start = recent[0]
            factor = 86400/(now-start['time'])
            sample['data_growth_bytes_per_day'] = (sample['data_bytes']-start['data_bytes'])*factor
            available = sample.get('capacity_available_bytes', sample['disk_free_bytes'])
            disk_growth = ((start.get('available_bytes', start['free_bytes'])-available)*factor
                           if available is not None else 0)
            if disk_growth > 0: sample['estimated_disk_days'] = available/disk_growth
        if sample.get('scan_complete'):
            if sample.get('capacity_available_bytes', sample.get('disk_free_bytes')) is not None:
                history.append({'time': now, 'data_bytes': sample['data_bytes'], 'free_bytes': sample['disk_free_bytes'],
                                'capacity_basis': basis,
                                'available_bytes': sample.get('capacity_available_bytes', sample['disk_free_bytes'])})
        state.update(sample=sample, history=history[-2016:], last_check=now)
        # A worker interrupted during send must not retry an uncertain delivery.
        if state.get('notification_state') == 'sending': state['notification_state'] = 'uncertain'
        if state.get('alert_notification_state') == 'sending': state['alert_notification_state'] = 'uncertain'
        level = sample['status']
        prior = state.get('notification_level', 'healthy')
        changed = level != prior
        reminder_due = level != 'healthy' and now-state.get('attempt_at', 0) >= REMINDER
        legacy_retry=state.get('retry_at',now+3600)
        detail_failed = (state.get('notification_state') in ('failed', 'pending') and level == prior
                         and now>=state.get('notification_retry_at',legacy_retry))
        alert_failed = (state.get('alert_notification_state') in ('failed', 'pending') and level == prior
                        and now>=state.get('alert_notification_retry_at',legacy_retry))
        due = changed or reminder_due or detail_failed or alert_failed
        if not due or self.sender is None and self.alert_sender is None:
            self._save(state)
            return
        send_detail = self.sender is not None and (changed or reminder_due or detail_failed)
        send_alert = self.alert_sender is not None and (changed or reminder_due or alert_failed)
        state.update(notification_level=level, attempt_at=now)
        if send_detail:state.update(notification_state='pending',notification_retry_at=now)
        if send_alert:state.update(alert_notification_state='pending',alert_notification_retry_at=now)
        self._save(state)
        if send_alert:
            if not self._deliver_channel(state,'alert_notification_state',lambda:self._alert(sample),
                                         self.alert_sender,current_time,can_send):return
        if send_detail:
            self._deliver_channel(state,'notification_state',lambda:(self._message(sample),),
                                  self.sender,current_time,can_send)

    def _deliver_channel(self,state,key,prepare,sender,current_time,can_send):
        # Preparation is known unsent. Each channel gets its own durable intent
        # and acknowledgement before the next channel can start.
        try:arguments=prepare()
        except Exception:
            state[key]='failed'
            state[key.replace('_state','_retry_at')]=current_time()+900
            self._save(state)
            return True
        if can_send is not None and not can_send():return False
        state[key]='sending'
        self._save(state)
        try:
            sender(*arguments)
            state[key]='sent'
        except DeliveryError as exc:
            state[key]='uncertain' if exc.ambiguous else 'failed'
            state[key.replace('_state','_retry_at')]=current_time()+(3600 if exc.permanent else 900)
        except Exception:
            state[key]='uncertain'
        self._save(state)
        return True
