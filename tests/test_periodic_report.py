import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from zeekr_control.notifications import DeliveryError
from zeekr_control.focused_trip_image import ImagePreparationError
from zeekr_control.periodic_report import report_view, render_png, ReportImage, PeriodicDelivery, demo_report


def delivery_report():
    report=demo_report()
    report.pop('demo')
    return report


class PeriodicReportTests(unittest.TestCase):
    def test_six_templates_valid_png_and_zero_not_missing(self):
        for period in ('day','week','month'):
            for theme in ('light','dark'):
                content=render_png(demo_report(period),theme)
                self.assertTrue(content.startswith(b'\x89PNG\r\n\x1a\n'))
                self.assertLess(len(content),2*1024*1024)
        report=demo_report('day');report['metrics']['distance_km']=0
        self.assertEqual(report_view(report)['distance'],'0')
        report['metrics']['distance_km']=None
        self.assertEqual(report_view(report)['distance'],'—')

    def test_large_values_partial_and_invalid_input(self):
        report=demo_report('month');report['metrics']['distance_km']=100000000
        report['quality']['missing_distance_count']=1
        view=report_view(report)
        self.assertEqual(view['distance'],'10000万')
        self.assertIn('部分',view['notice'])
        self.assertTrue(render_png(report).startswith(b'\x89PNG'))
        with self.assertRaises(ValueError):render_png(report,'unknown')
        report['end_date']='PRIVATE-INJECTED'
        with self.assertRaises(ValueError):render_png(report)

    def test_worker_returns_image_and_corrupt_asset_is_safe(self):
        self.assertTrue(ReportImage().render(demo_report()).startswith(b'\x89PNG'))
        with self.assertRaises(ImagePreparationError) as error:ReportImage().render({},'dark')
        self.assertFalse(error.exception.retryable)

    def test_durable_send_once_image_failure_text_survives_and_retries_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            sender=Mock();renderer=Mock();renderer.render.side_effect=ImagePreparationError('报表图片超时')
            now=[1000]
            delivery=PeriodicDelivery(Path(folder)/'reports.sqlite3',renderer,clock=lambda:now[0])
            for i in range(4):
                delivery.deliver('scope','car',delivery_report(),sender);now[0]+=120000
            self.assertEqual(sender.send_markdown.call_count,1)
            self.assertEqual(renderer.render.call_count,3)
            sender.send_image.assert_not_called()

    def test_ambiguous_text_never_retried_and_restart_preserves_result(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'reports.sqlite3';sender=Mock();renderer=Mock()
            renderer.render.return_value=b'\x89PNG\r\n\x1a\nimage'
            sender.send_markdown.side_effect=DeliveryError('响应未确认',ambiguous=True)
            delivery=PeriodicDelivery(path,renderer)
            self.assertEqual(delivery.deliver('scope','car',delivery_report(),sender)['text'],'unknown')
            PeriodicDelivery(path,renderer).deliver('scope','car',delivery_report(),sender)
            self.assertEqual(sender.send_markdown.call_count,1)
            sender.send_image.assert_not_called()

    def test_confirmed_image_rejection_retries_image_only(self):
        with tempfile.TemporaryDirectory() as folder:
            sender=Mock();renderer=Mock();renderer.render.return_value=b'\x89PNG\r\n\x1a\nimage'
            sender.send_image.side_effect=[DeliveryError('被拒绝'),None]
            now=[1000];delivery=PeriodicDelivery(Path(folder)/'reports.sqlite3',renderer,clock=lambda:now[0])
            delivery.deliver('scope','car',delivery_report(),sender)
            now[0]+=120000
            delivery.deliver('scope','car',delivery_report(),sender)
            delivery.deliver('scope','car',delivery_report(),sender)
            self.assertEqual(sender.send_markdown.call_count,1)
            self.assertEqual(sender.send_image.call_count,2)

    def test_preparation_backoff_survives_text_success_and_snapshot_is_frozen(self):
        with tempfile.TemporaryDirectory() as folder:
            sender=Mock();renderer=Mock();renderer.render.side_effect=[ImagePreparationError('超时'),b'\x89PNG\r\n\x1a\nimage']
            now=[1000];delivery=PeriodicDelivery(Path(folder)/'reports.sqlite3',renderer,clock=lambda:now[0])
            original=delivery_report();delivery.deliver('scope','car',original,sender)
            modified=delivery_report();modified['metrics']['distance_km']=999
            delivery.deliver('scope','car',modified,sender)
            self.assertEqual(renderer.render.call_count,1)
            now[0]+=120000;delivery.deliver('scope','car',modified,sender)
            self.assertEqual(renderer.render.call_args.args[0]['metrics']['distance_km'],38.6)
            self.assertEqual(sender.send_markdown.call_count,1)
            self.assertEqual(sender.send_image.call_count,1)

    def test_ambiguous_image_and_interrupted_text_are_not_replayed(self):
        with tempfile.TemporaryDirectory() as folder:
            sender=Mock();renderer=Mock();renderer.render.return_value=b'\x89PNG\r\n\x1a\nimage'
            sender.send_image.side_effect=DeliveryError('未确认',ambiguous=True)
            delivery=PeriodicDelivery(Path(folder)/'reports.sqlite3',renderer)
            delivery.deliver('scope','car',delivery_report(),sender)
            delivery.deliver('scope','car',delivery_report(),sender)
            self.assertEqual(sender.send_image.call_count,1)
            self.assertEqual(sender.send_markdown.call_count,1)

    def test_cli_never_sends_demo(self):
        from zeekr_control.periodic_report_cli import main
        from unittest.mock import patch
        with patch('sys.argv',['periodic_report','--period','day','--demo','--send']),patch('sys.stderr'):
            with self.assertRaises(SystemExit):main()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):PeriodicDelivery(Path(folder)/'reports.sqlite3').deliver('scope','car',demo_report(),Mock())
            self.assertFalse((Path(folder)/'reports.sqlite3').exists())

    def test_real_cli_uses_readonly_dict_snapshot_and_current_vehicle_time(self):
        from zeekr_control.periodic_report_cli import main
        from unittest.mock import patch
        import threading
        with tempfile.TemporaryDirectory() as folder:
            app=Mock();app.lock=threading.Lock();app.vehicle_key='car';app.model={'updated_time':1234}
            app._read_session.return_value={'accessToken':'PRIVATE-TOKEN','userId':'user'}
            output=Path(folder)/'report.png'
            with patch('sys.argv',['periodic_report','--period','day','--date','2026-09-15','--output',str(output)]),\
                 patch('zeekr_control.web.App',return_value=app),\
                 patch('zeekr_control.periodic_summary.PeriodicSummary') as summary,\
                 patch('zeekr_control.periodic_report_cli.ReportImage') as image,patch('builtins.print'):
                summary.return_value.query.return_value=delivery_report()
                image.return_value.render.return_value=b'\x89PNG\r\n\x1a\nimage'
                main()
                self.assertEqual(summary.return_value.query.call_args.kwargs['vehicle_time'],1234)
                self.assertEqual(output.stat().st_mode & 0o777,0o600)
                app._restore_snapshot.assert_called_once()
                app.close.assert_called_once()

    def test_process_interrupted_after_text_claim_does_not_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            sender=Mock();renderer=Mock();renderer.render.return_value=b'\x89PNG\r\n\x1a\nimage'
            sender.send_markdown.side_effect=KeyboardInterrupt
            path=Path(folder)/'reports.sqlite3'
            with self.assertRaises(KeyboardInterrupt):PeriodicDelivery(path,renderer).deliver('scope','car',delivery_report(),sender)
            result=PeriodicDelivery(path,renderer).deliver('scope','car',delivery_report(),sender)
            self.assertEqual(result['text'],'unknown')
            self.assertEqual(sender.send_markdown.call_count,1)
            sender.send_image.assert_not_called()

    def test_worker_timeout_is_retryable_and_stderr_is_never_exposed(self):
        from unittest.mock import patch
        import subprocess
        with patch('zeekr_control.periodic_report.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',45)):
            with self.assertRaises(ImagePreparationError) as error:ReportImage().render(delivery_report())
            self.assertTrue(error.exception.retryable)
        with patch('zeekr_control.periodic_report.subprocess.run',return_value=Mock(returncode=1,stderr=b'PRIVATE-WEBHOOK',stdout=b'')):
            with self.assertRaises(ImagePreparationError) as error:ReportImage().render(delivery_report())
            self.assertNotIn('PRIVATE',str(error.exception))

    def test_manual_send_dedupe_uses_stable_account_not_rotating_session(self):
        from zeekr_control.periodic_report_cli import main
        from zeekr_control.personal_store import account_scope
        from unittest.mock import patch
        import threading
        app=Mock();app.lock=threading.Lock();app.vehicle_key='car';app.model={}
        session={'accessToken':'rotating-token','userId':'stable-user'};app._read_session.return_value=session
        with patch('sys.argv',['periodic_report','--period','day','--date','2026-09-15','--send']),\
             patch('zeekr_control.web.App',return_value=app),\
             patch('zeekr_control.periodic_summary.PeriodicSummary') as summary,\
             patch('zeekr_control.notifications.WeComSender'),\
             patch('zeekr_control.periodic_report_cli.PeriodicDelivery') as delivery,patch('builtins.print'):
            summary.return_value.query.return_value=delivery_report()
            delivery.return_value.deliver.return_value={'text':'sent','image':'sent'}
            main()
            self.assertEqual(delivery.return_value.deliver.call_args.args[0],account_scope(session))


if __name__=='__main__':unittest.main()
