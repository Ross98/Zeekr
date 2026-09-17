"""Offline browser fixture. Never reads the owner's session or vehicle."""
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zeekr_control.storage import save
from zeekr_control.web import App, make_server


class FixtureClient:
    def __init__(self, session):
        pass

    def vehicles(self):
        return [{'vin': 'L6T79X2Z0NP000001'}]

    def status(self, vin):
        import time
        now = int(time.time() * 1000)
        safety = {'centralLockingStatus': 2, 'trunkOpenStatus': 0, 'engineHoodOpenStatus': 0}
        climate = {'interiorTemp': 25.6, 'exteriorTemp': 23.1, 'temperatureUpdateTime': now - 7200000,
                   'sunroofPos': 101, 'climateOverHeatProActive': True, 'steerWhlHeatingSts': 2}
        maintenance = {'odometer': 12560, 'mainBatteryStatus': {'chargeLevel': 96, 'voltage': 12.5},
                       'daysToService': 240, 'distanceToService': 11000}
        for side in ('Driver', 'Passenger', 'DriverRear', 'PassengerRear'):
            safety['doorLockStatus' + side] = 1
            safety['doorOpenStatus' + side] = 0
            climate['winPos' + side] = 0
            maintenance['tyreStatus' + side] = 265.125
            maintenance['tyreTemp' + side] = 27
        return {'updateTime': now - 1200000,
                'position': {'latitude': 111600000, 'longitude': 435600000,
                             'posCanBeTrusted': False, 'marsCoordinates': False},
                'additionalVehicleStatus': {'drivingSafetyStatus': safety, 'climateStatus': climate,
                    'pollutionStatus': {'interiorPM25': 15, 'interiorPM25Level': 0},
                    'maintenanceStatus': maintenance,
                    'electricVehicleStatus': {'chargeLevel': 64, 'distanceToEmptyOnBatteryOnly': 302,
                        'chargeSts': 0, 'chargerState': 0, 'statusOfChargerConnection': 0,
                        'chargeUAct': 0, 'timeToFullyCharged': 2047, 'averPowerConsumption': 14.8}}}


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        session = Path(directory) / 'private' / 'session.json'
        save(session, {'accessToken': 'TEST-ONLY', 'userId': 'TEST-ONLY'})
        app = App(session, client_factory=FixtureClient)
        server = make_server(app, 0)
        print(server.server_port, flush=True)
        try:
            server.serve_forever()
        finally:
            app.close()
            server.server_close()
