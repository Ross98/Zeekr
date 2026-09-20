"""Scalar-only evidence for activity starts; never invent an exact event time."""
import math

MAX_GAP = 180000


def timestamp(value):
    return value if type(value) in (int, float) and 0 < value <= 32503680000000 and math.isfinite(value) else None


def _seconds(later, earlier):
    return (later-earlier)/1000 if later is not None and earlier is not None and later >= earlier else None


def project(value=None):
    """Validate a stored claim and explicitly project every public field."""
    value = value if isinstance(value, dict) else {}
    first, detected, previous, previous_observed = (
        timestamp(value.get(key)) for key in
        ('first_state_time', 'detected_at', 'previous_state_time', 'previous_observed_at'))
    basis = value.get('basis')
    valid = (type(value.get('version')) is int and value['version'] == 1 and basis in ('bounded', 'first_observation')
             and first is not None and detected is not None and -30000 <= detected-first <= MAX_GAP)
    if not valid:
        first = detected = previous = previous_observed = None
        basis = 'legacy'
    state_gap = _seconds(first, previous)
    observed_gap = _seconds(detected, previous_observed)
    bounded = (basis == 'bounded' and state_gap is not None and 0 < state_gap <= MAX_GAP/1000
               and observed_gap is not None and observed_gap <= MAX_GAP/1000
               and -30000 <= previous_observed-previous <= MAX_GAP)
    if basis == 'bounded' and not bounded:
        basis = 'first_observation'
    earliest = previous if bounded else None
    age = _seconds(detected, first)
    return {'version': 1, 'basis': basis, 'actual_start_time': None,
            'earliest_time': earliest, 'latest_time': first,
            'first_state_time': first, 'detected_at': detected,
            'previous_state_time': previous, 'previous_observed_at': previous_observed,
            'state_gap_seconds': state_gap, 'observation_gap_seconds': observed_gap,
            'sample_age_seconds': age, 'delay_min_seconds': age,
            'delay_max_seconds': _seconds(detected, earliest) if age is not None else None}


def build(kind, previous, point, continuous):
    previous = previous or {}
    inactive = (previous.get('charging') is False if kind == 'charge'
                else previous.get('off') is True and previous.get('speed') == 0)
    return project({'version': 1, 'basis': 'bounded' if continuous and inactive else 'first_observation',
                    'first_state_time': point.get('time'), 'detected_at': point.get('observed'),
                    'previous_state_time': previous.get('time'),
                    'previous_observed_at': previous.get('observed')})


def from_summary(summary, kind=None):
    summary = summary if isinstance(summary, dict) else {}
    report = summary.get('report_v2')
    report = report if isinstance(report, dict) else {}
    if 'start_evidence' in summary or 'start_evidence' in report:
        return project(summary.get('start_evidence', report.get('start_evidence')))
    # Older reports already saved the first charge sample (or a moving trip
    # start). Recover only those explicit observations, never a prior boundary.
    start = report.get('start', summary.get('report_start'))
    start = start if isinstance(start, dict) else {}
    kind = kind or report.get('kind') or summary.get('kind')
    speed = start.get('speed')
    active = False
    if kind in ('charge', 'charge_start', 'charge_end'):
        active = start.get('charging') is True
    elif kind in ('trip', 'trip_end'):
        active = type(speed) in (int, float) and 0 < speed < 400
    state = timestamp(start.get('state_time'))
    activity_start = summary.get('start')
    activity_start = activity_start if isinstance(activity_start, dict) else {}
    stored_start = summary.get('start_time', report.get('start_time', activity_start.get('time', state)))
    if active and state is not None and state == timestamp(stored_start):
        return project({'version':1,'basis':'first_observation','first_state_time':state,
                        'detected_at':start.get('observed_at')})
    return project()


def comparison(summary, actual_start=None):
    """Read-only comparison with a separately supplied, measured reference."""
    evidence = from_summary(summary)
    actual = timestamp(actual_start)
    if actual_start is not None and actual is None:
        raise ValueError('实际开始时间无效。')
    start = timestamp(summary.get('start_time'))
    detected = evidence['detected_at']
    earliest, latest = evidence['earliest_time'], evidence['latest_time']
    return {'start_evidence': evidence, 'reference_available': actual is not None,
            'record_offset_seconds': (start-actual)/1000 if start is not None and actual is not None else None,
            'detection_delay_seconds': (detected-actual)/1000 if detected is not None and actual is not None else None,
            'reference_within_bounds': earliest < actual <= latest
                if earliest is not None and latest is not None and actual is not None else None}
