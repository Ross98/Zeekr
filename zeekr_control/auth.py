"""Single-user password authentication; bounded in-memory sessions and throttling."""
import hashlib
import hmac
import secrets
import threading
import time


def password_record(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return {'salt': salt, 'digest': digest}


class WebAuth:
    def __init__(self, record):
        self.salt = bytes.fromhex(record['salt'])
        self.digest = bytes.fromhex(record['digest'])
        if len(self.salt) != 16 or len(self.digest) != 32:
            raise ValueError('Invalid password record')
        self.sessions = {}
        self.failures = []
        self.lock = threading.RLock()

    def limited(self):
        with self.lock:
            self.failures = [t for t in self.failures if time.time() - t < 300]
            return len(self.failures) >= 5

    def login(self, password):
        with self.lock:
            if self.limited():
                return None
            if not isinstance(password, str) or len(password) > 256:
                self.failures.append(time.time())
                return None
            digest = hashlib.pbkdf2_hmac('sha256', password.encode(), self.salt, 600000)
            if not hmac.compare_digest(digest, self.digest):
                self.failures.append(time.time())
                return None
            now = time.time()
            self.sessions = {k:v for k,v in self.sessions.items() if v > now}
            if len(self.sessions) >= 32:
                del self.sessions[min(self.sessions, key=self.sessions.get)]
            token = secrets.token_urlsafe(32)
            self.sessions[hashlib.sha256(token.encode()).digest()] = now + 12*3600
            return token

    def valid(self, token):
        with self.lock:
            return self.sessions.get(hashlib.sha256(token.encode()).digest(), 0) > time.time()

    def logout(self, token):
        with self.lock:
            self.sessions.pop(hashlib.sha256(token.encode()).digest(), None)
