import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from zeekr_control.notifications import DeliveryError
from zeekr_control.periodic_report import PeriodicDelivery, demo_report
from zeekr_control.periodic_schedule import ScheduledReports
from zeekr_control.snapshot_archive import BEIJING
from zeekr_control.storage import save


def stamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=BEIJING).timestamp() * 1000)


def report(period='day', trips=0, charges=0):
    result = demo_report(period)
    result.pop('demo')
    result['metrics'].update(trip_count=trips, charge_count=charges, distance_km=0)
    if not trips:
        result['metrics'].update(duration_seconds=0, trip_estimated_kwh=0)
    return result


class IdleDailyReportTests(unittest.TestCase):
    def test_idle_day_sends_one_short_text_and_never_prepares_image(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'reports.sqlite3'
            sender, renderer = Mock(), Mock()
            first = PeriodicDelivery(path, renderer).deliver('owner', 'car', report(), sender)
            self.assertEqual((first['text'], first['image']), ('sent', 'skipped'))
            # A restart and changed incoming data cannot replay a frozen idle report.
            PeriodicDelivery(path, renderer).deliver('owner', 'car', report(trips=1), sender)
            sender.send_markdown.assert_called_once()
            text = sender.send_markdown.call_args.args[0]
            self.assertIn('2026/10/07', text)
            self.assertIn('未记录到行程或充电', text)
            self.assertNotIn('估算耗电', text)
            self.assertLessEqual(len(text.splitlines()), 2)
            renderer.render.assert_not_called()
            sender.send_image.assert_not_called()
            self.assertEqual(first['image_attempts'], 0)

    def test_missing_observation_does_not_claim_car_was_unused(self):
        with tempfile.TemporaryDirectory() as folder:
            idle = report()
            idle['quality'].update(observed_days=0, archive_limited=True)
            sender = Mock()
            result = PeriodicDelivery(Path(folder) / 'reports.sqlite3', Mock()).deliver('owner', 'car', idle, sender)
            self.assertEqual(result['image'], 'skipped')
            self.assertIn('数据不完整', sender.send_markdown.call_args.args[0])
            self.assertIn('不能据此确认车辆未使用', sender.send_markdown.call_args.args[0])

    def test_legacy_pending_image_is_skipped_using_stored_report(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'reports.sqlite3'
            sender, renderer = Mock(), Mock()
            delivery = PeriodicDelivery(path, renderer)
            delivery.deliver('owner', 'car', report(), sender)
            # Simulate an idle report whose text was sent by the previous version.
            with delivery.connect() as db, db:
                db.execute("UPDATE reports SET image='retry',next_at=0")
            result = PeriodicDelivery(path, renderer).deliver('owner', 'car', report(trips=1), sender)
            self.assertEqual(result['image'], 'skipped')
            sender.send_markdown.assert_called_once()
            renderer.render.assert_not_called()
            sender.send_image.assert_not_called()

    def test_idle_text_rejection_retries_only_text_after_backoff(self):
        with tempfile.TemporaryDirectory() as folder:
            sender, renderer, now = Mock(), Mock(), [1000]
            sender.send_markdown.side_effect = [DeliveryError('被拒绝'), None]
            delivery = PeriodicDelivery(Path(folder) / 'reports.sqlite3', renderer, clock=lambda: now[0])
            self.assertEqual(delivery.deliver('owner', 'car', report(), sender)['text'], 'retry')
            delivery.deliver('owner', 'car', report(), sender)
            self.assertEqual(sender.send_markdown.call_count, 1)
            now[0] += 120000
            self.assertEqual(delivery.deliver('owner', 'car', report(), sender)['text'], 'sent')
            self.assertEqual(sender.send_markdown.call_count, 2)
            renderer.render.assert_not_called()
            sender.send_image.assert_not_called()

    def test_charging_only_zero_distance_trip_and_empty_long_reports_keep_images(self):
        for period, trips, charges in [('day', 0, 1), ('day', 1, 0), ('week', 0, 0), ('month', 0, 0)]:
            with self.subTest(period=period, trips=trips, charges=charges), tempfile.TemporaryDirectory() as folder:
                sender, renderer = Mock(), Mock()
                renderer.render.return_value = b'PNG'
                result = PeriodicDelivery(Path(folder) / 'reports.sqlite3', renderer).deliver('owner', 'car', report(period, trips, charges), sender)
                self.assertEqual(result['image'], 'sent')
                renderer.render.assert_called_once()
                sender.send_image.assert_called_once()

    def test_scheduler_skips_completed_text_only_report(self):
        with tempfile.TemporaryDirectory() as folder:
            summary, delivery = Mock(), Mock()
            worker = ScheduledReports(Path(folder) / 'session.json',
                context=Mock(return_value=('scope', 'owner', 'car', 1234)),
                summary=summary, delivery=delivery, sender=Mock())
            now = stamp('2026-10-08T08:00:00')
            save(worker.settings, {'enabled': '1', 'enabled_at': str(now - 86400000), 'theme': 'light'})
            delivery.lookup.return_value = {'text': 'sent', 'image': 'skipped', 'next_at': 0}
            delivery.deliver.return_value = {'text': 'sent', 'image': 'skipped'}
            self.assertEqual(worker.tick(now), [])
            summary.query.assert_not_called()
            delivery.deliver.assert_not_called()
