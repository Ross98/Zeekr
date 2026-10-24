"""Owner-only SQLite metadata; credentials do not belong in these databases."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from .archive_reader import _private
from .sqlite_files import prepare_database_file
from .credential_store import sync_directory


@contextmanager
def database(path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    _private(path.parent,directory=True)
    prepare_database_file(path)
    _private(path)
    sync_directory(path.parent)
    db=sqlite3.connect(str(path),timeout=5)
    try:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        yield db
    finally: db.close()
