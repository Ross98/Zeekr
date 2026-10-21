"""Conservative parking labels from nearby trusted history; never GPS repair."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zeekr_control.personal_store import PersonalStore
from zeekr_control.trip_place_names import TripPlaceNames
from zeekr_control.parking_place_reference import parking_place_reference

T=1792546125053
class ParkingReferenceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name);root.chmod(0o700)
        self.store=PersonalStore(root/'personal.sqlite3');self.names=TripPlaceNames(self.store)
        self.store.change('owner','car','place_names','save','home',dict(name='住所',latitude=31.2,longitude=121.4,radius_m=75),0)
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE observations(id INTEGER PRIMARY KEY,vehicle TEXT,state_time INTEGER,observed_time INTEGER,location TEXT)')
        self.rule=dict(deleted=False,home=dict(latitude=31.2,longitude=121.4,radius_m=500),work=None)
        self.event=dict(start_time=T,end_time=T+3600000,parking_status='parked',p_gear_samples=3,reasons=['gap'])
        self.add(T-120000,31.2,True)
        self.add(T,31.2014,False)
        self.add(T+60000,31.2014,False)
    def add(self,t,lat,trusted,**extra):
        point=dict(valid=True,plottable=True,latitude=lat,longitude=121.4,trusted=trusted,coordinate_system='WGS84（社区解释）');point.update(extra)
        self.db.execute('INSERT INTO observations(vehicle,state_time,observed_time,location) VALUES(?,?,?,?)',('car',t,t+2000,json.dumps(point)))
    def result(self):
        return parking_place_reference(self.db,'car',self.event,self.names,'owner',self.names.regions('owner','car'),self.rule)
    def test_recent_anchor_and_same_commute_region_keep_reference_provenance(self):
        point,evidence=self.result()
        self.assertEqual(point['label'],'住所')
        self.assertEqual(point['statistics_key'],'region:home')
        self.assertEqual(point['latitude'],31.2014)
        self.assertEqual(evidence['source'],'parking_reference')
        self.assertEqual(evidence['sampling_gap_seconds'],120)
        self.assertGreater(evidence['distance_m'],150)
        self.assertNotIn('trusted',point)
        self.assertFalse(json.loads(self.db.execute('SELECT location FROM observations WHERE state_time=?',(T,)).fetchone()[0])['trusted'])
    def test_old_anchor_no_p_gear_movement_location_conflict_or_candidate_are_rejected(self):
        for change in [dict(parking_status='candidate'),dict(p_gear_samples=1),dict(reasons=['movement']),dict(reasons=['location'])]:
            with self.subTest(change=change):
                original=self.event.copy();self.event.update(change);self.assertIsNone(self.result());self.event=original
        self.db.execute('UPDATE observations SET state_time=? WHERE state_time=?',(T-181000,T-120000));self.assertIsNone(self.result())
    def test_unknown_region_and_same_label_different_regions_are_rejected(self):
        self.rule=dict(deleted=False,home=None,work=None)
        self.assertIsNone(self.result())
        self.store.change('owner','car','place_names','save','other',dict(name='住所',latitude=31.2014,longitude=121.4,radius_m=50),1)
        self.assertIsNone(self.result())
    def test_overlapping_regions_are_rejected(self):
        self.store.change('owner','car','place_names','save','overlap',dict(name='隔壁',latitude=31.2,longitude=121.4,radius_m=100),1)
        self.assertIsNone(self.result())
    def test_charge_confirmation_disambiguates_only_its_region_without_relaxing_gps(self):
        # Two circles cover both coordinates; an explicit charge confirmation can
        # select one, while automatic naming remains ambiguous.
        self.store.change('owner','car','place_names','save','home',dict(name='住所',latitude=31.2007,longitude=121.4,radius_m=150),1)
        self.store.change('owner','car','place_names','save','overlap',dict(name='隔壁',latitude=31.2007,longitude=121.4,radius_m=150),2)
        self.assertIsNone(self.result())
        regions=self.names.regions('owner','car')
        point,evidence=parking_place_reference(self.db,'car',self.event,self.names,'owner',regions,self.rule,confirmed_region=(next(r for r in regions if r['id']=='home'),'confirmed-charge'))
        self.assertEqual(point['label'],'住所')
        self.assertEqual(evidence['confirmation_event_id'],'confirmed-charge')
        self.assertEqual(evidence['source'],'parking_reference')
        self.db.execute('UPDATE observations SET state_time=? WHERE state_time=?',(T-181000,T-120000))
        self.assertIsNone(parking_place_reference(self.db,'car',self.event,self.names,'owner',regions,self.rule,confirmed_region=(next(r for r in regions if r['id']=='home'),'confirmed-charge')))

    def test_missing_unplottable_stale_or_changing_parking_coordinates_are_rejected(self):
        self.db.execute('DELETE FROM observations WHERE state_time>=?',(T,));self.assertIsNone(self.result())
        self.add(T,31.2014,False,plottable=False);self.assertIsNone(self.result())
        self.db.execute('DELETE FROM observations WHERE state_time>=?',(T,));self.add(T,31.2014,False)
        self.db.execute('UPDATE observations SET observed_time=state_time+600000 WHERE state_time=?',(T,));self.assertIsNone(self.result())
        self.db.execute('UPDATE observations SET observed_time=state_time+2000 WHERE state_time=?',(T,));self.add(T+60000,31.2020,False);self.assertIsNone(self.result())
    def test_distant_anchor_is_rejected_even_in_large_named_area(self):
        self.db.execute('DELETE FROM observations WHERE state_time>=?',(T,));self.add(T,31.2035,False)
        self.assertIsNone(self.result())
    def test_window_and_limit_do_not_skip_dense_uncertain_boundaries(self):
        for index in range(129):self.add(T+index,31.2014,False)
        self.assertIsNone(self.result())
