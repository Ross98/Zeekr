"""One visibility rule for all event consumers; old databases remain read-only."""


def has_trash(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trip_record_trash'").fetchone())


def visible_clause(db, alias='monitor_events'):
    # Aliases come only from source code, never from a request.
    if not has_trash(db):
        return '1'
    return (f'NOT EXISTS (SELECT 1 FROM trip_record_trash t '
            f'WHERE t.vehicle={alias}.vehicle AND t.event_id={alias}.id)')


def revision(db, vehicle):
    if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='trip_record_revisions' AND type='table'").fetchone():
        return 0
    row = db.execute('SELECT revision FROM trip_record_revisions WHERE vehicle=?', (vehicle,)).fetchone()
    return row[0] if row else 0
