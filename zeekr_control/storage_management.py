"""Owner-only archive maintenance: preview, confirm, recycle, restore and purge."""
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
import time

from .snapshot_archive import archive_lock, _private_directory, BEIJING

PARTITION = re.compile(r'(\d{4})/(0[1-9]|1[0-2])\Z')
TRASH = re.compile(r'(\d{4})-(0[1-9]|1[0-2])-([a-f0-9]{32})\.sqlite3\Z')
LABELS = {'trash': '移入回收区', 'restore': '恢复', 'purge': '永久删除'}


def _file_info(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError('拒绝操作非私有普通归档文件。')
    if any(os.path.lexists(path.with_name(path.name + suffix)) for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('归档存在数据库工作文件，须先确认已停止写入。')
    return info


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


class StorageManager:
    def __init__(self, root, clock=time.time):
        self.root = Path(root)
        self.archive = self.root / 'snapshot-archive'
        self.trash = self.root / 'snapshot-trash'
        self.clock = clock
        self.plans = {}
        self.lock = threading.RLock()

    def _resolve(self, action, target):
        if action not in LABELS or not isinstance(target, str):
            raise ValueError('存储操作无效。')
        match = (PARTITION if action == 'trash' else TRASH).fullmatch(target)
        if not match:
            raise ValueError('仅可选择列表中的历史归档。')
        partition = '%s/%s' % match.group(1, 2)
        current = datetime.fromtimestamp(self.clock(), BEIJING).strftime('%Y/%m')
        if partition >= current:
            raise ValueError('当前月份及未来归档受保护，不能操作。')
        if action == 'trash':
            _private_directory(self.archive / match.group(1))
            path = self.archive / (partition + '.sqlite3')
        else:
            _private_directory(self.trash)
            path = self.trash / target
        info = _file_info(path)
        if action == 'restore' and (self.archive / (partition + '.sqlite3')).exists():
            raise ValueError('原月份归档已存在，不能覆盖恢复。')
        return path, partition, info

    def _describe(self, path, partition, info):
        count = None
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                count = db.execute('SELECT COUNT(*) FROM reads').fetchone()[0]
        except sqlite3.DatabaseError:
            pass  # A damaged archive can still be explicitly managed, not called empty.
        return {'partition': partition, 'bytes': info.st_size,
                'allocated_bytes': getattr(info, 'st_blocks', 0) * 512,
                'reads': count, 'database_readable': count is not None}

    def inventory(self):
        archives, trash = [], []
        with archive_lock(self.archive):
            current = datetime.fromtimestamp(self.clock(), BEIJING).strftime('%Y/%m')
            for year in sorted(self.archive.iterdir()):
                if not re.fullmatch(r'\d{4}', year.name) or year.is_symlink() or not year.is_dir(): continue
                _private_directory(year)
                for path in sorted(year.iterdir()):
                    partition = year.name + '/' + path.stem
                    if path.suffix != '.sqlite3' or not PARTITION.fullmatch(partition): continue
                    try:
                        item = self._describe(path, partition, _file_info(path))
                        item.update(id=partition, manageable=partition < current)
                    except (ValueError, OSError):
                        item = {'id': partition, 'partition': partition, 'manageable': False,
                                'bytes': None, 'reads': None, 'database_readable': False}
                    archives.append(item)
            if self.trash.exists() or self.trash.is_symlink():
                _private_directory(self.trash)
                for path in sorted(self.trash.iterdir()):
                    match = TRASH.fullmatch(path.name)
                    if not match: continue
                    partition = '%s/%s' % match.group(1, 2)
                    try:
                        item = self._describe(path, partition, _file_info(path))
                        item.update(id=path.name, manageable=partition < current)
                    except (ValueError, OSError):
                        item = {'id': path.name, 'partition': partition, 'manageable': False,
                                'bytes': None, 'reads': None, 'database_readable': False}
                    trash.append(item)
        return {'archives': archives, 'trash': trash, 'scope': '全部车辆的完整快照归档',
                'protected': '当前月份、凭据、最新车况、轨迹、事件及备份不在删除范围'}

    def preview(self, action, target, owner):
        with self.lock, archive_lock(self.archive):
            path, partition, info = self._resolve(action, target)
            now = self.clock()
            self.plans = {k:v for k,v in self.plans.items() if v['expires_at'] > now}
            if len(self.plans) >= 32:
                del self.plans[next(iter(self.plans))]
            token = secrets.token_urlsafe(32)
            plan = dict(self._describe(path, partition, info), token=token, action=action,
                        target=target, expires_at=now+300, confirmation=LABELS[action]+' '+partition)
            self.plans[token] = dict(plan, owner=owner, fingerprint=_fingerprint(info))
            return dict(plan, released_bytes=plan['allocated_bytes'] if action == 'purge' else 0)

    def _audit(self, entry):
        path = self.root / 'storage-audit.jsonl'
        fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise OSError('审计文件权限不安全。')
            with os.fdopen(fd, 'a', encoding='utf-8', closefd=False) as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)

    def execute(self, token, confirmation, owner):
        if not isinstance(token, str): raise ValueError('请重新预览操作。')
        with self.lock, archive_lock(self.archive):
            plan = self.plans.get(token)
            if not plan or plan['owner'] != owner or self.clock() >= plan['expires_at']:
                raise ValueError('预览已失效或会话不匹配，请重新预览。')
            if confirmation != plan['confirmation']:
                raise ValueError('确认文字不匹配，未执行。')
            action = plan['action']
            path, partition, info = self._resolve(action, plan['target'])
            if _fingerprint(info) != plan['fingerprint']:
                raise ValueError('归档在预览后发生变化，请重新预览。')
            operation_id = secrets.token_hex(16)
            if action == 'trash':
                _private_directory(self.trash)
                destination = self.trash / (partition.replace('/', '-')+'-'+operation_id+'.sqlite3')
            elif action == 'restore':
                _private_directory(self.archive / partition[:4])
                destination = self.archive / (partition + '.sqlite3')
            else:
                destination = None
            if destination is not None and (destination.exists() or destination.is_symlink()):
                raise ValueError('目标已存在，未执行。')
            entry = {'id': operation_id, 'time': int(self.clock()), 'action': action,
                     'partition': partition, 'bytes': info.st_size, 'phase': 'planned'}
            self._audit(entry)  # No destructive operation unless its intent is durable.
            del self.plans[token]
            if action == 'purge':
                path.unlink()  # Single validated, confirmed, old archive in recycle area only.
            else:
                os.rename(path, destination)
            warning = None
            try:
                if destination is not None: _sync(destination.parent)
                _sync(path.parent)
                self._audit(dict(entry, phase='complete'))
            except OSError:
                warning = '操作已执行，但落盘确认或完成审计失败；请检查存储，勿重复操作。'
            return {'action': action, 'partition': partition, 'completed': True,
                    'released_bytes': plan['allocated_bytes'] if action == 'purge' else 0,
                    'audit_warning': warning}
