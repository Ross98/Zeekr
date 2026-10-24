"""Read-only movement barriers based on vehicle time, with unknown-time fallback."""
from .analysis_cancel import check_cancelled
from .usage_events import MAX_SUMMARY_BYTES


def trip_start_between(db, vehicle, lower, upper, *, upper_inclusive=False,
                       unknown_lower_inclusive=False):
    """Reject stationary inference when movement contradicts its time window.

    A valid vehicle timestamp takes precedence over the service write timestamp.
    Unreadable timestamps retain each caller's conservative write-window policy.
    """
    check_cancelled()
    upper_op = '<=' if upper_inclusive else '<'
    unknown_lower_op = '>=' if unknown_lower_inclusive else '>'
    row = db.execute(
        'WITH starts AS (SELECT created, CASE WHEN length(CAST(summary AS BLOB))<=? THEN '
        "CASE WHEN json_valid(summary) THEN CASE WHEN json_type(summary,'$.start_time') IN ('integer','real') "
        "AND json_extract(summary,'$.start_time') BETWEEN 1 AND 32503680000000 "
        "THEN json_extract(summary,'$.start_time') END END END AS stamp "
        "FROM monitor_events WHERE vehicle=? AND kind='trip_start') "
        f'SELECT 1 FROM starts WHERE (stamp>? AND stamp{upper_op}?) '
        f'OR (stamp IS NULL AND created{unknown_lower_op}? AND created{upper_op}?) LIMIT 1',
        (MAX_SUMMARY_BYTES,vehicle,lower,upper,lower,upper)).fetchone()
    return row is not None


def trip_movement_between(db, vehicle, lower, upper, *, exclude_event_ids=(),
                          unknown_lower_inclusive=False):
    """Check an open parking window against starts and completed-trip spans.

    Explicit review anchors are excluded by identity. Other trips that overlap
    the window invalidate a review even if both endpoints lie outside it.
    """
    if trip_start_between(db, vehicle, lower, upper, unknown_lower_inclusive=unknown_lower_inclusive):
        return True
    check_cancelled()
    excluded = {f'excluded_{index}': identity for index, identity in enumerate(exclude_event_ids)}
    exclusion = ' AND id NOT IN ('+','.join(':'+key for key in excluded)+')' if excluded else ''
    unknown_lower_op = '>=' if unknown_lower_inclusive else '>'
    row = db.execute(
        'WITH encoded AS (SELECT created,CASE WHEN length(CAST(summary AS BLOB))<=:maximum '
        'THEN CASE WHEN json_valid(summary) THEN summary END END AS summary '
        "FROM monitor_events WHERE vehicle=:vehicle AND kind='trip_end'"+exclusion+'), '
        'timed AS (SELECT created, '
        "CASE WHEN json_type(summary,'$.start_time') IN ('integer','real') "
        "AND json_extract(summary,'$.start_time') BETWEEN 1 AND 32503680000000 "
        "THEN json_extract(summary,'$.start_time') END AS start_time, "
        "CASE WHEN json_type(summary,'$.end_time') IN ('integer','real') "
        "AND json_extract(summary,'$.end_time') BETWEEN 1 AND 32503680000000 "
        "THEN json_extract(summary,'$.end_time') END AS end_time FROM encoded) "
        'SELECT 1 FROM timed WHERE (start_time>:lower AND start_time<:upper) '
        'OR (end_time>:lower AND end_time<:upper) '
        'OR (start_time<=:lower AND end_time>=:upper) '
        'OR ((start_time IS NULL OR end_time IS NULL OR end_time<start_time) '
        f'AND created{unknown_lower_op}:lower AND created<:upper) LIMIT 1',
        dict(maximum=MAX_SUMMARY_BYTES,vehicle=vehicle,lower=lower,upper=upper,**excluded)).fetchone()
    return row is not None
