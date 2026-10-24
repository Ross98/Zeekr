"""Publish private empty SQLite files without touching an existing DB inode."""
import os
from pathlib import Path
import tempfile


def prepare_database_file(path):
    """Return lstat metadata; caller retains its ownership/type/mode checks.

    Raw open/close on an existing SQLite file can drop another connection's
    process-wide POSIX locks. Close a new temporary inode before publishing it;
    link never replaces a competing creator's database.
    """
    path=Path(path)
    try:return path.lstat()
    except FileNotFoundError:pass
    fd,temporary=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        os.close(fd);fd=None
        try:os.link(temporary,path)
        except FileExistsError:pass
    finally:
        if fd is not None:os.close(fd)
        Path(temporary).unlink()
    return path.lstat()
