"""Prevent credential-file/query-lock nesting, including future call paths."""
from contextlib import contextmanager
from contextvars import ContextVar

held=ContextVar('zeekr_coordination_lock',default='')


@contextmanager
def lock_context(kind):
    if held.get(): raise RuntimeError('凭据锁与查询锁不得嵌套。')
    token=held.set(kind)
    try: yield
    finally: held.reset(token)
