import json
from pathlib import Path
import tempfile
import unittest

from zeekr_control.archive_reader import ArchiveReader
from zeekr_control.snapshot_archive import SnapshotArchive
from zeekr_control.personal_store import PersonalStore
from zeekr_control.tracks import day_bounds


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        from zeekr_control.parameter_experiments import ParameterExperiments
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.archive=ArchiveReader(self.root/'archive')
        writer=SnapshotArchive(self.root/'archive');self.store=PersonalStore(self.root/'personal.sqlite3')
        self.start,_=day_bounds('2026-09-20')
        for offset,soc in ((0,70),(60000,69)):
            raw={'updateTime':self.start+offset,'vin':'SECRET-VIN','accessToken':'SECRET-TOKEN',
                 'position':{'latitude':123,'longitude':456},
                 'additionalVehicleStatus':{'electricVehicleStatus':{'chargeLevel':soc},
                                            'climateStatus':{'interiorTemp':25+offset/60000}}}
            writer.append('scope','car',json.dumps(raw),self.start+offset,self.start+offset,self.start+offset,'monitor')
        keys=self.archive.timeline('scope','car','2026-09-20')['items']
        self.before,self.after=[r['key'] for r in keys]
        self.api=ParameterExperiments(self.store,self.archive,clock=lambda:self.start+100000)
        self.path='additionalVehicleStatus.electricVehicleStatus.chargeLevel'

    def save(self,**extra):
        payload=dict(action='save',revision=0,title='空调动作观察',action_text='手动打开空调',
                     action_at=self.start+30000,before=self.before,after=self.after,
                     paths=[self.path],note='合成观察；不推断因果')
        payload.update(extra)
        return self.api.update('owner','car',payload,scope='scope')

    def test_save_freezes_only_selected_safe_changes_and_no_promotion(self):
        saved=self.save(evidence_status='confirmed')
        row=self.api.detail('owner','car',saved['id'])
        self.assertEqual(row['body']['status'],'research_only')
        self.assertEqual(len(row['body']['changes']),1)
        self.assertEqual(row['body']['changes'][0]['path'],self.path)
        self.assertNotIn('SECRET',json.dumps(row))
        self.assertFalse((self.root/'field-reviews.sqlite3').exists())

    def test_list_is_summary_only_and_read_does_not_create_database(self):
        self.assertEqual(self.api.query('owner','car')['records'],[])
        self.assertFalse(self.store.path.exists())
        self.save();row=self.api.query('owner','car')['records'][0]
        self.assertNotIn('changes',row['body']);self.assertEqual(row['body']['change_count'],1)

    def test_private_or_unchanged_paths_and_foreign_samples_rejected(self):
        for paths in (['vin'],['position.latitude'],['missing.field'],[1],['a']*41):
            with self.assertRaises(ValueError):self.save(paths=paths)
        with self.assertRaises(ValueError):
            self.api.update('owner','other',dict(action='save',revision=0,title='test',action_text='test',
                action_at=self.start,before=self.before,after=self.after,paths=[]),scope='scope')
        with self.assertRaises(ValueError):
            self.api.update('owner','car',dict(action='save',revision=0,title='test',action_text='test',
                action_at=self.start,before=self.before,after=self.after,paths=[]),scope='other')

    def test_action_outside_sample_bracket_is_warning_not_claimed_causality(self):
        saved=self.save(action_at=self.start-60000)
        self.assertIn('action_not_bracketed',self.api.detail('owner','car',saved['id'])['body']['warnings'])

    def test_time_order_future_and_missing_action_validation(self):
        for changes in ({'before':self.after,'after':self.before},{'before':self.after},
                        {'action_at':True},{'action_at':self.start+86400000},{'title':''},{'action_text':''},
                        {'note':'x'*2001}):
            with self.assertRaises(ValueError):self.save(**changes)

    def test_same_vehicle_timestamp_revision_remains_qualified(self):
        writer=SnapshotArchive(self.root/'archive')
        raw={'updateTime':self.start,'additionalVehicleStatus':{'electricVehicleStatus':{'chargeLevel':68}}}
        writer.append('scope','car',json.dumps(raw),self.start,self.start+120000,self.start+120000,'monitor')
        after=self.archive.timeline('scope','car','2026-09-20')['items'][-1]['key']
        saved=self.save(after=after)
        self.assertIn('vehicle_time_not_advanced',self.api.detail('owner','car',saved['id'])['body']['warnings'])

    def test_reopen_and_edit_notes_survive_source_archive_removal(self):
        saved=self.save()
        for path in (self.root/'archive').glob('*/*.sqlite3'):path.unlink()
        self.assertEqual(self.api.detail('owner','car',saved['id'])['body']['changes'][0]['before']['raw'],'70')
        self.save(id=saved['id'],revision=1,note='补充备注')
        self.assertEqual(self.api.detail('owner','car',saved['id'])['body']['note'],'补充备注')
        with self.assertRaises(ValueError):self.save(id=saved['id'],revision=2,after='202609.999')

    def test_soft_delete_restore_undo_and_owner_scope(self):
        saved=self.save()
        self.api.update('owner','car',dict(action='delete',id=saved['id'],revision=1),scope='scope')
        self.assertTrue(self.api.query('owner','car')['records'][0]['deleted'])
        self.api.update('owner','car',dict(action='undo',revision=2),scope='scope')
        self.assertFalse(self.api.query('owner','car')['records'][0]['deleted'])
        self.assertEqual(self.api.query('other','car')['records'],[])
        with self.assertRaises(ValueError):self.api.detail('other','car',saved['id'])

    def test_review_raw_uses_dictionary_format_without_losing_frozen_raw(self):
        from zeekr_control.parameter_experiments import review_raw
        self.assertEqual(review_raw({'status':'pending','raw':'12.34567'}),'12.346')
        self.assertEqual(review_raw({'status':'pending','raw':'"hello"'}),'hello')
        self.assertEqual(review_raw({'status':'pending','raw':'true'}),'true')
        self.assertIsNone(review_raw({'status':'invalid','raw':'[非标量值]'}))
        saved=self.save()
        data=dict(experiment_id=saved['id'],experiment_side='after',path=self.path,raw='69')
        with self.assertRaises(ValueError):self.api.review_evidence('other','car',data)
        with self.assertRaises(ValueError):self.api.review_evidence('owner','other-car',data)


if __name__=='__main__':unittest.main()
