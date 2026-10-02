"""Offline report preview. Never constructs a client or sender."""
import json
from pathlib import Path
import sqlite3

from .report_render import render


def preview(database_path=None, event_id=None, fixture_path=None, target_bytes=1900):
    if fixture_path:
        payload = json.loads(Path(fixture_path).read_text())
        kind, report = payload['kind'], payload['report_v2']
        identity, address = payload.get('id', 'synthetic000000'), payload.get('address')
    else:
        if not database_path or not event_id:
            raise ValueError('需指定合成fixture或私有事件编号')
        db = sqlite3.connect('file:%s?mode=ro' % Path(database_path).resolve(), uri=True)
        try:
            row = db.execute('SELECT kind,summary FROM monitor_events WHERE id=?', (event_id,)).fetchone()
        finally:
            db.close()
        if not row: raise ValueError('未找到事件')
        kind, payload = row[0], json.loads(row[1])
        report, identity = payload.get('report_v2'), event_id
        if not report: raise ValueError('事件没有v2报告')
        address = {'start': payload.get('start_address'), 'end': payload.get('end_address')}
    if type(target_bytes) is not int or not 256 <= target_bytes <= 1900:
        raise ValueError('预览目标字节应为256–1900')
    references = {prefix: payload.get(prefix + '_location_reference') for prefix in ('start', 'end')}
    text, omitted = render(kind, report, identity, address, target=target_bytes, references=references)
    return {'text': text, 'utf8_bytes': len(text.encode()), 'omitted': omitted}
