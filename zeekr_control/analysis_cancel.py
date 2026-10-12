"""Cooperative cancellation scoped to an analysis worker, never global state."""
from contextlib import contextmanager
import threading

_local = threading.local()


class AnalysisCancelled(Exception):
    pass


def cancelled():
    probe = getattr(_local, 'probe', None)
    return bool(probe and probe())


def check_cancelled():
    if cancelled():
        raise AnalysisCancelled('分析已取消。')


def configure_sqlite(db):
    """Only asynchronous workers need the SQLite cancellation callback."""
    if getattr(_local, 'probe', None) is not None:
        db.set_progress_handler(cancelled, 1000)


@contextmanager
def cancellation_scope(probe):
    previous = getattr(_local, 'probe', None)
    _local.probe = probe
    try:
        check_cancelled()
        yield
    finally:
        _local.probe = previous
