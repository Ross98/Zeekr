from pathlib import Path
import tempfile
import unittest

from zeekr_control.personal_store import PersonalStore, account_scope


class PersonalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'private'/'personal.sqlite3'
        self.store=PersonalStore(self.path)

    def change(self,action='save',identity='entry',body=None,revision=0,**kwargs):
        return self.store.change('owner','car','charges',action,identity,
                                 {'amount_cents':1234} if body is None else body,revision,**kwargs)

    def test_read_is_readonly_and_does_not_create_storage(self):
        self.assertEqual(self.store.read('owner','car','charges')['revision'],0)
        self.assertFalse(self.path.parent.exists())

    def test_stable_account_survives_token_rotation_and_separates_users(self):
        a=account_scope({'userId':'owner','accessToken':'one'})
        self.assertEqual(a,account_scope({'userId':'owner','accessToken':'two'}))
        self.assertNotEqual(a,account_scope({'userId':'other','accessToken':'one'}))
        self.assertNotEqual(account_scope({'accessToken':'one'}),account_scope({'accessToken':'two'}))

    def test_persistence_scope_and_permissions(self):
        result=self.change()
        self.assertEqual(result['revision'],1)
        self.assertTrue(result['can_undo'])
        reopened=PersonalStore(self.path).read('owner','car','charges')
        self.assertEqual(reopened['records'][0]['body']['amount_cents'],1234)
        for owner,car,collection in [('other','car','charges'),('owner','other','charges'),('owner','car','expenses')]:
            self.assertEqual(self.store.read(owner,car,collection)['records'],[])
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertEqual(self.path.parent.stat().st_mode&0o777,0o700)
        before=self.path.read_bytes();self.store.read('owner','car','charges');self.assertEqual(self.path.read_bytes(),before)

    def test_stale_revision_cannot_overwrite_or_delete(self):
        self.change()
        for action in ('save','delete','undo'):
            with self.assertRaises(ValueError):self.change(action=action,body={'amount_cents':999},revision=0)
        self.assertEqual(self.store.read('owner','car','charges')['records'][0]['body']['amount_cents'],1234)

    def test_delete_restore_and_undo_edit_preserve_values(self):
        self.change()
        edited=self.change(body={'amount_cents':2000},revision=1)
        undone=self.change(action='undo',revision=edited['revision'])
        self.assertEqual(undone['records'][0]['body']['amount_cents'],1234)
        self.assertFalse(undone['can_undo'])
        deleted=self.change(action='delete',revision=undone['revision'])
        self.assertTrue(deleted['records'][0]['deleted'])
        restored=self.change(action='restore',revision=deleted['revision'])
        self.assertFalse(restored['records'][0]['deleted'])
        self.assertEqual(restored['records'][0]['body']['amount_cents'],1234)

    def test_undo_creation_removes_active_record(self):
        self.change()
        result=self.change(action='undo',revision=1)
        self.assertEqual(result['records'],[])
        self.assertEqual(result['revision'],2)

    def test_guard_failure_rolls_back_data_and_revision(self):
        self.change()
        def reject():raise ValueError('Session changed')
        with self.assertRaises(ValueError):self.change(revision=1,body={'amount_cents':999},guard=reject)
        result=self.store.read('owner','car','charges')
        self.assertEqual(result['revision'],1)
        self.assertEqual(result['records'][0]['body']['amount_cents'],1234)

    def test_validation_and_symlink_refusal(self):
        for changes in ({'identity':'../secret'},{'body':{'value':float('nan')}},{'revision':True},
                        {'action':'overwrite'},{'body':{'note':'x'*20000}}):
            with self.assertRaises(ValueError):self.change(**changes)
        self.change()
        original=self.path.with_suffix('.original');self.path.rename(original);self.path.symlink_to(original)
        with self.assertRaises(OSError):self.store.read('owner','car','charges')

    def test_larger_frozen_experiments_keep_undo_and_other_collection_limits(self):
        body={'observations':'x'*40000}
        self.store.change('owner','car','experiments','save','experiment',body,0)
        self.store.change('owner','car','experiments','save','experiment',{'note':'edit'},1)
        undone=self.store.change('owner','car','experiments','undo',None,None,2)
        self.assertEqual(undone['records'][0]['body'],body)
        with self.assertRaises(ValueError):self.change(body=body)
        with self.assertRaises(ValueError):
            self.store.change('owner','car','experiments','save','too-large',{'value':'x'*66000},3)

    def test_one_step_undo_journal_stays_bounded_and_keeps_other_collections(self):
        for revision in range(25):self.change(body={'amount_cents':revision},revision=revision)
        self.store.change('owner','car','experiments','save','other',{'note':'preserve'},0)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT collection,COUNT(*) FROM changes GROUP BY collection ORDER BY collection').fetchall(),
                             [('charges',1),('experiments',1)])
        result=self.change(action='undo',revision=25)
        self.assertEqual(result['records'][0]['body']['amount_cents'],23)
        self.assertFalse(result['can_undo'])
        self.assertTrue(self.store.read('owner','car','experiments')['can_undo'])


if __name__=='__main__':unittest.main()
