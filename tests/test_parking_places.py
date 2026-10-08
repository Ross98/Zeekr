"""Parking names require parking evidence and the current owner's saved regions."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from zeekr_control.parking_analytics import ParkingAnalytics
from zeekr_control.personal_store import PersonalStore
from zeekr_control.tracks import day_bounds


class ParkingPlaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        root.chmod(0o700)
        self.database = root / 'tracks.sqlite3'
        self.store = PersonalStore(root / 'personal.sqlite3')
        self.lower, _ = day_bounds('2026-09-20')
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE monitor_events(id TEXT,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
            for identity, start, end, soc in [('a', 0, 5, 70), ('b', 20, 25, 69)]:
                body = dict(start_time=self.lower+start*60000, end_time=self.lower+end*60000,
                            start_soc=soc, end_soc=soc, duration_seconds=300, partial=False)
                db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',
                           (identity, 'car', 'trip_end', json.dumps(body), body['end_time']))
        self.database.chmod(0o600)
        self.raw = dict(position=dict(latitude=108000000, longitude=432000000,
                                      marsCoordinates=False, posCanBeTrusted=True),
                        basicVehicleStatus=dict(engineStatus='engine_off', speed=0, speedValidity=True),
                        additionalVehicleStatus=dict(electricVehicleStatus=dict(ptReady=0, chargeLevel=70,
                            chargeSts=0, chargerState=0, statusOfChargerConnection=0),
                            maintenanceStatus=dict(odometer=100)))
        outer = self
        class Archive:
            def iter_records(self, scope, vehicle, lower, upper):
                for minute in (5, 10, 15, 20):
                    stamp = outer.lower + minute*60000
                    raw = dict(outer.raw, updateTime=stamp)
                    if lower <= stamp < upper:
                        yield dict(key=str(minute), state_time=stamp, observed_at=stamp,
                                   flags=list(outer.flags), change='new'), raw
        self.archive = Archive()
        self.flags = []

    def save_name(self, owner='owner', vehicle='car', **extra):
        body = dict(name='自家车库', latitude=30, longitude=120, radius_m=25)
        body.update(extra)
        self.store.change(owner, vehicle, 'place_names', 'save', 'garage', body, 0)

    def query(self, owner='owner', store=True):
        options = dict(store=self.store, owner=owner) if store else {}
        return ParkingAnalytics(self.archive, self.database, **options).query(
            'archive-scope', 'car', '2026-09-20', '2026-09-20', 75)['events'][0]

    def test_queries_on_either_day_share_complete_closed_and_open_stop(self):
        a, b = self.lower+23*3600000, self.lower+25*3600000
        outer = self
        class Archive:
            def time_bounds(self, scope, vehicle):
                return a, b
            def iter_records(self, scope, vehicle, lower, upper):
                for stamp in range(a, b+1, 300000):
                    if lower <= stamp < upper:
                        yield dict(key=str(stamp), state_time=stamp, observed_at=stamp,
                                   flags=[], change='new'), outer.raw
        with sqlite3.connect(self.database) as db:
            for identity, start, end in [('a',a-300000,a), ('b',b,b+300000)]:
                body = dict(start_time=start,end_time=end,start_soc=70,end_soc=70,
                            duration_seconds=300,partial=False)
                db.execute('UPDATE monitor_events SET summary=?,created=? WHERE id=?',
                           (json.dumps(body),end,identity))
        analyzer = ParkingAnalytics(Archive(), self.database)
        def query(day):
            return analyzer.query('scope','car',day,day,75)['events'][0]
        self.assertEqual(query('2026-09-20'), query('2026-09-21'))
        self.assertEqual(query('2026-09-20')['status'], 'comparable')
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM monitor_events WHERE id="b"')
        self.assertEqual(query('2026-09-20'), query('2026-09-21'))
        self.assertTrue(query('2026-09-20')['open'])
        self.assertEqual(query('2026-09-20')['end_time'], b)

    def test_date_filter_reloads_full_stop_beyond_31_days(self):
        first = self.lower-40*86400000
        with sqlite3.connect(self.database) as db:
            body = dict(start_time=first-300000, end_time=first, start_soc=70, end_soc=70,
                        duration_seconds=300, partial=False)
            db.execute('UPDATE monitor_events SET summary=?,created=? WHERE id="a"',
                       (json.dumps(body), first))
        outer = self
        class Archive:
            def iter_records(self, scope, vehicle, lower, upper):
                self_ranges.append((lower, upper))
                for stamp in (first, outer.lower, outer.lower+1200000):
                    if lower <= stamp < upper:
                        yield dict(key=str(stamp), state_time=stamp, observed_at=stamp,
                                   flags=[], change='new'), outer.raw
        self_ranges = []
        result = ParkingAnalytics(Archive(), self.database).query(
            'scope', 'car', '2026-09-20', '2026-09-20', 75)['events'][0]
        self.assertEqual(result['start_time'], first)
        self.assertEqual(result['start_trip_id'], 'a')
        self.assertEqual(result['duration_seconds'], 40*86400+1200)
        self.assertIn('gap', result['reasons'])
        self.assertTrue(all(end-start <= 33*86400000 for start,end in self_ranges))

    def arrival_reference(self, age=120, latitude=30, trusted=True, **extra):
        with sqlite3.connect(self.database) as db:
            body = json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='a'").fetchone()[0])
            body.update(end_address='示例商场', end_location_reference=dict(
                age_seconds=age, state_time=body['end_time']-age*1000,
                location=dict(latitude=latitude, longitude=120, valid=True, trusted=trusted,
                              coordinate_system='WGS84（社区解释）')))
            body.update(extra)
            db.execute("UPDATE monitor_events SET summary=? WHERE id='a'", (json.dumps(body),))

    def test_nearby_arrival_reference_names_untrusted_stop_and_preserves_energy(self):
        self.save_name()
        original = self.query()
        self.raw['position']['posCanBeTrusted'] = False
        self.arrival_reference()
        row = self.query()
        self.assertEqual(row['place_label'], '自家车库')
        self.assertEqual(row['place_confidence'], 'reference')
        self.assertEqual(row['place_reference_age_seconds'], 120)
        for key in ('id','start_time','end_time','duration_seconds','status','soc_drop','estimated_kwh','reasons'):
            self.assertEqual(row[key], original[key])
        self.assertFalse(any(key.startswith('_') for key in row))
        self.assertNotIn('latitude', row)
        self.assertEqual(self.query(owner='another')['place_label'], '示例商场附近')

    def test_trusted_parking_position_wins_over_arrival_reference(self):
        self.save_name()
        self.arrival_reference(latitude=31)
        row = self.query()
        self.assertEqual(row['place_label'], '自家车库')
        self.assertEqual(row['place_confidence'], 'observed')

    def test_reference_age_and_distance_are_bounded(self):
        self.raw['position']['posCanBeTrusted'] = False
        for age, latitude, trusted in [(301,30,True),(-1,30,True),(float('nan'),30,True),
                                       (True,30,True),(120,30.002,True),(120,30,False)]:
            with self.subTest(age=age, latitude=latitude, trusted=trusted):
                self.arrival_reference(age,latitude,trusted)
                row = self.query()
                self.assertEqual(row['place_label'], '位置未知')
                self.assertTrue(row['place_reason'])
        self.arrival_reference(age=300)
        self.assertEqual(self.query()['place_confidence'], 'reference')

    def test_arrival_reference_time_must_match_its_saved_age(self):
        self.raw['position']['posCanBeTrusted'] = False
        self.arrival_reference()
        with sqlite3.connect(self.database) as db:
            body = json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='a'").fetchone()[0])
            body['end_location_reference']['state_time'] -= 600000
            db.execute("UPDATE monitor_events SET summary=? WHERE id='a'",(json.dumps(body),))
        row = self.query()
        self.assertEqual(row['place_label'], '位置未知')
        self.assertIn('时间', row['place_reason'])

    def test_trusted_arrival_endpoint_is_a_reference_not_parking_gps(self):
        self.save_name()
        self.raw['position']['posCanBeTrusted'] = False
        self.arrival_reference(end_location=dict(latitude=30,longitude=120,valid=True,
                               trusted=True,coordinate_system='WGS84（社区解释）'))
        row = self.query()
        self.assertEqual(row['place_label'], '自家车库')
        self.assertEqual(row['place_confidence'], 'reference')
        self.assertEqual(row['place_reference_age_seconds'], 0)

    def test_reference_never_overrides_movement_or_partial_arrival(self):
        self.raw['position']['posCanBeTrusted'] = False
        self.arrival_reference(partial=True)
        self.assertEqual(self.query()['place_label'], '位置未知')
        self.arrival_reference(partial=False)
        self.raw['basicVehicleStatus']['speed'] = 2
        self.assertEqual(self.query()['place_label'], '位置未知')

    def test_reference_cannot_use_unknown_coordinate_system_or_missing_coordinates(self):
        self.raw['position']['posCanBeTrusted'] = False
        self.arrival_reference()
        self.raw['position']['marsCoordinates'] = True
        self.assertEqual(self.query()['place_label'], '位置未知')
        self.raw['position'] = {}
        self.assertEqual(self.query()['place_label'], '位置未知')

    def test_reference_location_can_be_named_despite_stale_soc_observations(self):
        self.save_name()
        self.raw['position']['posCanBeTrusted'] = False
        self.flags = ['stale']
        self.arrival_reference()
        row = self.query()
        self.assertEqual(row['place_label'], '自家车库')
        self.assertEqual(row['status'], 'uncertain')
        self.assertIsNone(row['estimated_kwh'])

    def test_unnamed_trusted_position_is_not_missing_position(self):
        row = self.query(store=False)
        self.assertEqual(row.get('place_label'), '未命名地点')

    def test_saved_name_uses_current_owner_without_current_period_trips_at_that_place(self):
        self.save_name()
        row = self.query()
        self.assertEqual(row['place_label'], '自家车库')
        self.assertEqual(row['place_source'], 'manual')
        self.assertNotIn('_location', row)
        self.assertNotIn('latitude', row)
        self.assertEqual(self.query(owner='another')['place_label'], '未命名地点')

    def test_saved_radius_is_respected(self):
        self.save_name(latitude=30.0005)
        self.assertEqual(self.query()['place_label'], '未命名地点')

    def test_polygon_match_uses_shared_region_rules(self):
        self.save_name(shape='polygon', vertices=[[29.999,119.999],[29.999,120.001],[30.001,120.001],[30.001,119.999]])
        self.assertEqual(self.query()['place_label'], '自家车库')

    def test_other_vehicle_and_deleted_names_are_not_reused(self):
        self.save_name(vehicle='other-car')
        self.assertEqual(self.query()['place_label'], '未命名地点')
        self.save_name()
        self.store.change('owner', 'car', 'place_names', 'delete', 'garage', None, 1)
        self.assertEqual(self.query()['place_label'], '未命名地点')

    def test_trusted_local_address_is_only_a_nearby_reference(self):
        with sqlite3.connect(self.database) as db:
            body = json.loads(db.execute("SELECT summary FROM monitor_events WHERE id='a'").fetchone()[0])
            body.update(end_address='示例商场', end_location=dict(latitude=30, longitude=120,
                        valid=True, trusted=True, coordinate_system='WGS84（社区解释）'))
            db.execute("UPDATE monitor_events SET summary=? WHERE id='a'", (json.dumps(body),))
        row = self.query()
        self.assertEqual(row['place_label'], '示例商场附近')
        self.assertEqual(row['place_source'], 'address')
        self.save_name()
        self.assertEqual(self.query()['place_label'], '自家车库')

    def test_untrusted_wrong_system_and_invalid_time_never_receive_saved_name(self):
        self.save_name()
        for key, value in [('posCanBeTrusted', False), ('marsCoordinates', True)]:
            with self.subTest(key=key):
                original = self.raw['position'][key]
                self.raw['position'][key] = value
                self.assertEqual(self.query()['place_label'], '位置未知')
                self.raw['position'][key] = original
        self.flags = ['stale']
        self.assertEqual(self.query()['place_label'], '位置未知')


if __name__ == '__main__':
    unittest.main()
