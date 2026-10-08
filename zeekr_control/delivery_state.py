"""Process and thread exclusion for delivery and crash recovery."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import threading


class DeliveryBusy(Exception):
    pass


class DeliveryCancelled(Exception):
    """No send may start after sampling, ownership or shutdown changes."""


_mutex = threading.Lock()
_locks = {}
_local = threading.local()


@contextmanager
def delivery_lock(path):
    path=Path(path).absolute()
    key=(os.getpid(),str(path))
    with _mutex:
        lock=_locks.setdefault(key,threading.RLock())
    if not lock.acquire(blocking=False):
        raise DeliveryBusy('通知任务已由其他执行者处理。')
    held=getattr(_local,'held',{})
    _local.held=held
    nested=key in held
    fd=None
    try:
        if not nested:
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            parent=path.parent.stat()
            if path.parent.is_symlink() or parent.st_uid!=os.getuid() or parent.st_mode & 0o077:
                raise ValueError('通知目录须由当前用户持有且权限为700。')
            fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077:
                raise ValueError('通知锁权限须为600。')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise DeliveryBusy('通知任务已由其他执行者处理。') from None
            held[key]=fd
        yield
    finally:
        if not nested:held.pop(key,None)
        if fd is not None:os.close(fd)
        lock.release()


def add_columns(db,table,columns):
    present={row[1] for row in db.execute('PRAGMA table_info('+table+')')}
    for name,declaration in columns.items():
        if name not in present:
            db.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+declaration)


def normalize_preparation_for_rollback(root):
    """After services stop, let legacy readers retry only provably unsent work.

    Run as the service owner. Both locks exclude any remaining local/manual
    sender. Failure leaves the code switch to the caller; no data is restored.
    """
    import sqlite3
    root=Path(root)
    counts={}
    with delivery_lock(root/'notifications.lock'),delivery_lock(root/'periodic-delivery.lock'):
        stores=[('tracks.sqlite3',[(table,'delivery') for table in
                ('monitor_events','monitor_event_media','monitor_event_alerts')]),
                ('periodic-reports.sqlite3',[('reports','text'),('reports','image')])]
        for name,targets in stores:
            path=root/name
            if not path.exists() and not path.is_symlink():continue
            info=path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077 or info.st_nlink!=1:
                raise ValueError('回滚投递库权限不安全。')
            db=sqlite3.connect(path.absolute().as_uri()+'?mode=rw',uri=True,timeout=5)
            try:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    for table,column in targets:
                        if table not in tables:continue
                        changed=db.execute('UPDATE '+table+' SET '+column+"='pending' WHERE "+column+" IN ('preparing','ready')").rowcount
                        counts[table+'.'+column]=changed
            finally:db.close()
    return counts
