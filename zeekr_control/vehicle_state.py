"""Shared cached-vehicle interpretation for monitoring and dashboard display."""
from .summary import number, section


def numeric(value, minimum=0, maximum=1e9):
    result = number(value, minimum, maximum)
    return float(result) if result is not None else None


def decode(raw, active_codes=(), stopped_codes=()):
    basic = section(raw.get('basicVehicleStatus'))
    extra = section(raw.get('additionalVehicleStatus'))
    electric = section(extra.get('electricVehicleStatus'))
    maintenance = section(extra.get('maintenanceStatus'))
    valid_speed = basic.get('speedValidity') is True or basic.get('speedValidity') == 'true'
    speed = numeric(basic.get('speed'), 0, 400) if valid_speed else None
    engine = basic.get('engineStatus')
    ready = numeric(electric.get('ptReady'), 0, 1)
    off = True if engine == 'engine_off' and ready == 0 else (
        False if engine in ('engine_on', 'engine_running') or ready == 1 else None)
    code = str(electric.get('chargeSts', '')).strip().lower()
    idle = all(number(electric.get(k)) == 0 for k in ('chargeSts', 'chargerState', 'statusOfChargerConnection'))
    dc_lid_open = number(electric.get('chargeLidDcAcStatus')) == 1
    dc_status = number(electric.get('dcChargeSts'))
    pile_voltage = numeric(electric.get('dcChargePileUAct'), 0, 1500)
    pile_current = numeric(electric.get('dcChargePileIAct'), -2000, 2000)
    dc_evidence = (dc_status is not None and dc_status != 0) or (pile_current is not None and pile_current != 0)
    dc_invalid = any(electric.get(k) is not None and value is None for k, value in (
        ('dcChargeSts', dc_status), ('dcChargePileUAct', pile_voltage), ('dcChargePileIAct', pile_current)))
    verified_dc = (dc_lid_open and number(electric.get('chargerState')) == 24 and dc_status == 12
                   and pile_voltage is not None and pile_voltage > 0
                   and pile_current is not None and pile_current > 0)
    verified_stopped = (dc_lid_open and number(electric.get('chargerState')) == 26
                        and dc_status == 10 and pile_current == 0 and not dc_invalid
                        and not (speed is not None and speed > 0) and off is not False)
    charging = None
    # Owner-confirmed DC combination takes priority over generic zero codes.
    # AC lid opening and other numeric states are not yet calibrated.
    if verified_dc:
        charging = True
    elif verified_stopped:
        charging = False
    elif not dc_evidence and not dc_invalid:
        if dc_lid_open and code in set(active_codes) | {'charging', 'inprogress'}:
            charging = True
        elif idle or code in set(stopped_codes) | {'stopped', 'finished', 'complete', 'completed', 'notcharging'}:
            charging = False
    if charging is True and ((speed is not None and speed > 0) or off is False):
        charging = None  # Conflicting drive-ready evidence requires calibration.
    return {'time': numeric(raw.get('updateTime'), 1, 32503680000000),
            'speed': speed, 'off': off, 'charging': charging,
            'charging_phase': 'stopped' if verified_stopped else 'active' if charging is True else 'idle' if charging is False else 'unknown',
            'charging_mode': 'dc' if charging is True and verified_dc else None,
            'soc': numeric(electric.get('chargeLevel'), 0, 100),
            'km': numeric(maintenance.get('odometer')),
            'signals': {k: str(electric.get(k, '缺失'))[:40] for k in
                        ('chargeSts', 'chargerState', 'statusOfChargerConnection', 'ptReady',
                         'chargeLidAcStatus', 'chargeLidDcAcStatus', 'dcChargeSts',
                         'dcChargePileUAct', 'dcChargePileIAct')}}
