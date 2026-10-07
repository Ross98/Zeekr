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
