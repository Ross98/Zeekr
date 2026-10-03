import unittest
import tempfile
from pathlib import Path
from zeekr_control.tyre_notifications import transition, TyreNotifications
from zeekr_control.personal_store import PersonalStore
from zeekr_control.notifications import DeliveryError
from test_monitor import sample, BASE

class TyreTransitionTests(unittest.TestCase):
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
        calls=[]
        def transient(*args):
            calls.append(args);raise DeliveryError('synthetic')
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
