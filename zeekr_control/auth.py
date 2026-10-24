"""Single-user auth with bounded sessions and owner-only remembered credentials."""
from contextlib import closing
import hashlib
import hmac
import ipaddress
import math
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import threading
import time
from .sqlite_files import prepare_database_file


def password_record(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return {'salt': salt, 'digest': digest}


class WebAuth:
    def __init__(self, record, remembered_path=None):
        self.salt = bytes.fromhex(record['salt'])
        self.digest = bytes.fromhex(record['digest'])
        if len(self.salt) != 16 or len(self.digest) != 32:
            raise ValueError('Invalid password record')
        self.sessions = {}
        self.failures = []
        self.lock = threading.RLock()
        self.remembered_path = Path(remembered_path) if remembered_path is not None else None
        self.password_key = hashlib.sha256(self.salt + self.digest).digest()
        if self.remembered_path is not None:
            self.remembered_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with closing(self._connect(create=True)) as connection, connection:
                connection.execute('''CREATE TABLE IF NOT EXISTS remembered_sessions (
                    token_key BLOB PRIMARY KEY, password_key BLOB NOT NULL,
                    client_key BLOB NOT NULL, expires REAL NOT NULL)''')

    def _connect(self, create=False):
        """Check owner-only storage before SQLite opens it; never follow a symlink."""
        path = self.remembered_path
        if path.parent.is_symlink():
            raise ValueError('记住设备的存储目录不可使用符号链接。')
        parent = path.parent.stat()
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise ValueError('记住设备的存储目录权限必须为 700。')
        info = prepare_database_file(path) if create else path.lstat()
        if stat.S_ISDIR(info.st_mode):
            raise IsADirectoryError('记住设备的存储路径必须为普通文件。')
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('记住设备的存储文件权限必须为 600。')
        return sqlite3.connect(path, timeout=2)

    @staticmethod
    def _client_key(client_ip, user_agent):
        try:
            address = str(ipaddress.ip_address(client_ip))
        except ValueError:
            raise ValueError('无法确认客户端 IP，请选择“不记住”后登录。') from None
        if not isinstance(user_agent, str) or not 0 < len(user_agent) <= 1024:
            raise ValueError('无法确认此浏览器，请选择“不记住”后登录。')
        return hashlib.sha256((address + '\n' + user_agent).encode()).digest()

    def limited(self):
        with self.lock:
            now=time.monotonic()
            self.failures = [t for t in self.failures if now - t < 300]
            return len(self.failures) >= 5

    def login(self, password, remember_days=0, client_ip='', user_agent='',previous_token=''):
        with self.lock:
            if type(remember_days) is not int or remember_days not in (0, 7, 30):
                raise ValueError('记住设备期限只能为 7 天、30 天或不记住。')
            if remember_days:
                if self.remembered_path is None:
                    raise ValueError('此服务尚未启用记住设备，请选择“不记住”后登录。')
                client_key = self._client_key(client_ip, user_agent)
            if self.limited():
                return None
            if not isinstance(password, str) or len(password) > 256:
                self.failures.append(time.monotonic())
                return None
            digest = hashlib.pbkdf2_hmac('sha256', password.encode(), self.salt, 600000)
            if not hmac.compare_digest(digest, self.digest):
                self.failures.append(time.monotonic())
                return None
            now = time.time()
            token = secrets.token_urlsafe(32)
            token_key = hashlib.sha256(token.encode()).digest()
            previous_key=(hashlib.sha256(previous_token.encode()).digest()
                          if isinstance(previous_token,str) and 0<len(previous_token)<=256 else None)
            previous_in_memory=previous_key is not None and previous_key in self.sessions
            revoke_remembered=(previous_key is not None and not previous_in_memory
                               and self.remembered_path is not None)
            if remember_days or revoke_remembered:
                with closing(self._connect()) as connection, connection:
                    if revoke_remembered:
                        connection.execute('DELETE FROM remembered_sessions WHERE token_key=?',(previous_key,))
                    if remember_days:
                        # Invalid deadlines must not consume slots ahead of valid devices.
                        connection.execute('''DELETE FROM remembered_sessions WHERE expires <= ? OR password_key != ?
                            OR typeof(expires) NOT IN ('integer','real') OR expires >= ?''',
                                           (now, self.password_key, float('inf')))
                        # Reuse this browser's slot before trimming unrelated devices.
                        connection.execute('''DELETE FROM remembered_sessions WHERE token_key IN (
                            SELECT token_key FROM remembered_sessions ORDER BY expires DESC, rowid DESC LIMIT -1 OFFSET 31)''')
                        connection.execute('INSERT INTO remembered_sessions VALUES (?, ?, ?, ?)',
                                           (token_key, self.password_key, client_key, now + remember_days * 86400))
            # Required persistent changes must commit before changing memory sessions.
            if previous_in_memory:del self.sessions[previous_key]
            if remember_days:return token
            self.sessions = {k:v for k,v in self.sessions.items() if v > now}
            if len(self.sessions) >= 32:
                del self.sessions[min(self.sessions, key=self.sessions.get)]
            self.sessions[token_key] = now + 12*3600
            return token

    def valid(self, token, client_ip='', user_agent=''):
        with self.lock:
            if not isinstance(token, str) or not 0 < len(token) <= 256:
                return False
            token_key = hashlib.sha256(token.encode()).digest()
            if self.sessions.get(token_key, 0) > time.time():
                return True
            if self.remembered_path is None:
                return False
            try:
                client_key = self._client_key(client_ip, user_agent)
                with closing(self._connect()) as connection:
                    row = connection.execute('''SELECT expires FROM remembered_sessions
                        WHERE token_key = ? AND password_key = ? AND client_key = ? AND expires > ?''',
                        (token_key, self.password_key, client_key, time.time())).fetchone()
                return row is not None and type(row[0]) in (int,float) and math.isfinite(row[0])
            except (ValueError, OSError, sqlite3.Error):
                return False

    def logout(self, token):
        with self.lock:
            token_key = hashlib.sha256(token.encode()).digest()
            # Default sessions are never persisted in remembered_sessions.
            if token_key in self.sessions:
                del self.sessions[token_key]
                return
            if self.remembered_path is not None:
                with closing(self._connect()) as connection, connection:
                    connection.execute('DELETE FROM remembered_sessions WHERE token_key = ?', (token_key,))
