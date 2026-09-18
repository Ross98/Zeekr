"""Vehicle-local manual annotations. Never used by vehicle decoders or notifications."""
import json
import math
import os
from pathlib import Path
import sqlite3
import time


class FieldReviewStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS revisions (vehicle TEXT PRIMARY KEY, revision INTEGER NOT NULL)')
        db.execute('''CREATE TABLE IF NOT EXISTS reviews (vehicle TEXT, path TEXT, scope TEXT,
                      value TEXT, body TEXT NOT NULL, PRIMARY KEY(vehicle,path,scope,value))''')
        db.commit()
        return db

    def read(self, vehicle):
        if not vehicle or not self.path.exists():
            return {'vehicle': vehicle, 'revision': 0, 'records': []}
        db = self.connect()
        try:
            db.execute('BEGIN')
            return self._read(db, vehicle)
        finally:
            db.close()

    @staticmethod
    def _read(db, vehicle):
        revision = db.execute('SELECT revision FROM revisions WHERE vehicle=?', (vehicle,)).fetchone()
        records = [json.loads(row[0]) for row in db.execute(
            'SELECT body FROM reviews WHERE vehicle=? ORDER BY path,scope,value', (vehicle,))]
        return {'vehicle': vehicle, 'revision': revision[0] if revision else 0, 'records': records}

    def update(self, vehicle, data, allowed_paths):
        if not vehicle or data.get('vehicle') != vehicle:
            raise ValueError('车辆已切换，请重新选择参数。')
        if type(data.get('revision')) is not int or data['revision'] < 0:
            raise ValueError('核实记录版本无效。')
        path, scope, raw = data.get('path'), data.get('scope'), data.get('raw')
        if not isinstance(path, str) or path not in allowed_paths:
            raise ValueError('请选择参数详情页中的字段。')
        if scope not in ('value', 'field') or not isinstance(raw, str) or len(raw) > 120:
            raise ValueError('核实范围或原始值无效。')
        action = data.get('action')
        if action not in ('save', 'delete'):
            raise ValueError('核实操作无效。')
        record = {'path': path, 'scope': scope, 'raw': raw}
        if action == 'save':
            status = data.get('status')
            if status not in ('confirmed', 'question', 'na'):
                raise ValueError('核实状态无效。')
            for name, limit in (('meaning', 200), ('unit', 40), ('conversion', 200),
                                ('observation', 600), ('scene', 200), ('note', 1200)):
                value = data.get(name, '')
                if not isinstance(value, str) or len(value) > limit:
                    raise ValueError('核实内容过长或格式无效。')
                record[name] = value.strip()
            observed = data.get('observed_at')
            if observed is not None and (type(observed) is not int or not 0 <= observed <= 9999999999999):
                raise ValueError('观测时间无效。')
            if status == 'confirmed':
                if not record['meaning'] or raw in ('未知', ''):
                    raise ValueError('请填写确认含义；缺失值不能确认。')
                if scope == 'field':
                    try:
                        valid = math.isfinite(float(raw))
                    except ValueError:
                        valid = False
                    if not valid:
                        raise ValueError('字段级确认仅用于数值参数，枚举请按具体值确认。')
            record.update(status=status, observed_at=observed, saved_at=int(time.time() * 1000))
        db = self.connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                current = self._read(db, vehicle)
                if current['revision'] != data['revision']:
                    raise ValueError('核实记录已有更新，请同步记录后重试；填写内容保留。')
                key = (vehicle, path, scope, raw if scope == 'value' else '')
                if action == 'delete':
                    db.execute('DELETE FROM reviews WHERE vehicle=? AND path=? AND scope=? AND value=?', key)
                else:
                    db.execute('INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?)',
                               (*key, json.dumps(record, ensure_ascii=False)))
                db.execute('INSERT OR REPLACE INTO revisions VALUES (?,?)', (vehicle, current['revision'] + 1))
                return self._read(db, vehicle)
        finally:
            db.close()
