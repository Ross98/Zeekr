import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch

from tests import test_commute_tags as fixtures


class PlaceTagRuleTests(unittest.TestCase):
    setUp = fixtures.CommuteTagTests.setUp
    trip = fixtures.CommuteTagTests.trip

    def setUp(self):
        fixtures.CommuteTagTests.setUp(self)
        self.store = self.tags.store
        self.store.change('owner','car','place_names','save','station',
            dict(name='测试充电站',shape='circle',latitude=31.21,longitude=121.41,radius_m=150),0)
        self.future=self.start+3601000

    def rule(self, **extra):
        body=dict(action='place-rule-preview',date='2026-09-28',revision=0,
                  region_id='station',tag='充电',direction='arrive',require_charge=False,enabled=True)
        body.update(extra)
        with patch('zeekr_control.place_tag_rules.time.time',return_value=(self.start+3600000)/1000):
            preview=self.tags.update('owner','car',body)
            return self.tags.update('owner','car',dict(body,action='place-rule-save',preview_token=preview['token']))

    def charge(self, identity, start, end, vehicle='car'):
        body=dict(start_time=start,end_time=end,duration_seconds=(end-start)/1000,
                  start_soc=40,end_soc=70,soc_delta=30,partial=False)
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',(identity,vehicle,'charge_end',json.dumps(body),end))

    def rows(self):return {r['id']:r for r in self.tags.query('owner','car','2026-09-28')['events']}

    def test_rule_requires_preview_and_owned_saved_region(self):
        with self.assertRaises(ValueError):
            self.tags.update('owner','car',dict(action='place-rule-save',revision=0,region_id='station',tag='充电',direction='arrive',require_charge=False,enabled=True,date='2026-09-28'))
        self.assertEqual(self.tags.place_rules.rules('other','car')['rules'],[])
        with self.assertRaises(ValueError):self.rule(region_id='missing')

    def test_future_destination_matches_and_manual_labels_notes_survive(self):
        self.rule();self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41))
        self.tags.update('owner','car',dict(action='save',event_id='arrival',tags=['接送'],note='保留',revision=0))
        row=self.rows()['arrival'];self.assertEqual(row['tags'],['接送','充电']);self.assertEqual(row['note'],'保留')
        self.assertEqual(row['automatic_place_tags'][0]['source'],'place_rule')
        self.assertEqual(self.store.read('owner','car','tags')['records'][0]['body']['tags'],['接送'])

    def test_direction_and_untrusted_coordinates(self):
        self.rule(direction='depart')
        self.trip('arrive',self.future,(31.2,121.4),(31.21,121.41))
        self.trip('depart',self.future+3600000,(31.21,121.41),(31.2,121.4))
        self.trip('untrusted',self.future+7200000,(31.21,121.41),(31.2,121.4),trusted=False)
        rows=self.rows();self.assertEqual(rows['arrive']['tags'],[]);self.assertEqual(rows['depart']['tags'],['充电']);self.assertEqual(rows['untrusted']['tags'],[])

    def test_charging_evidence_waits_then_retries_without_page_mutation(self):
        self.rule(require_charge=True);self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41))
        self.assertEqual(self.rows()['arrival']['tags'],[])
        self.charge('late-charge',self.future+1260000,self.future+1800000)
        self.tags.place_rules.collect('owner','car',self.future+3600000)
        row=self.rows()['arrival'];self.assertEqual(row['tags'],['充电']);self.assertEqual(row['automatic_place_tags'][0]['evidence']['charge_ids'],['late-charge'])

    def test_charge_after_next_movement_cannot_match_previous_parking(self):
        self.rule(require_charge=True);self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41))
        self.trip('moved',self.future+1800000,(31.21,121.41),(31.3,121.5))
        self.charge('other-parking',self.future+3100000,self.future+3500000)
        self.assertEqual(self.rows()['arrival']['tags'],[])

    def test_departure_can_match_preceding_charge_in_same_stop(self):
        self.rule(direction='depart',require_charge=True)
        self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41))
        self.charge('charge',self.future+1300000,self.future+1700000)
        self.trip('depart',self.future+1900000,(31.21,121.41),(31.2,121.4))
        self.assertEqual(self.rows()['depart']['tags'],['充电'])

    def test_saving_rule_does_not_backfill_old_trips_history_apply_is_explicit(self):
        self.trip('old',self.start+1000,(31.2,121.4),(31.21,121.41));rule=self.rule()['rule']
        self.assertEqual(self.rows()['old']['tags'],[])
        body=dict(action='place-rule-history-preview',date='2026-09-28',id=rule['id'],revision=1)
        before=self.store.path.read_bytes();preview=self.tags.update('owner','car',body);self.assertEqual(self.store.path.read_bytes(),before)
        self.assertEqual(preview['counts']['add'],1)
        self.tags.update('owner','car',dict(body,action='place-rule-history-apply',token=preview['token']))
        self.assertEqual(self.rows()['old']['tags'],['充电'])

    def test_history_token_rejects_charge_place_annotation_and_exclusion_changes(self):
        self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41));rule=self.rule()['rule'];self.rows()
        payload=dict(action='place-rule-history-preview',date='2026-09-28',id=rule['id'],revision=1)
        preview=self.tags.update('owner','car',payload)
        self.tags.update('owner','car',dict(action='save',event_id='arrival',tags=['人工'],note='',revision=0))
        with self.assertRaisesRegex(ValueError,'预览'):
            self.tags.update('owner','car',dict(payload,action='place-rule-history-apply',token=preview['token']))

    def test_single_trip_exclusion_survives_preview_and_rule_edit(self):
        rule=self.rule()['rule'];self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41));self.rows()
        self.tags.update('owner','car',dict(action='place-rule-exclude',id=rule['id'],event_id='arrival',revision=1))
        self.assertEqual(self.rows()['arrival']['tags'],[])
        changed=self.rule(id=rule['id'],revision=1,tag='购物')['rule']
        preview=self.tags.update('owner','car',dict(action='place-rule-history-preview',id=changed['id'],revision=2,date='2026-09-28'))
        self.assertEqual(preview['counts']['excluded'],1)
        self.tags.update('owner','car',dict(action='place-rule-history-apply',id=changed['id'],revision=2,date='2026-09-28',token=preview['token']))
        self.assertEqual(self.rows()['arrival']['tags'],[])

    def test_pause_affects_future_only_and_rule_versions_preserve_old_tags(self):
        rule=self.rule()['rule'];self.trip('old',self.future,(31.2,121.4),(31.21,121.41));self.rows()
        with patch('zeekr_control.place_tag_rules.time.time',return_value=(self.future+1800000)/1000):
            self.tags.update('owner','car',dict(action='place-rule-pause',id=rule['id'],revision=1))
        self.trip('paused',self.future+1900000,(31.2,121.4),(31.21,121.41))
        self.assertEqual(self.rows()['old']['tags'],['充电']);self.assertEqual(self.rows()['paused']['tags'],[])

    def test_validation_stale_revisions_and_guard_rollback(self):
        for extra in [dict(direction='anything'),dict(tag='x'*25),dict(require_charge='yes'),dict(enabled=1)]:
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.rule(**extra)
        before=self.tags.place_rules.rules('owner','car')['revision']
        def reject():raise ValueError('账号已切换')
        with self.assertRaisesRegex(ValueError,'账号已切换'):
            body=dict(action='place-rule-preview',date='2026-09-28',revision=before,region_id='station',tag='充电',direction='arrive',require_charge=False,enabled=True)
            p=self.tags.update('owner','car',body)
            self.tags.update('owner','car',dict(body,action='place-rule-save',preview_token=p['token']),guard=reject)
        self.assertEqual(self.tags.place_rules.rules('owner','car')['revision'],before)

    def test_manual_endpoint_assignment_is_label_evidence_without_gps_promotion(self):
        self.rule();self.trip('manual',self.future,(31.2,121.4),(31.21,121.41),trusted=False)
        self.store.change('owner','car','place_corrections','save','manual_end',
            dict(record_id='manual',side='end',action='assign',target_key='station',label_only=True),0)
        row=self.rows()['manual'];self.assertEqual(row['tags'],['充电'])
        self.assertEqual(row['automatic_place_tags'][0]['evidence']['sides'][0]['source'],'user_confirmation')
        with sqlite3.connect(self.db) as db:
            self.assertFalse(any(json.loads(r[0])['trusted'] for r in db.execute('SELECT location FROM observations')))

    def test_hidden_charge_is_not_evidence_and_manual_tag_is_retained(self):
        self.rule(require_charge=True);self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41))
        self.charge('charge',self.future+1300000,self.future+1700000)
        self.assertEqual(self.rows()['arrival']['tags'],['充电'])
        self.tags.update('owner','car',dict(action='save',event_id='arrival',tags=['人工'],note='保留',revision=0))
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE charge_record_trash(vehicle TEXT,event_id TEXT)')
            db.execute('INSERT INTO charge_record_trash VALUES(?,?)',('car','charge'))
        row=self.rows()['arrival'];self.assertEqual(row['tags'],['人工']);self.assertEqual(row['note'],'保留')

    def test_history_preview_invalidates_when_region_changes(self):
        self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41));rule=self.rule()['rule']
        body=dict(action='place-rule-history-preview',id=rule['id'],revision=1,date='2026-09-28')
        preview=self.tags.update('owner','car',body)
        self.store.change('owner','car','place_names','save','station',
            dict(name='另一个地点',latitude=32,longitude=120,radius_m=150),1)
        with self.assertRaisesRegex(ValueError,'预览'):
            self.tags.update('owner','car',dict(body,action='place-rule-history-apply',token=preview['token']))

    def test_history_rename_reports_update_and_deleted_rule_can_still_be_excluded(self):
        rule=self.rule()['rule'];self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41));self.rows()
        self.rule(id=rule['id'],revision=1,tag='购物')
        body=dict(action='place-rule-history-preview',date='2026-09-28',id=rule['id'],revision=2)
        preview=self.tags.update('owner','car',body)
        self.assertEqual(preview['counts']['update'],1)
        self.tags.update('owner','car',dict(body,action='place-rule-history-apply',token=preview['token']))
        self.tags.update('owner','car',dict(action='place-rule-delete',id=rule['id'],revision=2))
        self.tags.update('owner','car',dict(action='place-rule-exclude',id=rule['id'],revision=3,event_id='arrival'))
        self.assertEqual(self.rows()['arrival']['tags'],[])

    def test_decision_reads_are_scoped_to_target_events(self):
        self.rule();self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41));self.rows()
        with self.store.connect(write=True) as db,db:
            db.execute('INSERT INTO place_tag_decisions VALUES(?,?,?,?,?,?)',('owner','car','unrelated','old',1,json.dumps(dict(result='outside',tag='UNRELATED_DECISION'))))
        decode=json.loads
        def scoped_decode(value,*args,**kwargs):
            if isinstance(value,str) and 'UNRELATED_DECISION' in value:raise AssertionError('Unrelated history must not be decoded')
            return decode(value,*args,**kwargs)
        with patch('zeekr_control.place_tag_rules.json.loads',side_effect=scoped_decode):
            self.assertEqual(self.rows()['arrival']['tags'],['充电'])

    def test_hidden_trip_invalidates_history_preview(self):
        rule=self.rule()['rule'];self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41))
        body=dict(action='place-rule-history-preview',id=rule['id'],revision=1,date='2026-09-28')
        preview=self.tags.update('owner','car',body)
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE trip_record_trash(vehicle TEXT,event_id TEXT)')
            db.execute("INSERT INTO trip_record_trash VALUES('car','arrival')")
        with self.assertRaisesRegex(ValueError,'预览'):
            self.tags.update('owner','car',dict(body,action='place-rule-history-apply',token=preview['token']))

    def test_history_token_rejects_late_charge_and_rule_revision(self):
        rule=self.rule(require_charge=True)['rule'];self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41))
        body=dict(action='place-rule-history-preview',id=rule['id'],revision=1,date='2026-09-28')
        preview=self.tags.update('owner','car',body)
        self.charge('late',self.future+1300000,self.future+1700000)
        with self.assertRaisesRegex(ValueError,'预览'):
            self.tags.update('owner','car',dict(body,action='place-rule-history-apply',token=preview['token']))
        self.tags.update('owner','car',dict(action='place-rule-pause',id=rule['id'],revision=1))
        with self.assertRaisesRegex(ValueError,'更新'):
            self.tags.update('owner','car',body)

    def test_unknown_start_fragment_breaks_charge_association(self):
        self.rule(require_charge=True);self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41))
        self.charge('late',self.future+1900000,self.future+2300000)
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',('fragment','car','trip_end',json.dumps(dict(end_time=self.future+1800000,partial=True)),self.future+1800000))
        self.assertEqual(self.rows()['arrival']['tags'],[])

    def test_unknown_start_fragment_ending_after_charge_does_not_prove_continuous_parking(self):
        self.rule(require_charge=True);self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41))
        self.charge('charge',self.future+1300000,self.future+1700000)
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)',('fragment','car','trip_end',json.dumps(dict(end_time=self.future+1800000,partial=True)),self.future+1800000))
        self.assertEqual(self.rows()['arrival']['tags'],[])

    def test_history_apply_guard_rolls_back_automatic_decisions(self):
        rule=self.rule()['rule'];self.trip('old',self.start+1000,(31.2,121.4),(31.21,121.41))
        body=dict(action='place-rule-history-preview',id=rule['id'],revision=1,date='2026-09-28')
        preview=self.tags.update('owner','car',body)
        def reject():raise ValueError('账号已切换')
        with self.assertRaisesRegex(ValueError,'账号已切换'):
            self.tags.update('owner','car',dict(body,action='place-rule-history-apply',token=preview['token']),guard=reject)
        self.assertEqual(self.rows()['old']['tags'],[])

    def test_other_owner_and_vehicle_do_not_inherit_rules(self):
        self.rule();self.trip('arrival',self.future,(31.2,121.4),(31.21,121.41))
        self.assertEqual(self.tags.query('other','car','2026-09-28')['events'][0]['tags'],[])
        self.assertEqual(self.tags.place_rules.rules('owner','other')['rules'],[])


if __name__=='__main__':unittest.main()
