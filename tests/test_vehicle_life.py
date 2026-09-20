from pathlib import Path
import tempfile
import unittest

from zeekr_control.personal_store import PersonalStore
from zeekr_control.tracks import day_bounds


class VehicleLifeTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.vehicle_life import VehicleLife
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=PersonalStore(Path(self.temp.name)/'private'/'personal.sqlite3')
        self.now=day_bounds('2026-09-20')[0]
        self.api=VehicleLife(self.store,clock=lambda:self.now)

    def save(self,collection='expenses',**changes):
        data=dict(action='save',collection=collection,revision=0)
        data.update(dict(date='2026-09-20',category='保险',title='本年保险',amount='1234.56',odometer='10000.1',note='合成费用')
                    if collection=='expenses' else dict(title='下次保养',due_date='2026-09-20',due_km='',note='合成待办'))
        data.update(changes)
        return self.api.update('owner','car',data)

    def query(self,**kwargs):
        return self.api.query('owner','car','2026-09-20',**kwargs)

    def change(self,collection,action,identity,revision):
        return self.api.update('owner','car',dict(collection=collection,action=action,id=identity,revision=revision))

    def raw(self,km=12000,stamp=None):
        return {'updateTime':self.now if stamp is None else stamp,'vin':'PRIVATE-VIN',
                'additionalVehicleStatus':{'maintenanceStatus':{'odometer':km}}}

    def test_readonly_empty_and_scope(self):
        self.assertEqual(self.query()['expenses']['entries'],[])
        self.assertFalse(self.store.path.exists())
        self.save();self.save('reminders')
        for owner,car in [('other','car'),('owner','other')]:
            result=self.api.query(owner,car,'2026-09-20')
            self.assertEqual(result['expenses']['entries'],[])
            self.assertEqual(result['reminders']['records'],[])

    def test_costs_use_integer_cents_date_and_custom_categories(self):
        self.save();self.save(revision=1,category='车位管理',amount='0')
        self.save(revision=2,date='2026-08-31',amount='9.99')
        result=self.query()['expenses']
        self.assertEqual(result['total_cents'],123456)
        self.assertEqual(len(result['entries']),2)
        self.assertEqual(result['categories']['车位管理']['count'],1)
        self.assertEqual(result['categories']['车位管理']['amount_cents'],0)

    def test_invalid_amount_date_notes_and_mileage_rejected(self):
        for changes in ({'amount':''},{'amount':'0.001'},{'amount':True},{'amount':-1},{'amount':'NaN'},
                        {'date':'2026-02-30'},{'category':''},{'category':'a'*25},{'title':''},
                        {'note':'a'*1001},{'odometer':'123.45'},{'odometer':True}):
            with self.assertRaises(ValueError):self.save(**changes)

    def test_expense_edit_delete_restore_undo(self):
        saved=self.save();identity=saved['id']
        self.save(id=identity,revision=1,amount='100')
        self.change('expenses','undo',None,2)
        self.assertEqual(self.query()['expenses']['total_cents'],123456)
        self.change('expenses','delete',identity,3)
        self.assertEqual(self.query()['expenses']['total_cents'],0)
        self.change('expenses','restore',identity,4)
        self.assertEqual(self.query()['expenses']['entries'][0]['amount_cents'],123456)

    def test_reminder_date_uses_beijing_calendar_boundary(self):
        self.save('reminders')
        self.now-=1
        self.assertEqual(self.query()['reminders']['records'][0]['status'],'upcoming')
        self.now+=1
        row=self.query()['reminders']['records'][0]
        self.assertEqual(row['status'],'due');self.assertEqual(row['due_reasons'],['date'])

    def test_mileage_reminder_requires_current_fresh_valid_observation(self):
        self.save('reminders',due_date='',due_km='12000')
        self.assertEqual(self.query()['reminders']['records'][0]['status'],'unknown')
        for raw,read in [(self.raw(None),self.now),(self.raw(True),self.now),(self.raw(),None),
                         (self.raw(stamp=self.now-700000),self.now),(self.raw(),self.now-700000),
                         (self.raw(stamp=self.now+120000),self.now),(self.raw(),self.now+120000)]:
            self.assertEqual(self.query(raw=raw,fetched_at=read)['reminders']['records'][0]['status'],'unknown')
        result=self.query(raw=self.raw(),fetched_at=self.now)
        self.assertEqual(result['reminders']['records'][0]['due_reasons'],['mileage'])
        self.assertEqual(result['odometer']['value'],12000)
        self.assertNotIn('PRIVATE',str(result))

    def test_date_or_mileage_either_can_be_due_without_guessing_unknown(self):
        self.save('reminders',due_date='2026-09-21',due_km='12000')
        self.assertEqual(self.query()['reminders']['records'][0]['status'],'unknown')
        self.assertEqual(self.query(raw=self.raw(),fetched_at=self.now)['reminders']['records'][0]['status'],'due')
        self.now+=86400000
        row=self.query()['reminders']['records'][0]
        self.assertEqual(row['status'],'due');self.assertEqual(row['due_reasons'],['date'])

    def test_complete_reopen_and_undo_preserve_schedule(self):
        saved=self.save('reminders');identity=saved['id']
        self.change('reminders','complete',identity,1)
        row=self.query()['reminders']['records'][0]
        self.assertEqual(row['status'],'completed');self.assertEqual(row['completed_at'],self.now)
        self.change('reminders','undo',None,2)
        self.assertEqual(self.query()['reminders']['records'][0]['status'],'due')
        self.change('reminders','complete',identity,3)
        self.change('reminders','reopen',identity,4)
        self.assertEqual(self.query()['reminders']['records'][0]['status'],'due')

    def test_edit_completed_reminder_does_not_silently_reactivate(self):
        identity=self.save('reminders')['id']
        self.change('reminders','complete',identity,1)
        self.save('reminders',id=identity,revision=2,title='修正说明')
        self.assertEqual(self.query()['reminders']['records'][0]['status'],'completed')
        self.change('reminders','delete',identity,3)
        with self.assertRaises(ValueError):self.change('reminders','reopen',identity,4)
        self.change('reminders','restore',identity,4)
        self.assertEqual(self.query()['reminders']['records'][0]['status'],'completed')

    def test_reminder_validation_and_forged_edit_identity(self):
        for changes in ({'due_date':'','due_km':''},{'due_date':'bad'},{'due_date':None},
                        {'due_km':True},{'due_km':'1.23'},{'title':'a'*81},{'id':'unknown'}):
            with self.assertRaises(ValueError):self.save('reminders',**changes)
        with self.assertRaises(ValueError):self.save(id='unknown')
        with self.assertRaises(ValueError):self.save(collection='rules')

    def test_stale_revisions_and_session_guard_do_not_change_records(self):
        saved=self.save()
        with self.assertRaises(ValueError):self.save(id=saved['id'],amount='2')
        def reject():raise ValueError('changed session')
        with self.assertRaises(ValueError):
            self.api.update('owner','car',dict(collection='expenses',action='delete',id=saved['id'],revision=1),guard=reject)
        self.assertEqual(self.query()['expenses']['total_cents'],123456)


if __name__=='__main__':unittest.main()
