"""Measured references stay separate from cached samples and stored records."""
import unittest
import json
from pathlib import Path
import tempfile
from zeekr_control.start_evidence import build, comparison
from zeekr_control.start_audit import audit, reference_time
from zeekr_control.monitor import Monitor
from zeekr_control.storage import save
from test_monitor import BASE


class StartAuditTests(unittest.TestCase):
    def test_measured_reference_does_not_become_a_vehicle_event(self):
        evidence = build('trip', {'time':BASE,'observed':BASE+5000,'off':True,'speed':0},
                         {'time':BASE+60000,'observed':BASE+80000}, True)
        summary = {'start_time':BASE,'start_evidence':evidence}
        result = comparison(summary, BASE+40000)
        self.assertEqual(result['record_offset_seconds'], -40)
        self.assertEqual(result['detection_delay_seconds'], 40)
        self.assertTrue(result['reference_within_bounds'])
        self.assertIsNone(result['start_evidence']['actual_start_time'])
        self.assertNotIn('actual_start_time', summary)

    def test_missing_reference_is_unknown_and_conflicts_are_visible(self):
        evidence = build('charge', {'time':BASE,'observed':BASE,'charging':False},
                         {'time':BASE+60000,'observed':BASE+80000}, True)
        summary = {'start_time':BASE+60000,'start_evidence':evidence}
        result = comparison(summary)
        self.assertFalse(result['reference_available'])
        self.assertIsNone(result['detection_delay_seconds'])
        self.assertIsNone(result['reference_within_bounds'])
        self.assertFalse(comparison(summary, BASE+90000)['reference_within_bounds'])
        self.assertEqual(comparison(summary, BASE+90000)['detection_delay_seconds'], -10)

    def test_legacy_record_can_compare_offset_but_not_detection(self):
        result = comparison({'start_time':BASE+300000}, BASE+30000)
        self.assertEqual(result['record_offset_seconds'], 270)
        self.assertIsNone(result['detection_delay_seconds'])
        for invalid in (True, float('inf'), 0, 'yesterday'):
            with self.assertRaises(ValueError):
                comparison({}, invalid)

    def test_audit_filters_vehicle_preserves_bytes_and_requires_reference_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'private'
            save(root/'monitor-binding.json', {'vehicle_key':'car-a'})
            monitor = Monitor(root/'tracks.sqlite3')
            evidence = build('charge', {'time':BASE,'observed':BASE,'charging':False},
                             {'time':BASE+60000,'observed':BASE+80000}, True)
            summary = {'start_time':BASE+60000,'end_time':BASE+120000,'duration_seconds':60,
                       'partial':False,'start_evidence':dict(evidence, secret='PRIVATE'),
                       'location':{'latitude':31},'raw':'PRIVATE'}
            with monitor.tracks.connect() as db:
                for vehicle in ('car-a','car-b'):
                    db.execute('INSERT INTO monitor_events (id,vehicle,kind,summary,message,created) VALUES (?,?,?,?,?,?)',
                               (vehicle+'-event',vehicle,'charge_end',json.dumps(summary),'PRIVATE',BASE+150000))
            before = (root/'tracks.sqlite3').read_bytes()
            result = audit(root, now=BASE+200000)
            self.assertEqual(result['record_count'],1)
            self.assertEqual(result['sample_age_p95_seconds'],20)
            self.assertNotIn('PRIVATE',json.dumps(result))
            self.assertNotIn('latitude',json.dumps(result))
            checked = audit(root,event='car-a-event',actual_start=BASE+30000)
            self.assertEqual(checked['records'][0]['detection_delay_seconds'],50)
            self.assertEqual(checked['reference_source'],'user_supplied')
            self.assertEqual((root/'tracks.sqlite3').read_bytes(),before)
            with self.assertRaises(ValueError):
                audit(root,event='car-b-event')
            with self.assertRaises(ValueError):
                audit(root,actual_start=BASE)

    def test_reference_requires_timezone(self):
        import argparse
        self.assertEqual(reference_time('2024-01-01T08:00:00+08:00'), BASE)
        with self.assertRaises(argparse.ArgumentTypeError):
            reference_time('2024-01-01T08:00:00')
