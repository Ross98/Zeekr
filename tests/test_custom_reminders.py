"""Synthetic rules and outbox tests. No network or real vehicle data."""
import json
from pathlib import Path
import tempfile
import unittest

from zeekr_control.personal_store import PersonalStore
from test_monitor import BASE, sample


class ReminderTests(unittest.TestCase):
    def test_recovery_only_supersedes_its_own_rule(self):
        first=self.save(delivery='wecom',name='低于25')
        self.save(revision=1,delivery='wecom',name='低于10',threshold=10,recovery=False)
        for seconds,soc in ((0,5),(60,5),(120,15),(180,15)):
            self.observe(seconds,soc)
        messages=[]
        self.rules.deliver('owner','car',sample(180,soc=15),BASE+180000,messages.append)
        self.assertEqual(len(messages),1)
        self.assertIn('低于25',messages[0])
        first_history=[row for row in self.query()['history'] if row['rule_id']==first['id']]
        self.assertEqual(first_history[0]['delivery'],'sent')


    def test_legacy_pending_warning_does_not_revive_after_recovery(self):
        self.save(delivery='wecom',recovery=False)
        for seconds,soc in ((0,20),(60,20),(120,40),(180,40)):
            self.observe(seconds,soc)
        # Older versions left raised events pending even after local recovery.
        with self.store.connect(write=True) as db,db:
            db.execute("UPDATE rule_history SET delivery='pending' WHERE kind='raised'")
        messages=[]
        # A single matching sample is not a new confirmed warning.
        self.observe(240,20,sender=messages.append)
        self.assertEqual(messages,[])
        self.assertEqual(self.query()['history'][-1]['delivery'],'cancelled')


    def test_new_confirmed_cycle_supersedes_pending_old_warning(self):
        self.save(delivery='wecom',cooldown_minutes=1)
        for seconds,soc in ((0,20),(60,20),(120,40),(180,40),(240,20),(300,20)):
            self.observe(seconds,soc)
        history=self.query()['history']
        self.assertEqual([row['delivery'] for row in history],['pending','cancelled','cancelled'])
        messages=[]
        self.rules.deliver('owner','car',sample(300,soc=20),BASE+300000,messages.append)
        self.assertEqual(len(messages),1)
        self.assertIn(history[0]['id'][:16],messages[0])


    def test_preparation_delay_rechecks_observation_freshness_at_send(self):
        from unittest.mock import patch
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        clock=[100.0];calls=[];messages=[]
        def guard():
            calls.append(True)
            if len(calls)==2:clock[0]+=2
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.rules.deliver('owner','car',sample(60,soc=20),BASE+239000,messages.append,guard)
        self.assertEqual(messages,[])
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_slow_first_send_cannot_keep_later_queue_items_artificially_fresh(self):
        from unittest.mock import patch
        self.save(delivery='wecom')
        self.save(name='第二条提醒',revision=1,delivery='wecom')
        self.observe(0);self.observe(60)
        clock=[100.0];messages=[]
        def sender(message):
            messages.append(message)
            clock[0]+=2
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.rules.deliver('owner','car',sample(60,soc=20),BASE+239000,sender)
        self.assertEqual(len(messages),1)
        self.assertEqual(sorted(row['delivery'] for row in self.query()['history']),['cancelled','sent'])

    def test_event_age_expires_during_preparation_even_with_fresh_observation(self):
        from unittest.mock import patch
        self.save(delivery='wecom');self.observe(0);self.observe(60);self.observe(659)
        clock=[100.0];calls=[];messages=[]
        def guard():
            calls.append(True)
            if len(calls)==2:clock[0]+=2
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.rules.deliver('owner','car',sample(659,soc=20),BASE+659000,messages.append,guard)
        self.assertEqual(messages,[])
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_observation_exactly_at_freshness_limit_is_still_allowed(self):
        from unittest.mock import patch
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        clock=[100.0];calls=[];messages=[]
        def guard():
            calls.append(True)
            if len(calls)==2:clock[0]+=1
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.rules.deliver('owner','car',sample(60,soc=20),BASE+239000,messages.append,guard)
        self.assertEqual(len(messages),1)
        self.assertEqual(self.query()['history'][0]['delivery'],'sent')

    def test_delivery_recovery_time_is_included_in_freshness_budget(self):
        from unittest.mock import patch
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        clock=[100.0];messages=[]
        original=self.rules._recover
        def recover():
            original()
            clock[0]+=2
        with patch('time.monotonic',side_effect=lambda:clock[0]),patch.object(self.rules,'_recover',side_effect=recover):
            self.rules.deliver('owner','car',sample(60,soc=20),BASE+239000,messages.append)
        self.assertEqual(messages,[])
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_worker_includes_earlier_delivery_phase_time_before_reminder_call(self):
        from unittest.mock import Mock,patch
        from zeekr_control.delivery_runtime import DeliveryWorker
        from zeekr_control.snapshots import SnapshotStore,session_scope
        from zeekr_control.storage import save
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        root=self.store.path.parent
        session={'accessToken':'synthetic'}
        save(root/'session.json',session)
        save(root/'monitor-binding.json',{'vehicle_key':'car'})
        SnapshotStore(root/'snapshots.sqlite3').publish(session_scope(session),'car',sample(60,soc=20),BASE+60000)
        sender=Mock()
        worker=DeliveryWorker(root/'session.json',sender=sender,alert_sender=None)
        clock=[100.0]
        def slow_storage(*args,**kwargs):clock[0]+=2
        with patch('time.monotonic',side_effect=lambda:clock[0]), \
                patch.object(worker.storage,'tick',side_effect=slow_storage), \
                patch('zeekr_control.delivery_runtime.account_scope',return_value='owner'):
            worker.tick(BASE+239000)
        sender.assert_not_called()
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_rule_disabled_after_preparation_does_not_send_old_reminder(self):
        saved=self.save(delivery='wecom');self.observe(0);self.observe(60)
        messages=[];calls=[]
        def guard():
            calls.append(True)
            if len(calls)==2:self.save(id=saved['id'],revision=1,delivery='wecom',enabled=False)
        self.rules.deliver('owner','car',sample(60,soc=20),BASE+60000,messages.append,guard)
        self.assertEqual(messages,[])
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_newer_recovery_during_preparation_invalidates_old_raised_reminder(self):
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        messages=[];calls=[]
        def guard():
            calls.append(True)
            if len(calls)==2:
                self.observe(120,soc=80);self.observe(180,soc=80)
        self.rules.deliver('owner','car',sample(60,soc=20),BASE+60000,messages.append,guard)
        self.assertEqual(messages,[])
        self.rules.deliver('owner','car',sample(180,soc=80),BASE+180000,messages.append)
        self.assertEqual(len(messages),1)
        self.assertIn('条件恢复',messages[0])
        self.assertEqual({row['kind']:row['delivery'] for row in self.query()['history']},
                         {'raised':'cancelled','recovered':'sent'})

    def test_newer_unconfirmed_reversal_also_blocks_old_condition_message(self):
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        messages=[];calls=[]
        def guard():
            calls.append(True)
            if len(calls)==2:self.observe(120,soc=80)
        self.rules.deliver('owner','car',sample(60,soc=20),BASE+60000,messages.append,guard)
        self.assertEqual(messages,[])
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_delivery_mode_change_during_preparation_cancels_external_reminder(self):
        saved=self.save(delivery='wecom');self.observe(0);self.observe(60)
        messages=[];calls=[]
        def guard():
            calls.append(True)
            if len(calls)==2:self.save(id=saved['id'],revision=1,delivery='in_app')
        self.rules.deliver('owner','car',sample(60,soc=20),BASE+60000,messages.append,guard)
        self.assertEqual(messages,[])
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_preparation_interruption_can_resume_without_ambiguous_send(self):
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        messages=[];calls=[]
        def guard():
            calls.append(True)
            if len(calls)==2:raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.rules.deliver('owner','car',sample(60,soc=20),BASE+60000,messages.append,guard)
        self.assertEqual(self.query()['history'][0]['delivery'],'preparing')
        self.rules.deliver('owner','car',sample(60,soc=20),BASE+60000,messages.append)
        self.assertEqual(len(messages),1)
        self.assertEqual(self.query()['history'][0]['delivery'],'sent')

    def test_actual_send_interruption_remains_uncertain_without_replay(self):
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        calls=[]
        def sender(message):
            calls.append(message)
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.rules.deliver('owner','car',sample(60,soc=20),BASE+60000,sender)
        self.rules.deliver('owner','car',sample(60,soc=20),BASE+60000,sender)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.query()['history'][0]['delivery'],'uncertain')

    def test_rollback_requeues_reminder_preparation_only(self):
        from zeekr_control.delivery_state import normalize_preparation_for_rollback
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        identity=self.query()['history'][0]['id']
        with self.store.connect(write=True) as db,db:
            db.execute("UPDATE rule_history SET delivery='preparing'")
            for status in ('sending','uncertain','sent','failed'):
                db.execute('INSERT INTO rule_history SELECT ?,owner,vehicle,rule_id,signature,kind,name,created,state_time,?,message,error '
                           'FROM rule_history WHERE id=?',('phase_'+status,status,identity))
        result=normalize_preparation_for_rollback(self.store.path.parent)
        self.assertEqual(result['rule_history.delivery'],1)
        with self.store.connect() as db:
            states=dict(db.execute('SELECT id,delivery FROM rule_history'))
        self.assertEqual(states[identity],'pending')
        for status in ('sending','uncertain','sent','failed'):
            self.assertEqual(states['phase_'+status],status)

    def test_rule_edit_after_sender_entry_preserves_actual_sent_result(self):
        saved=self.save(delivery='wecom');self.observe(0);self.observe(60)
        calls=[]
        def sender(message):
            calls.append(message)
            self.save(id=saved['id'],revision=1,enabled=False)
        self.rules.deliver('owner','car',sample(60,soc=20),BASE+60000,sender)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.query()['history'][0]['delivery'],'sent')

    def setUp(self):
        from zeekr_control.custom_reminders import Reminders
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=PersonalStore(Path(self.temp.name)/'personal.sqlite3')
        self.rules=Reminders(self.store)

    def save(self,**values):
        data=dict(action='save',name='低电量',kind='low_soc',threshold=25,enabled=True,
                  confirm_seconds=60,cooldown_minutes=10,delivery='in_app',recovery=True,revision=0)
        data.update(values)
        return self.rules.update('owner','car',data)

    def observe(self,seconds,soc=20,**kwargs):
        return self.rules.observe('owner','car',sample(seconds,soc=soc),BASE+seconds*1000,**kwargs)

    def query(self):return self.rules.query('owner','car')

    def test_read_and_preview_do_not_create_database(self):
        from zeekr_control.custom_reminders import preview
        self.assertEqual(self.query()['records'],[])
        self.assertTrue(preview(dict(kind='low_soc',threshold=25),sample(0,soc=20),BASE)['matches'])
        self.assertFalse(self.store.path.exists())

    def test_requires_distinct_continuous_new_states_and_restarts(self):
        from zeekr_control.custom_reminders import Reminders
        self.save();self.observe(0)
        self.rules.observe('owner','car',sample(0,soc=20),BASE+60000)
        self.assertEqual(self.query()['history'],[])
        self.rules=Reminders(PersonalStore(self.store.path))
        self.observe(60)
        self.assertEqual([e['kind'] for e in self.query()['history']],['raised'])
        self.observe(120)
        self.assertEqual(len(self.query()['history']),1)

    def test_same_time_revision_and_regression_do_not_count_confirmation(self):
        self.save();self.observe(0)
        self.rules.observe('owner','car',sample(0,soc=19),BASE+60000)
        self.observe(60)
        self.assertEqual(self.query()['history'],[])
        self.observe(120);self.assertEqual(len(self.query()['history']),1)
        self.rules.observe('owner','car',sample(90,soc=80),BASE+120000)
        self.assertEqual(len(self.query()['history']),1)

    def test_unknown_stale_future_and_gap_break_confirmation(self):
        self.save();self.observe(0)
        self.observe(60,soc=None);self.observe(120)
        self.assertEqual(self.query()['history'],[])
        self.rules.observe('owner','car',sample(180,soc=20),BASE+900000)
        self.observe(900)
        self.assertEqual(self.query()['history'],[])
        self.rules.observe('owner','car',sample(1600,soc=20),BASE+960000)
        self.observe(960)
        self.assertEqual(self.query()['history'],[])
        self.observe(1700);self.assertEqual(self.query()['history'],[])
        self.observe(1760);self.assertEqual(len(self.query()['history']),1)

    def test_recovery_needs_confirmation_and_unknown_never_recovers(self):
        self.save();self.observe(0);self.observe(60)
        self.observe(120,soc=None);self.observe(180,soc=40)
        self.assertEqual(len(self.query()['history']),1)
        self.observe(240,soc=40)
        self.assertEqual([e['kind'] for e in self.query()['history']],['recovered','raised'])

    def test_cooldown_applies_after_recovery_and_no_spam_while_active(self):
        self.save();self.observe(0);self.observe(60)
        self.observe(120,40);self.observe(180,40)
        for second in range(240,601,60):self.observe(second)
        self.assertEqual(len(self.query()['history']),2)
        self.observe(660);self.observe(720)
        self.assertEqual(len(self.query()['history']),3)

    def test_sampling_epoch_resets_candidates_but_preserves_active_and_cooldown(self):
        self.save()
        self.observe(0,sampling_epoch='first')
        self.observe(60,sampling_epoch='first')
        self.assertEqual(len(self.query()['history']),1)
        self.observe(120,sampling_epoch='outage')
        self.observe(180,sampling_epoch='outage')
        self.assertEqual(len(self.query()['history']),1)
        # A second outage during recovery cannot confirm across its boundary.
        self.observe(240,40,sampling_epoch='outage')
        self.observe(300,40,sampling_epoch='second-outage')
        self.assertEqual(len(self.query()['history']),1)
        self.observe(360,40,sampling_epoch='second-outage')
        self.assertEqual([row['kind'] for row in self.query()['history']],['recovered','raised'])
        for second in (420,480):self.observe(second,sampling_epoch='second-outage')
        self.assertEqual(len(self.query()['history']),2)
        self.observe(660,sampling_epoch='second-outage')
        self.assertEqual(len(self.query()['history']),3)

    def test_scope_isolated_and_only_enabled_rules_run(self):
        saved=self.save(enabled=False)
        self.observe(0);self.observe(60)
        self.assertEqual(self.query()['history'],[])
        self.assertEqual(self.rules.query('other','car')['records'],[])
        self.assertEqual(self.rules.query('owner','other')['records'],[])
        self.save(id=saved['id'],revision=1,enabled=True)
        self.observe(120);self.observe(180)
        self.assertEqual(len(self.query()['history']),1)

    def test_edit_resets_confirmation_and_old_pending_is_cancelled(self):
        saved=self.save(delivery='wecom');self.observe(0)
        self.save(id=saved['id'],revision=1,threshold=10,delivery='wecom')
        self.observe(60);self.observe(120)
        self.assertEqual(self.query()['history'],[])

    def test_undo_delete_restore_and_invalid_input(self):
        saved=self.save()
        self.rules.update('owner','car',dict(action='delete',id=saved['id'],revision=1))
        self.assertTrue(self.query()['records'][0]['deleted'])
        self.rules.update('owner','car',dict(action='undo',revision=2))
        self.assertFalse(self.query()['records'][0]['deleted'])
        for changes in ({'threshold':True},{'confirm_seconds':0},{'cooldown_minutes':0},
                        {'enabled':'true'},{'kind':'raw_expression'},{'delivery':'arbitrary_url'},
                        {'name':'x'*81}):
            with self.assertRaises(ValueError):self.save(revision=3,**changes)

    def test_window_position_without_complete_status_cannot_prove_open(self):
        from zeekr_control.custom_reminders import preview
        raw=sample(0);raw['additionalVehicleStatus']['climateStatus']={'winPosDriver':5}
        result=preview(self.window_rule(),raw,BASE)
        self.assertIsNone(result['matches']);self.assertEqual(result['reason'],'unknown_value')

    @staticmethod
    def windows(seconds,position=8,status=1,**kwargs):
        raw=sample(seconds,**kwargs)
        raw['additionalVehicleStatus']['climateStatus']={
            key+side:str(value) for side in ('Driver','Passenger','DriverRear','PassengerRear')
            for key,value in (('winPos',position),('winStatus',status))}
        return raw

    def window_rule(self,**extra):
        from zeekr_control.custom_reminders import definition
        return definition(dict(name='车窗',kind='parked_windows',enabled=True,recovery=True,
            threshold=25,confirm_seconds=60,cooldown_minutes=1,delivery='in_app',**extra))

    def test_window_verified_pairs_enable_and_preview_without_promoting_unknown_codes(self):
        from zeekr_control.custom_reminders import preview
        rule=self.window_rule()
        self.assertTrue(self.query()['capabilities']['parked_windows'])
        for position,status,expected in ((0,2,False),(8,1,True),(100,1,True),
                (4,1,True),(12,1,True),(99,1,True),(101,1,None),(0,1,None),
                (8,2,None),(100,2,None),(8,3,None),(None,1,None)):
            with self.subTest(position=position,status=status):
                raw=self.windows(0,position,status)
                self.assertIs(preview(rule,raw,BASE)['matches'],expected)
        raw=self.windows(0,0,2)
        raw['additionalVehicleStatus']['climateStatus'].update(winPosPassenger='100',winStatusPassenger='1')
        self.assertIs(preview(rule,raw,BASE)['matches'],True)
        raw['additionalVehicleStatus']['climateStatus'].pop('winStatusPassengerRear')
        self.assertIsNone(preview(rule,raw,BASE)['matches'])
        for changes in ({'speed':1},{'engine':'engine_on'},{'ready':1}):
            self.assertIsNone(preview(rule,self.windows(0,**changes),BASE)['matches'])
        raw=self.windows(0);raw['basicVehicleStatus']['speedValidity']=False
        self.assertIsNone(preview(rule,raw,BASE)['matches'])
        for now in (BASE+180001,BASE-30001):
            self.assertIsNone(preview(rule,self.windows(0),now)['matches'])
        self.assertFalse(self.store.path.exists())

    def test_window_unknown_conflict_and_gaps_cannot_raise_or_recover(self):
        self.save(kind='parked_windows',cooldown_minutes=1,delivery='wecom')
        sent=[]
        def observe(seconds,raw=None,now=None):
            self.rules.observe('owner','car',raw or self.windows(seconds),
                BASE+seconds*1000 if now is None else now,sender=sent.append)
        observe(0)
        observe(60,self.windows(0))  # Repeated cloud timestamp.
        self.assertEqual(sent,[])
        observe(61,self.windows(61,101,1))
        observe(120)
        self.assertEqual(sent,[])
        observe(180)
        self.assertEqual(len(sent),1)
        observe(240,self.windows(240,0,1))  # Conflicting closed position/open enum.
        observe(300,self.windows(300,0,2,engine='engine_on',ready=1))
        self.assertEqual(len(sent),1)
        observe(360,self.windows(360,0,2))
        observe(600,self.windows(600,0,2))  # Four-minute gap breaks window confirmation.
        self.assertEqual(len(sent),1)
        observe(660,self.windows(660,0,2))
        self.assertEqual(len(sent),2)
        self.assertEqual([r['kind'] for r in self.query()['history']],['recovered','raised'])
        self.assertNotIn('离车',sent[0])

    def test_legacy_window_rules_require_resave_and_pending_send_rechecks_windows(self):
        self.store.change('owner','car','rules','save','legacy_window',dict(
            name='旧车窗',kind='parked_windows',enabled=True,recovery=True,
            threshold=25,confirm_seconds=60,cooldown_minutes=1,delivery='wecom'),0)
        sent=[]
        for second in (0,60,120):
            self.rules.observe('owner','car',self.windows(second),BASE+second*1000,sender=sent.append)
        self.assertEqual(sent,[])
        self.save(id='legacy_window',revision=1,kind='parked_windows',delivery='wecom')
        for second in (180,240):
            self.rules.observe('owner','car',self.windows(second),BASE+second*1000)
        self.assertEqual(self.query()['history'][0]['delivery'],'pending')
        self.rules.deliver('owner','car',self.windows(300,0,2),BASE+300000,sent.append)
        self.assertEqual(sent,[])
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_owner_window_operation_replay_does_not_turn_delivery_delay_into_confirmation(self):
        from zeekr_control.custom_reminders import preview
        self.save(kind='parked_windows',delivery='wecom')
        rule=self.window_rule()
        sent=[]
        # Actual window pairs and relative timestamps from the two owner operations.
        # Parking fields are synthetic; this is not a real notification acceptance test.
        for vehicle_ms,observed_ms,position,status,expected in (
                (0,5510,0,2,False),(17783,67499,8,1,True),
                (77852,88037,8,1,True),(90972,108812,8,1,True),
                (112427,129466,0,2,False),(185000,191471,0,2,False),
                (209569,232920,100,1,True),(209569,253449,100,1,True),
                (254163,294812,0,2,False)):
            raw=self.windows(0,position,status);raw['updateTime']=BASE+vehicle_ms
            now=BASE+observed_ms
            self.assertIs(preview(rule,raw,now)['matches'],expected)
            self.rules.observe('owner','car',raw,now,sender=sent.append)
        self.assertEqual(sent,[])
        self.assertEqual(self.query()['history'],[])

    def test_one_conflicting_window_blocks_decision_and_expired_pending_is_cancelled(self):
        from zeekr_control.custom_reminders import preview
        raw=self.windows(0)
        raw['additionalVehicleStatus']['climateStatus']['winStatusDriverRear']='2'
        self.assertIsNone(preview(self.window_rule(),raw,BASE)['matches'])
        self.save(kind='parked_windows',delivery='wecom')
        for second in (0,60):self.rules.observe('owner','car',self.windows(second),BASE+second*1000)
        sent=[]
        self.rules.deliver('owner','car',self.windows(241),BASE+241000,sent.append)
        self.assertEqual(sent,[])
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_parked_charging_needs_both_park_and_verified_charge_evidence(self):
        from zeekr_control.custom_reminders import preview
        rule=dict(kind='parked_charging')
        raw=sample(0);e=raw['additionalVehicleStatus']['electricVehicleStatus']
        e.update(chargeLidAcStatus=1,chargeLidDcAcStatus=2,chargerState=2,statusOfChargerConnection=3,
                 dcChargeSts=0,dcChargePileIAct=0,chargeUAct=220,chargeIAct=30)
        self.assertTrue(preview(rule,raw,BASE)['matches'])
        e['chargerState']=999
        self.assertIsNone(preview(rule,raw,BASE)['matches'])

    def test_wecom_delivers_once_with_safe_content(self):
        messages=[];self.save(delivery='wecom',name='合成提醒')
        self.observe(0,sender=messages.append);self.observe(60,sender=messages.append)
        self.observe(120,sender=messages.append)
        self.assertEqual(len(messages),1)
        self.assertEqual(self.query()['history'][0]['delivery'],'sent')
        for secret in ('position','latitude','longitude','vehicle_key','owner'):
            self.assertNotIn(secret,json.dumps([messages,self.query()]))

    def test_ambiguous_send_not_retried(self):
        from zeekr_control.notifications import DeliveryError
        messages=[]
        def sender(message):messages.append(message);raise DeliveryError('SECRET',ambiguous=True)
        self.save(delivery='wecom');self.observe(0,sender=sender);self.observe(60,sender=sender)
        self.observe(120,sender=sender)
        self.assertEqual(len(messages),1)
        history=self.query()['history'];self.assertEqual(history[0]['delivery'],'uncertain')
        self.assertNotIn('SECRET',json.dumps(history))

    def test_in_app_never_calls_sender(self):
        self.save();self.observe(0,sender=lambda _:self.fail('no send'))
        self.observe(60,sender=lambda _:self.fail('no send'))
        self.assertEqual(self.query()['history'][0]['delivery'],'local')

    def test_guard_change_rolls_back_before_event_or_delivery(self):
        self.save(delivery='wecom');self.observe(0)
        def guard():raise ValueError('account switched')
        with self.assertRaises(ValueError):self.observe(60,guard=guard,sender=lambda _:self.fail('no send'))
        self.assertEqual(self.query()['history'],[])

    def test_preview_is_readonly_even_when_matching(self):
        self.save()
        before=self.store.path.read_bytes()
        self.rules.preview('owner','car',self.query()['records'][0]['body'],sample(0,soc=20),BASE)
        self.assertEqual(self.store.path.read_bytes(),before)
        self.assertEqual(self.query()['history'],[])

    def test_restart_marks_interrupted_send_uncertain_and_never_retries(self):
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        with self.store.connect(write=True) as db,db:
            db.execute("UPDATE rule_history SET delivery='sending'")
        self.rules.recover()
        self.observe(120,sender=lambda _:self.fail('interrupted send must not retry'))
        self.assertEqual(self.query()['history'][0]['delivery'],'uncertain')

    def test_disabled_edited_and_expired_pending_never_send(self):
        saved=self.save(delivery='wecom');self.observe(0);self.observe(60)
        self.save(id=saved['id'],revision=1,delivery='wecom',enabled=False)
        self.observe(120,sender=lambda _:self.fail('disabled rule must not send'))
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')
        self.save(id=saved['id'],revision=2,delivery='wecom')
        self.observe(180);self.observe(240)
        self.observe(1000,sender=lambda _:self.fail('expired event must not send'))
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_pending_recovery_is_not_sent_after_condition_returns(self):
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        self.observe(120,40);self.observe(180,40)
        # Both queued events must be discarded when neither has fresh confirmed state.
        self.observe(240,soc=None,sender=lambda _:self.fail('unknown must not send'))
        self.assertTrue(all(row['delivery']=='cancelled' for row in self.query()['history']))

    def test_no_recovery_notification_still_records_local_transition(self):
        self.save(delivery='wecom',recovery=False);messages=[]
        for seconds,soc in ((0,20),(60,20),(120,40),(180,40)):
            self.observe(seconds,soc,sender=messages.append)
        self.assertEqual(len(messages),1)
        self.assertEqual(self.query()['history'][0]['kind'],'recovered')
        self.assertEqual(self.query()['history'][0]['delivery'],'local')

    def test_permanent_failure_is_reported_without_secret_or_retry(self):
        from zeekr_control.notifications import DeliveryError
        def sender(message):raise DeliveryError('SECRET',permanent=True)
        self.save(delivery='wecom');self.observe(0,sender=sender);self.observe(60,sender=sender)
        self.observe(120,sender=lambda _:self.fail('no retry'))
        self.assertEqual(self.query()['history'][0]['delivery'],'failed')
        self.assertNotIn('SECRET',json.dumps(self.query()))

    def test_guard_change_after_claim_cancels_unsent_message(self):
        self.save(delivery='wecom');self.observe(0);calls=[]
        def guard():
            calls.append(1)
            if len(calls)==3:raise ValueError('account switched before send')
        with self.assertRaises(ValueError):self.observe(60,guard=guard,sender=lambda _:self.fail('no send'))
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')

    def test_undo_creation_cleans_orphan_state_and_cancels_pending_without_sending(self):
        self.save(delivery='wecom');self.observe(0);self.observe(60)
        self.rules.update('owner','car',dict(action='undo',revision=1))
        self.observe(120,sender=lambda _:self.fail('Removed rule must not send'))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rule_states WHERE owner=? AND vehicle=?',('owner','car')).fetchone()[0],0)
        self.assertEqual(self.query()['history'][0]['delivery'],'cancelled')


if __name__=='__main__':unittest.main()
