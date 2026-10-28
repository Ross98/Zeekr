import unittest
import tempfile
from pathlib import Path
from zeekr_control.tyre_notifications import transition, TyreNotifications
from zeekr_control.personal_store import PersonalStore
from zeekr_control.notifications import DeliveryError
from test_monitor import sample, BASE

class TyreTransitionTests(unittest.TestCase):
    def test_regressed_observation_breaks_confirmation(self):
        for stamp,now in ((990000,1010000),(1010000,990000)):
            with self.subTest(stamp=stamp,now=now):
                s,e=self.step({},0,208)
                s,e=transition(s,{'左前':260},stamp,now,260)
                self.assertEqual(e,[])
                s,e=self.step(s,20,208);self.assertEqual(e,[])
                s,e=self.step(s,40,208);self.assertEqual(e[0]['level'],2)


    def step(self,state,seconds,pressure=228,base=260):
        return transition(state,{'左前':pressure},1000000+seconds*1000,1000000+seconds*1000,base)
    def test_warning_new_samples_duration_repeat_and_recovery(self):
        s={}
        for sec in [0,20,40,100]:s,e=self.step(s,sec);self.assertEqual(e,[])
        s,e=self.step(s,120);self.assertEqual(e,[{'wheel':'左前','level':1,'pressure':228}])
        s,e=self.step(s,140);self.assertEqual(e,[])
        for sec in [160,180,220]:s,e=self.step(s,sec,250);self.assertEqual(e,[])
        s,e=self.step(s,280,250);self.assertEqual(e,[{'wheel':'左前','level':0,'pressure':250}])
    def test_severe_escalation_no_downgrade_and_repeat_cache(self):
        s,e=self.step({},0,208);self.assertEqual(e,[])
        s,e=self.step(s,0,208);self.assertEqual(e,[])
        s,e=self.step(s,20,208);self.assertEqual(e[0]['level'],2)
        s,e=self.step(s,40,228);self.assertEqual(e,[])
        s,e=self.step(s,60,208);self.assertEqual(e,[])
    def test_zero_missing_stale_gap_and_profile(self):
        s,e=self.step({},0,208)
        s,e=self.step(s,20,0);self.assertEqual(e,[])
        s,e=self.step(s,40,208);self.assertEqual(e,[])
        s,e=self.step(s,240,208);self.assertEqual(e,[])
        s,e=self.step(s,260,208);self.assertEqual(e[0]['level'],2)
        s,e=self.step({},0,232,290);s,e=self.step(s,20,232,290);self.assertEqual(e[0]['level'],2)
    def test_grouped_wheels_and_exact_warning_boundary(self):
        s={}
        for sec in [0,60,120]:s,e=transition(s,{'左前':234,'右前':234},1000000+sec*1000,1000000+sec*1000,260)
        self.assertEqual(len(e),2)

    def test_missing_wheel_and_stale_timestamp_break_confirmation(self):
        s,e=self.step({},0,208)
        s,e=transition(s,{},1020000,1020000,260)
        s,e=self.step(s,40,208);self.assertEqual(e,[])
        s,e=transition(s,{'左前':208},1040000,1240000,260)
        s,e=self.step(s,260,208);self.assertEqual(e,[])

    def test_same_timestamp_revision_resets_candidate(self):
        s,e=self.step({},0,208)
        s,e=self.step(s,0,260)
        s,e=self.step(s,20,208);self.assertEqual(e,[])
        s,e=self.step(s,40,208);self.assertEqual(e[0]['level'],2)

class TyrePersistenceTests(unittest.TestCase):
    def test_retry_interval_starts_after_slow_failed_send_not_batch_start(self):
        from unittest.mock import patch
        from zeekr_control.notifications import DeliveryError
        self.observe(0);self.observe(20)
        clock=[100.0];calls=[]
        def fail(*arguments):
            calls.append(True)
            clock[0]+=20
            raise DeliveryError('synthetic transient failure')
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.engine.deliver('owner','vehicle',BASE+20000,fail,None)
            self.engine.deliver('owner','vehicle',BASE+80000,fail,None)
            self.assertEqual(calls,[True])
            with self.store.connect() as db:
                self.assertEqual(db.execute('SELECT next_bark FROM tyre_outbox').fetchone()[0],BASE+100000)
            self.engine.deliver('owner','vehicle',BASE+100000,fail,None)
            self.assertEqual(len(calls),2)
            with self.store.connect() as db:
                self.assertEqual(db.execute('SELECT attempts_bark,next_bark FROM tyre_outbox').fetchone(),(2,BASE+240000))
            for seconds in (240,500,1000):
                self.engine.deliver('owner','vehicle',BASE+seconds*1000,fail,None)
            self.engine.deliver('owner','vehicle',BASE+3000000,fail,None)
        self.assertEqual(len(calls),5)
        self.assertEqual(self.engine.query('owner','vehicle')['history'][0]['bark'],'failed')

    def test_second_channel_uses_elapsed_time_when_its_cooldown_becomes_due(self):
        from unittest.mock import patch
        self.observe(0);self.observe(20)
        with self.store.connect(write=True) as db,db:
            db.execute('UPDATE tyre_outbox SET next_wecom=?',(BASE+30000,))
        clock=[100.0]
        def slow_bark(*arguments):
            self.bark.append(arguments)
            clock[0]+=20
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.engine.deliver('owner','vehicle',BASE+20000,slow_bark,self.wecom.append)
        self.assertEqual((len(self.bark),len(self.wecom)),(1,1))

    def test_second_channel_does_not_bypass_remaining_cooldown(self):
        from unittest.mock import patch
        self.observe(0);self.observe(20)
        with self.store.connect(write=True) as db,db:
            db.execute('UPDATE tyre_outbox SET next_wecom=?',(BASE+50000,))
        clock=[100.0]
        def slow_bark(*arguments):clock[0]+=20
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            self.engine.deliver('owner','vehicle',BASE+20000,slow_bark,self.wecom.append)
            self.engine.deliver('owner','vehicle',BASE+49000,None,self.wecom.append)
            self.assertEqual(self.wecom,[])
            self.engine.deliver('owner','vehicle',BASE+50000,None,self.wecom.append)
        self.assertEqual(len(self.wecom),1)

    def test_new_recovery_during_preparation_invalidates_loaded_grouped_payload(self):
        self.observe(0,right=200);self.observe(20,right=200)
        identity=self.engine.query('owner','vehicle')['history'][0]['id']
        changed=[]
        def guard():
            with self.store.connect() as db:
                status=db.execute('SELECT bark FROM tyre_outbox WHERE id=?',(identity,)).fetchone()[0]
            if status=='preparing' and not changed:
                changed.append(True)
                for seconds in (40,100,160):self.observe(seconds,left=260,right=200)
        self.engine.deliver('owner','vehicle',BASE+20000,lambda *args:self.bark.append(args),None,guard)
        self.assertEqual(self.bark,[])
        self.engine.deliver('owner','vehicle',BASE+160000,**self.send())
        self.assertEqual(len(self.bark),2)
        self.assertIn('右前',self.bark[0][1]);self.assertNotIn('左前',self.bark[0][1])
        self.assertIn('恢复',self.bark[1][0])

    def test_config_change_after_preparation_cancels_unsent_channels(self):
        self.observe(0);self.observe(20)
        changed=[]
        def guard():
            with self.store.connect() as db:status=db.execute('SELECT bark FROM tyre_outbox').fetchone()[0]
            if status=='preparing' and not changed:
                changed.append(True)
                self.engine.update('owner','vehicle',dict(action='save',revision=0,enabled=False,load='light'))
        self.engine.deliver('owner','vehicle',BASE+20000,lambda *args:self.bark.append(args),None,guard)
        self.engine.deliver('owner','vehicle',BASE+40000,**self.send())
        self.assertEqual((self.bark,self.wecom),([],[]))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT bark,wecom,attempts_bark,attempts_wecom FROM tyre_outbox').fetchone(),
                             ('cancelled','cancelled',0,0))

    def test_preparation_interruption_recovers_without_ambiguous_send(self):
        self.observe(0);self.observe(20)
        def guard():
            with self.store.connect() as db:status=db.execute('SELECT bark FROM tyre_outbox').fetchone()[0]
            if status=='preparing':raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.engine.deliver('owner','vehicle',BASE+20000,lambda *args:self.bark.append(args),None,guard)
        self.assertEqual(self.bark,[])
        self.engine=TyreNotifications(self.store)
        self.engine.deliver('owner','vehicle',BASE+40000,**self.send())
        self.assertEqual((len(self.bark),len(self.wecom)),(1,1))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT bark,attempts_bark FROM tyre_outbox').fetchone(),('sent',1))

    def test_guard_cancellation_after_claim_remains_provably_unsent_and_resumes(self):
        from zeekr_control.delivery_state import DeliveryCancelled
        self.observe(0);self.observe(20)
        def guard():
            with self.store.connect() as db:
                status=db.execute('SELECT bark FROM tyre_outbox').fetchone()[0]
            if status in ('sending','preparing'):raise DeliveryCancelled()
        with self.assertRaises(DeliveryCancelled):
            self.engine.deliver('owner','vehicle',BASE+20000,lambda *args:self.bark.append(args),None,guard)
        self.assertEqual(self.bark,[])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT bark,attempts_bark FROM tyre_outbox').fetchone(),('pending',0))
        self.engine=TyreNotifications(self.store)
        self.engine.deliver('owner','vehicle',BASE+40000,**self.send())
        self.assertEqual((len(self.bark),len(self.wecom)),(1,1))

    def test_sampling_epoch_resets_recovery_without_losing_active_level(self):
        self.observe(0,sampling_epoch='first')
        self.observe(20,sampling_epoch='first')
        self.assertEqual(len(self.engine.query('owner','vehicle')['history']),1)
        self.observe(40,sampling_epoch='outage')
        self.observe(60,sampling_epoch='outage')
        self.assertEqual(len(self.engine.query('owner','vehicle')['history']),1)
        self.observe(80,left=260,sampling_epoch='outage')
        self.observe(140,left=260,sampling_epoch='second-outage')
        self.observe(200,left=260,sampling_epoch='second-outage')
        self.assertEqual(len(self.engine.query('owner','vehicle')['history']),1)
        self.observe(260,left=260,sampling_epoch='second-outage')
        history=self.engine.query('owner','vehicle')['history']
        self.assertEqual(len(history),2)
        self.assertEqual(history[0]['events'][0]['level'],0)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=PersonalStore(Path(self.temp.name)/'private'/'personal.sqlite3')
        self.engine=TyreNotifications(self.store);self.bark=[];self.wecom=[]

    def observe(self,seconds,left=200,right=260,**kwargs):
        raw=sample(seconds)
        raw['additionalVehicleStatus']['maintenanceStatus'].update(tyreStatusDriver=left,tyreStatusPassenger=right,tyreStatusDriverRear=260,tyreStatusPassengerRear=260)
        self.engine.observe('owner','vehicle',raw,BASE+seconds*1000,**kwargs)

    def send(self):
        return dict(bark=lambda *args:self.bark.append(args),wecom=self.wecom.append)

    def test_grouped_independent_channels_restart_and_owner_isolation(self):
        self.observe(0,right=200,**self.send());self.observe(20,right=200,**self.send())
        self.assertEqual((len(self.bark),len(self.wecom)),(1,1))
        self.assertIn('左前',self.bark[0][1]);self.assertIn('右前',self.bark[0][1])
        self.assertIn('轮胎独立更新时间未提供',self.wecom[0])
        self.engine=TyreNotifications(self.store)
        self.observe(40,right=200,**self.send())
        self.assertEqual(len(self.bark),1)
        self.assertEqual(self.engine.query('other','vehicle')['history'],[])
        self.assertEqual(self.engine.query('owner','other')['history'],[])

    def test_ambiguous_failure_not_retried_other_channel_still_sends(self):
        calls=[]
        def ambiguous(*args):
            calls.append(args);raise DeliveryError('synthetic',ambiguous=True)
        self.observe(0);self.observe(20,bark=ambiguous,wecom=self.wecom.append)
        self.observe(100,bark=ambiguous,wecom=self.wecom.append)
        history=self.engine.query('owner','vehicle')['history']
        self.assertEqual((len(calls),len(self.wecom)),(1,1))
        self.assertEqual((history[0]['bark'],history[0]['wecom']),('uncertain','sent'))

    def test_clear_failure_retries_after_delay_and_has_attempt_limit(self):
        from unittest.mock import patch
        calls=[]
        def transient(*args):
            calls.append(args);raise DeliveryError('synthetic')
        with patch('time.monotonic',return_value=100.0):
            self.observe(0);self.observe(20,bark=transient)
            self.engine.deliver('owner','vehicle',BASE+40000,transient,None)
            self.assertEqual(len(calls),1)
            for seconds in (80,200,440,920):self.engine.deliver('owner','vehicle',BASE+seconds*1000,transient,None)
        self.assertEqual(len(calls),5)
        self.assertEqual(self.engine.query('owner','vehicle')['history'][0]['bark'],'failed')

    def test_config_revision_full_load_disabled_and_pending_cancellation(self):
        self.observe(0);self.observe(20)
        result=self.engine.update('owner','vehicle',dict(action='save',revision=0,enabled=True,load='full'))
        self.assertEqual((result['base'],result['warning'],result['severe'],result['recovery']),(290,261,232,275.5))
        with self.assertRaises(ValueError):self.engine.update('owner','vehicle',dict(action='save',revision=0,enabled=False,load='light'))
        self.observe(40,**self.send());self.assertEqual(self.bark,[])
        self.assertEqual(self.engine.query('owner','vehicle')['history'][0]['bark'],'cancelled')
        self.engine.update('owner','vehicle',dict(action='save',revision=1,enabled=False,load='full'))
        self.observe(60,**self.send());self.observe(80,**self.send());self.assertEqual(self.bark,[])

    def test_new_wheel_does_not_discard_pending_other_wheel(self):
        self.observe(0);self.observe(20)
        self.observe(40,right=200);self.observe(60,right=200)
        self.engine.deliver('owner','vehicle',BASE+60000,**self.send())
        self.assertEqual(len(self.bark),2)
        self.assertIn('左前',self.bark[0][1]);self.assertIn('右前',self.bark[1][1])

    def test_recovery_supersedes_only_overlapping_pending_wheel(self):
        self.observe(0,right=200);self.observe(20,right=200)
        for seconds in (40,100,160):self.observe(seconds,left=260,right=200)
        self.engine.deliver('owner','vehicle',BASE+160000,**self.send())
        self.assertEqual(len(self.bark),2)
        self.assertNotIn('左前',self.bark[0][1]);self.assertIn('右前',self.bark[0][1])
        self.assertIn('恢复',self.bark[1][0]);self.assertIn('左前',self.bark[1][1])

    def test_sent_history_does_not_block_new_outbox_and_crash_is_uncertain(self):
        import json
        self.observe(0);self.observe(20,**self.send())
        with self.store.connect(write=True) as db,db:
            row=db.execute('SELECT * FROM tyre_outbox').fetchone()
            for number in range(12):
                values=list(row);values[0]='old-'+str(number);values[4]=BASE
                db.execute('INSERT INTO tyre_outbox VALUES('+','.join('?' for _ in values)+')',values)
        for seconds in (40,100,160):self.observe(seconds,left=260,**self.send())
        self.assertEqual(len(self.bark),2)
        self.observe(180);self.observe(200)
        with self.store.connect(write=True) as db,db:db.execute("UPDATE tyre_outbox SET bark='sending' WHERE bark='pending'")
        self.engine.deliver('owner','vehicle',BASE+200000,**self.send())
        self.assertEqual(len(self.bark),2)
        self.assertEqual(self.engine.query('owner','vehicle')['history'][0]['bark'],'uncertain')

    def test_guard_failure_rolls_back_observation(self):
        self.observe(0)
        calls=[]
        def guard():
            calls.append(1)
            if len(calls)>1:raise ValueError('changed owner')
        with self.assertRaises(ValueError):self.observe(20,guard=guard,**self.send())
        self.assertEqual(self.engine.query('owner','vehicle')['history'],[])
        self.observe(20,**self.send());self.assertEqual(len(self.bark),1)
