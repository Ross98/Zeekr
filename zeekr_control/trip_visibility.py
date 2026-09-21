"""One visibility rule for all event consumers; old databases remain read-only."""


def has_trash(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trip_record_trash'").fetchone())


def has_charge_trash(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='charge_record_trash'").fetchone())


def visible_clause(db, alias='monitor_events'):
    # Aliases come only from source code, never from a request.
    clauses = []
    if has_trash(db):
        clauses.append(f'NOT EXISTS (SELECT 1 FROM trip_record_trash t '
                       f'WHERE t.vehicle={alias}.vehicle AND t.event_id={alias}.id)')
    if has_charge_trash(db):
        clauses.append(f'NOT EXISTS (SELECT 1 FROM charge_record_trash c '
                       f'WHERE c.vehicle={alias}.vehicle AND c.event_id={alias}.id)')
    if not clauses:
        return '1'
    return ' AND '.join(clauses)


def revision(db, vehicle):
    if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='trip_record_revisions' AND type='table'").fetchone():
        return 0
    row = db.execute('SELECT revision FROM trip_record_revisions WHERE vehicle=?', (vehicle,)).fetchone()
    return row[0] if row else 0


def charge_revision(db, vehicle):
    if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='charge_record_revisions' AND type='table'").fetchone():
        return 0
    row = db.execute('SELECT revision FROM charge_record_revisions WHERE vehicle=?', (vehicle,)).fetchone()
    return row[0] if row else 0
