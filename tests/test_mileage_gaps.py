"""Missing driving remains a separate odometer interval, never a fake trip."""
import tempfile
import unittest
from pathlib import Path
from test_monitor import BASE, sample
from zeekr_control.monitor import Monitor
from zeekr_control.mileage_gaps import MileageGaps


class MileageGapTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'private'/'tracks.sqlite3'
        self.monitor=Monitor(self.path)

    def test_parked_to_parked_gap_preserves_distance_without_trip_or_duration(self):
        self.monitor.observe('car',sample(0,km=100,soc=50),BASE)
        self.monitor.observe('car',sample(3600,km=126,soc=44),BASE+3600000)
        gaps=MileageGaps(self.path.parent/'mileage-gaps.sqlite3')
        rows=gaps.between('car',BASE,BASE+7200000,BASE+7200000)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['distance_km'],26)
        self.assertEqual(rows[0]['soc_before'],50)
        self.assertEqual(rows[0]['soc_after'],44)
        self.assertNotIn('duration_seconds',rows[0])
        self.assertEqual(self.monitor.events(),[])
        self.assertEqual(gaps.between('other',BASE,BASE+7200000,BASE+7200000),[])
        self.assertEqual(gaps.between('car',BASE,BASE+7200000,BASE+1000),[])
        self.monitor.observe('car',sample(3600,km=126,soc=44),BASE+3601000)
        self.assertEqual(len(gaps.between('car',BASE,BASE+7200000,BASE+7200000)),1)

    def test_unchanged_or_reset_odometer_does_not_invent_mileage(self):
        for km in (100,99):
            self.monitor.observe('car'+str(km),sample(0,km=100),BASE)
            self.monitor.observe('car'+str(km),sample(3600,km=km),BASE+3600000)
        self.assertFalse((self.path.parent/'mileage-gaps.sqlite3').exists())

    def test_active_trip_gap_is_not_double_counted(self):
        self.monitor.observe('car',sample(0),BASE)
        self.monitor.observe('car',sample(20,km=101,speed=30,engine='engine_on',ready=1),BASE+20000)
        self.monitor.observe('car',sample(3600,km=126),BASE+3600000)
        self.assertFalse((self.path.parent/'mileage-gaps.sqlite3').exists())
