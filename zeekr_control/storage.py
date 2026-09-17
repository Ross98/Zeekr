"""Owner-only plaintext session storage; atomic replacement, no token logging."""
import json
import os
from pathlib import Path
import stat
import tempfile

from .client import ApiError

DEFAULT_PATH = Path.home() / 'Library' / 'Application Support' / 'ZeekrControl' / 'session.json'


def load(path=DEFAULT_PATH):
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    except OSError:
        raise ApiError('无法安全读取会话文件。') from None
    try:
        with os.fdopen(fd, 'r') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise ApiError('会话文件权限不安全，应由当前用户持有且权限为 600。')
            data = json.load(stream)
        if not isinstance(data, dict) or any(not isinstance(v, str) for v in data.values()):
            raise ApiError('会话文件格式错误。')
        return data
    except (ValueError, OSError):
        raise ApiError('会话文件损坏或无法读取。') from None


def save(path, data):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ApiError('拒绝使用符号链接存储会话。')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.parent.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ApiError('会话目录权限不安全，应由当前用户持有且权限为 700。')
    fd, temporary = tempfile.mkstemp(prefix='.session-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clear(path=DEFAULT_PATH):
    Path(path).unlink(missing_ok=True)
