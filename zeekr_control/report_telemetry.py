"""Versioned, conservative report telemetry. Pure: no I/O or network."""
from .summary import section
from .vehicle_state import decode, numeric

DECODER_VERSION = 'we86-v2-ac'
SIDES = ('Driver', 'Passenger', 'DriverRear', 'PassengerRear')
POSITIONS = ('左前', '右前', '左后', '右后')
PENDING_CAPABILITIES = frozenset(('target_soc', 'connector_state', 'stop_reason',
                                  'pack_temperature', 'hood', 'unlocked', 'openings'))
CAPABILITIES = {key: {'status': 'pending_evidence', 'paths': (), 'decoder': None,
                      'vehicle_scope': 'current_vehicle_only'} for key in PENDING_CAPABILITIES}
CAPABILITIES.update({'dc_charging': {'status': 'enabled',
    'paths': ('additionalVehicleStatus.electricVehicleStatus.chargeLidDcAcStatus',
              'additionalVehicleStatus.electricVehicleStatus.chargerState',
              'additionalVehicleStatus.electricVehicleStatus.dcChargeSts',
              'additionalVehicleStatus.electricVehicleStatus.dcChargePileUAct',
              'additionalVehicleStatus.electricVehicleStatus.dcChargePileIAct'),
    'decoder': DECODER_VERSION, 'vehicle_scope': 'current_vehicle_only'}})
CAPABILITIES['ac_charging'] = {'status': 'enabled',
    'paths': tuple('additionalVehicleStatus.electricVehicleStatus.' + key for key in (
        'chargeLidAcStatus', 'chargeLidDcAcStatus', 'chargeSts', 'chargerState',
        'statusOfChargerConnection', 'chargeUAct', 'chargeIAct', 'dcChargeSts',
        'dcChargePileIAct', 'ptReady')),
    'decoder': DECODER_VERSION, 'vehicle_scope': 'current_vehicle_only'}


def capability_registry():
    """Return declarative data only; notes/free-form formulas are never executed."""
    return {key: dict(value) for key, value in CAPABILITIES.items()}


def _metric(value, unit, state_time, minimum=None, maximum=None, *, capability='enabled',
            origin='vehicle', field_time=None, source=(), time_validity=None):
    parsed = numeric(value, minimum, maximum) if capability == 'enabled' else None
    validity = time_validity or ('valid' if parsed is not None else ('unverified' if capability == 'pending_evidence' else 'missing'))
    if validity == 'invalid': parsed = None
    return {'value': parsed, 'unit': unit, 'source_paths': list(source), 'origin': origin,
            'capability': capability, 'validity': validity, 'state_time': state_time,
            'field_time': field_time, 'time_basis': 'field_time' if field_time is not None else 'envelope_time',
            'decoder_version': DECODER_VERSION, 'reason': None if parsed is not None else validity}


def normalize(raw, observed_at, capabilities=(), active_codes=(), stopped_codes=()):
    """Normalize one accepted vehicle observation without guessing reverse enums."""
    extra = section(raw.get('additionalVehicleStatus'))
    electric = section(extra.get('electricVehicleStatus'))
    maintenance = section(extra.get('maintenanceStatus'))
    climate = section(extra.get('climateStatus'))
    safety = section(extra.get('drivingSafetyStatus'))
    point = decode(raw, active_codes, stopped_codes)
    state_time = int(point['time']) if point['time'] is not None else None
    temp_time = numeric(climate.get('temperatureUpdateTime'), 1, 32503680000000)
    temp_validity = None
    if temp_time is not None and state_time is not None:
        age = state_time - temp_time
        temp_validity = 'invalid' if age < -30000 else 'stale' if age > 180000 else 'valid'
    enabled = {name for name in capabilities if CAPABILITIES.get(name, {}).get('status') == 'enabled'}
    closures = {}
    for label, prefix, container in (('doors', 'doorOpenStatus', safety), ('windows', 'winPos', climate)):
        values = []
        for side in SIDES:
            raw_value = numeric(container.get(prefix + side), 0, 1e9)
            values.append('closed' if raw_value == 0 else 'unknown')
        closures[label] = values
    locked = (numeric(safety.get('centralLockingStatus')) == 2 and
              all(numeric(safety.get('doorLockStatus' + side)) == 1 for side in SIDES))
    voltage = _metric(electric.get('dcChargePileUAct'), 'V', state_time, 0, 1500,
                      source=('additionalVehicleStatus.electricVehicleStatus.dcChargePileUAct',))
    current = _metric(electric.get('dcChargePileIAct'), 'A', state_time, -2000, 2000,
                      source=('additionalVehicleStatus.electricVehicleStatus.dcChargePileIAct',))
    ac_voltage = _metric(electric.get('chargeUAct'), 'V', state_time, 0, 1500,
                         source=('additionalVehicleStatus.electricVehicleStatus.chargeUAct',))
    ac_current = _metric(electric.get('chargeIAct'), 'A', state_time, -2000, 2000,
                         source=('additionalVehicleStatus.electricVehicleStatus.chargeIAct',))
    power = None
    if point['charging'] is True and point['charging_mode'] == 'dc' and voltage['value'] and current['value'] and current['value'] > 0:
        power = voltage['value'] * current['value'] / 1000
    return {'schema_version': 2, 'decoder_version': DECODER_VERSION, 'state_time': state_time,
            'observed_at': observed_at, 'soc': point['soc'], 'odometer': point['km'],
            'speed': point['speed'], 'off': point['off'], 'charging': point['charging'],
            'charging_mode': point['charging_mode'],
            'range_km': numeric(electric.get('distanceToEmptyOnBatteryOnly'), 0),
            'closures': closures, 'locked': True if locked else None,
            'trunk': 'closed' if numeric(safety.get('trunkOpenStatus')) == 0 else 'unknown',
            'ac_lid': 'open' if numeric(electric.get('chargeLidAcStatus')) == 1 else 'closed' if numeric(electric.get('chargeLidAcStatus')) == 2 else 'unknown',
            'dc_lid': 'open' if numeric(electric.get('chargeLidDcAcStatus')) == 1 else 'closed' if numeric(electric.get('chargeLidDcAcStatus')) == 2 else 'unknown',
            'inside_temp': _metric(climate.get('interiorTemp'), '°C', state_time, -80, 100, field_time=temp_time, time_validity=temp_validity),
            'outside_temp': _metric(climate.get('exteriorTemp'), '°C', state_time, -80, 100, field_time=temp_time, time_validity=temp_validity),
            'tyres': [{'position': name,
                       'pressure': _metric(maintenance.get('tyreStatus' + side), 'kPa', state_time, 0),
                       'temperature': _metric(maintenance.get('tyreTemp' + side), '°C', state_time, -80, 150)}
                      for side, name in zip(SIDES, POSITIONS)],
            'voltage': voltage, 'current': current, 'power_kw': power,
            'ac_voltage': ac_voltage, 'ac_current': ac_current,
            'remaining_minutes': numeric(electric.get('timeToFullyCharged'), 0, 2046) if point['charging'] is True else None,
            'capabilities': {name: ('enabled' if name in enabled else 'pending_evidence') for name in PENDING_CAPABILITIES}}
