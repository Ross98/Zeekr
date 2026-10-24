from datetime import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from zeekr_control.snapshot_archive import BEIJING
from zeekr_control.storage import save
from zeekr_control.periodic_schedule import due_jobs,next_times,ScheduledReports


def stamp(value):return int(datetime.fromisoformat(value).replace(tzinfo=BEIJING).timestamp()*1000)


class PeriodicScheduleTests(unittest.TestCase):
    def test_year_and_leap_month_reports_keep_closed_calendar_windows(self):
        for date,start,end in [('2027-01-01','2026-12-01','2026-12-31'),
                               ('2024-03-01','2024-02-01','2024-02-29'),
                               ('2025-03-01','2025-02-01','2025-02-28')]:
            with self.subTest(date=date):
                now=stamp(date+'T08:20:00')
                jobs=due_jobs(now,now-86400000)
                month=next(job for job in jobs if job['period']=='month')
                self.assertEqual((month['start_date'],month['end_date']),(start,end))
                self.assertEqual(month['date'],end)
        self.assertEqual(next_times(stamp('2026-12-31T23:59:59')),
                         {'day':'2027-01-01 08:00','week':'2027-01-04 08:10',
                          'month':'2027-01-01 08:20'})

    def test_each_report_has_its_own_exclusive_six_hour_deadline(self):
        enabled=stamp('2026-05-31T12:00:00')
        for clock,expected in [('13:59:59',['day','week','month']),
                               ('14:00:00',['week','month']),
                               ('14:09:59',['week','month']),
                               ('14:10:00',['month']),
                               ('14:19:59',['month']),('14:20:00',[])]:
            with self.subTest(clock=clock):
                jobs=due_jobs(stamp('2026-06-01T'+clock),enabled)
                self.assertEqual([job['period'] for job in jobs],expected)

    def test_changes_during_render_prevent_external_sends(self):
        from unittest.mock import patch
        from zeekr_control.periodic_report import PeriodicDelivery,demo_report
        for change in ('disable','binding','deadline'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);elapsed=[0.0]
                context=Mock(return_value=('scope','owner','car',1234))
                sender=Mock();summary=Mock();renderer=Mock()
                report=demo_report();report.pop('demo');summary.query.return_value=report
                now=stamp('2026-10-08T13:59:59')
                delivery=PeriodicDelivery(root/'reports.sqlite3',renderer,clock=lambda:now)
                worker=ScheduledReports(root/'session.json',context=context,summary=summary,delivery=delivery,sender=sender)
                settings={'enabled':'1','enabled_at':str(now-86400000),'theme':'light'}
                save(worker.settings,settings)
                def render(*args):
                    if change=='disable':save(worker.settings,dict(settings,enabled='0'))
                    elif change=='binding':context.return_value=('new-scope','new-owner','other-car',1234)
                    else:elapsed[0]=2.0
                    return b'PNG'
                renderer.render.side_effect=render
                with patch('zeekr_control.periodic_schedule.time.monotonic',side_effect=lambda:elapsed[0]):
                    worker.tick(now)
                sender.send_markdown.assert_not_called()
                sender.send_image.assert_not_called()
                state=delivery.lookup('owner','car','day',report['start_date'],report['end_date'])
                self.assertEqual(state['text'],'pending')
                with delivery.connect() as db:
                    self.assertEqual(tuple(db.execute('SELECT text_attempts,image_attempts FROM reports').fetchone()),(0,0))
                if change=='binding':
                    context.return_value=('scope','owner','car',1234)
                    renderer.render.side_effect=None;renderer.render.return_value=b'PNG'
                    worker.tick(now)
                    sender.send_markdown.assert_called_once()
                    sender.send_image.assert_called_once()

    def test_query_that_crosses_window_does_not_start_delivery(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            elapsed=[0.0];now=stamp('2026-10-08T13:59:59')
            summary=Mock();delivery=Mock();delivery.lookup.return_value=None
            worker=ScheduledReports(Path(folder)/'session.json',context=Mock(return_value=('scope','owner','car',1234)),
                                    summary=summary,delivery=delivery,sender=Mock())
            save(worker.settings,{'enabled':'1','enabled_at':str(now-86400000),'theme':'light'})
            def query(*args,**kwargs):elapsed[0]=2.0;return {}
            summary.query.side_effect=query
            with patch('zeekr_control.periodic_schedule.time.monotonic',side_effect=lambda:elapsed[0]):
                self.assertEqual(worker.tick(now),[])
            delivery.deliver.assert_not_called()

    def test_disable_after_text_acknowledgement_prevents_image_send(self):
        from zeekr_control.periodic_report import PeriodicDelivery,demo_report
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);context=Mock(return_value=('scope','owner','car',1234))
            sender=Mock();summary=Mock();renderer=Mock();renderer.render.return_value=b'PNG'
            report=demo_report();report.pop('demo');summary.query.return_value=report
            now=stamp('2026-10-08T08:00:00')
            delivery=PeriodicDelivery(root/'reports.sqlite3',renderer,clock=lambda:now)
            worker=ScheduledReports(root/'session.json',context=context,summary=summary,delivery=delivery,sender=sender)
            settings={'enabled':'1','enabled_at':str(now-86400000),'theme':'light'}
            save(worker.settings,settings)
            sender.send_markdown.side_effect=lambda *_:save(worker.settings,dict(settings,enabled='0'))
            worker.tick(now)
            sender.send_markdown.assert_called_once()
            sender.send_image.assert_not_called()
            state=delivery.lookup('owner','car','day',report['start_date'],report['end_date'])
            self.assertEqual((state['text'],state['image']),('sent','ready'))

    def test_beijing_ten_minute_spacing_and_closed_dates(self):
        enabled=stamp('2026-05-31T12:00:00')
        for minute,periods in [('07:59',[]),('08:00',['day']),('08:09',['day']),
                               ('08:10',['day','week']),('08:19',['day','week']),('08:20',['day','week','month'])]:
            result=due_jobs(stamp('2026-06-01T'+minute+':00'),enabled)
            self.assertEqual([r['period'] for r in result],periods)
            self.assertTrue(all(r['date']=='2026-05-31' for r in result))

    def test_enable_after_due_never_backfills_and_only_today_is_considered(self):
        enabled=stamp('2026-10-07T18:00:00')
        self.assertEqual(due_jobs(stamp('2026-10-07T18:01:00'),enabled),[])
        jobs=due_jobs(stamp('2026-10-08T08:00:00'),enabled)
        self.assertEqual(jobs[0]['date'],'2026-10-07')
        self.assertEqual(due_jobs(stamp('2026-10-08T14:00:00'),enabled),[])
        self.assertEqual([r['period'] for r in due_jobs(stamp('2026-10-12T08:10:00'),enabled)],['day','week'])
        self.assertEqual([r['period'] for r in due_jobs(stamp('2026-11-01T08:20:00'),enabled)],['day','month'])
        self.assertEqual(next_times(enabled),{'day':'2026-10-08 08:00','week':'2026-10-12 08:10','month':'2026-11-01 08:20'})

    def test_enable_is_idempotent_and_does_not_send(self):
        with tempfile.TemporaryDirectory() as folder:
            sender=Mock();context=Mock(return_value=('scope','owner','car',1234))
            worker=ScheduledReports(Path(folder)/'session.json',context=context,sender=sender)
            save(Path(folder)/'wecom-webhook.json',{'webhook_url':'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key='+'x'*20})
            now=stamp('2026-10-07T18:00:00');worker.enable(now)
            worker.enable(now+120000)
            from zeekr_control.storage import load
            self.assertEqual(load(worker.settings)['enabled_at'],str(now))
            self.assertEqual(worker.tick(now),[])
            sender.send_markdown.assert_not_called();sender.send_image.assert_not_called()

    def test_disabled_is_noop_and_terminal_ledger_skips_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            context=Mock(return_value=('archive-scope','owner','car',1234))
            summary=Mock();delivery=Mock();sender=Mock()
            worker=ScheduledReports(Path(folder)/'session.json',context=context,summary=summary,delivery=delivery,sender=sender)
            now=stamp('2026-10-08T08:00:00')
            self.assertEqual(worker.tick(now),[]);context.assert_not_called()
            save(worker.settings,{'enabled':'1','enabled_at':str(stamp('2026-10-07T18:00:00')),'theme':'light'})
            delivery.lookup.return_value={'text':'sent','image':'sent','next_at':0}
            self.assertEqual(worker.tick(now),[]);summary.query.assert_not_called()

    def test_retry_not_before_next_at_and_stable_owner_used(self):
        with tempfile.TemporaryDirectory() as folder:
            context=Mock(return_value=('archive-scope','stable-owner','car',1234))
            summary=Mock();delivery=Mock();sender=Mock()
            worker=ScheduledReports(Path(folder)/'session.json',context=context,summary=summary,delivery=delivery,sender=sender)
            now=stamp('2026-10-08T08:00:00')
            save(worker.settings,{'enabled':'1','enabled_at':str(now-86400000),'theme':'light'})
            delivery.deliver.return_value={'text':'sent','image':'sent'}
            delivery.lookup.return_value={'text':'sent','image':'retry','next_at':now+120000}
            self.assertEqual(worker.tick(now),[])
            worker.tick(now+120000)
            self.assertEqual(delivery.deliver.call_args.args[0],'stable-owner')
            self.assertEqual(summary.query.call_args.args[:3],('archive-scope','car','stable-owner'))


if __name__=='__main__':unittest.main()
