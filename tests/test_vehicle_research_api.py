import json
import threading
import unittest
from unittest.mock import patch

import test_insights_api as fixtures
from zeekr_control.personal_store import account_scope
from zeekr_control.storage import save

SOC = 'additionalVehicleStatus.electricVehicleStatus.chargeLevel'


class ResearchApiTests(unittest.TestCase):
    setUp = fixtures.InsightsApiTests.setUp
    cleanup_server = fixtures.InsightsApiTests.cleanup_server
    get = fixtures.InsightsApiTests.get
    post_ledger = fixtures.InsightsApiTests.post_ledger

    def query(self, path=''):
        return self.get('/api/insights/research?start=2026-09-20&end=2026-09-20&path='+path)

    def experiment(self):
        timeline = self.get('/api/insights/timeline?date=2026-09-20')[1]
        before, after = [row['key'] for row in timeline['items']]
        data = dict(context=timeline['context'], action='save', revision=0, title='证据实验',
                    action_text='用户记录动作', action_at=self.start+30000,
                    before=before, after=after, paths=[SOC])
        code, result = self.post_ledger(data, route='/api/insights/experiments')
        self.assertEqual(code, 200)
        return result['id'], timeline['context']

    def review(self, identity, context, **extra):
        data = dict(vehicle=self.vehicle, context=context, action='save', revision=0, path=SOC,
                    scope='value', raw='69', status='question', meaning='',
                    experiment_id=identity, experiment_side='after')
        data.update(extra)
        return self.post_ledger(data, route='/api/field-reviews')

    def test_scoped_public_read_sources_assets_and_error(self):
        code, result = self.query(SOC)
        self.assertEqual(code, 200)
        self.assertEqual(result['counts']['reads'], 2)
        self.assertTrue(result['context'])
        self.assertEqual(len(result['sources']), 10)
        self.assertEqual(self.get('/vehicle-research.js')[0], 200)
        self.assertEqual(self.query('vin')[0], 400)
        for secret in ('PRIVATE-VIN', 'SYNTHETIC-SECRET', 'scope_key', 'latitude'):
            self.assertNotIn(secret, json.dumps(result))
        self.assertFalse(self.app.personal_store.path.exists())

    def test_archive_scan_does_not_hold_global_lock(self):
        original = self.app.vehicle_research.query
        def checking(*args, **kwargs):
            acquired = []
            def worker():
                ok = self.app.lock.acquire(timeout=.5)
                acquired.append(ok)
                if ok: self.app.lock.release()
            thread = threading.Thread(target=worker); thread.start(); thread.join()
            self.assertEqual(acquired, [True])
            return original(*args, **kwargs)
        with patch.object(self.app.vehicle_research, 'query', side_effect=checking):
            self.assertEqual(self.query()[0], 200)

    def test_account_switch_during_scan_discards_old_result(self):
        original = self.app.vehicle_research.query
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            save(self.path, {'accessToken':'another-owner'})
            return result
        with patch.object(self.app.vehicle_research, 'query', side_effect=changed):
            code, result = self.query()
        self.assertEqual(code, 400)
        self.assertNotIn('fields', result)

    def test_manual_evidence_saved_without_promoting_runtime_meaning(self):
        identity, context = self.experiment()
        code, result = self.review(identity, context)
        self.assertEqual(code, 200)
        row = result['records'][0]
        self.assertEqual(row['status'], 'question')
        self.assertEqual(row['evidence']['observation']['raw'], '69')
        self.assertEqual(row['evidence']['title'], '证据实验')
        research = self.query(SOC)[1]
        self.assertEqual(len(research['experiments']), 1)
        self.assertEqual(len(research['reviews']), 1)
        self.assertEqual(self.app.experiments.detail(account_scope(self.session),self.vehicle,identity)['body']['status'], 'research_only')

    def test_evidence_rejects_wrong_context_path_value_side_and_deleted(self):
        identity, context = self.experiment()
        for extra in [dict(raw='70'),dict(path='updateTime'),dict(experiment_side='bad'),dict(context='other')]:
            passed = dict(extra)
            active_context = passed.pop('context',context)
            self.assertEqual(self.review(identity,active_context,**passed)[0],400)
        self.app.personal_store.change(account_scope(self.session),self.vehicle,'experiments','delete',identity,None,1)
        self.assertEqual(self.review(identity,context)[0],400)
        self.assertFalse(self.app.field_review_store.path.exists())

    def test_session_change_during_evidence_read_prevents_commit(self):
        identity, context = self.experiment()
        original = self.app.experiments.review_evidence
        def changed(*args,**kwargs):
            result=original(*args,**kwargs)
            save(self.path,{'accessToken':'different-owner'})
            return result
        with patch.object(self.app.experiments,'review_evidence',side_effect=changed):
            self.assertEqual(self.review(identity,context)[0],400)
        self.assertEqual(self.app.field_review_store.read(self.vehicle)['revision'],0)


if __name__ == '__main__': unittest.main()
