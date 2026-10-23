"""Owner-only SQLite metadata; credentials do not belong in these databases."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from .archive_reader import _private
from .credential_store import sync_directory


@contextmanager
def database(path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    _private(path.parent,directory=True)
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    os.close(fd);_private(path)
    sync_directory(path.parent)
    db=sqlite3.connect(str(path),timeout=5)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA synchronous=FULL')
    try: yield db
    finally: db.close()
