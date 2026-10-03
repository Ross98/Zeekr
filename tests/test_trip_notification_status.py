import copy
import unittest
from zeekr_control.report_attention import build
from zeekr_control.report_render import render

BASE=1790000000000

class TripNotificationStatusTests(unittest.TestCase):
    def report(self,**changes):
        parking=dict(state_time=BASE+60000,off=True,locked=True,charging=False,closures={'doors':['closed']*4,'windows':['closed']*4},trunk='closed',dc_lid='closed')
        parking.update(changes)
        report=dict(start_time=BASE,end_time=BASE+60000,event_created_at=BASE+60000,
            start={'soc':80},end={'soc':79,'inside_temp':{'value':25},'outside_temp':{'value':20},
             'tyres':[{'position':'左前','pressure':{'value':250},'temperature':{'value':30}}]},parking=parking,
            metrics={'duration_seconds':60,'distance_km':2,'soc_delta':-1,'estimated_kwh':.86},
            quality={'parking_samples':1},partial=False)
        report['attention']=build('trip_end',report['end'],parking,report['event_created_at'])
        return report

    def test_normal_trip_keeps_core_and_omits_status_inventory(self):
        text,_=render('trip_end',self.report(),'synthetic')
        for value in ['2 公里','电量：80% → 79%','估算耗电：约 0.9 kWh']:self.assertIn(value,text)
        for value in ['锁车','四门','四窗','尾门','胎压','胎温','温度与轮胎','停车后状态','需留意']:self.assertNotIn(value,text)

    def test_confirmed_exception_is_shown_without_other_normal_states(self):
        report=self.report(dc_lid='open')
        report['attention']['changes']=[{'key':'lock','time':BASE,'text':'后续观测已确认锁车'}]
        text,_=render('trip_end',report,'synthetic')
        self.assertIn('直流口盖打开',text)
        self.assertNotIn('后续观测已确认锁车',text)
        self.assertNotIn('四门关闭',text)

    def test_unknown_is_not_promoted_to_abnormal(self):
        text,_=render('trip_end',self.report(locked=None,closures={'doors':['unknown']*4,'windows':['unknown']*4},trunk='unknown'),'synthetic')
        self.assertNotIn('锁车',text);self.assertNotIn('尾门',text);self.assertNotIn('需留意',text)

    def test_stale_open_status_does_not_claim_current_exception(self):
        report=self.report(dc_lid='open',state_time=BASE-600000)
        text,_=render('trip_end',report,'synthetic')
        self.assertNotIn('直流口盖打开',text)
        self.assertIn('旧观测',text)

    def test_budget_fallback_keeps_exception_and_partial_warning(self):
        report=self.report(dc_lid='open');report['partial']=True
        text,_=render('trip_end',report,'synthetic',target=256)
        self.assertIn('直流口盖打开',text);self.assertIn('部分记录',text)
        self.assertNotIn('锁车、门窗及尾门',text)
        self.assertLessEqual(len(text.encode()),2048)

    def test_charge_report_uses_approved_brief_template(self):
        report=self.report();report['end']=copy.deepcopy(report['parking'])
        text,_=render('charge_end',report,'synthetic')
        self.assertNotIn('四门关闭',text)

    def test_open_cover_during_charging_or_unknown_activity_is_not_abnormal(self):
        for charging in [True,None]:
            with self.subTest(charging=charging):
                text,_=render('trip_end',self.report(dc_lid='open',charging=charging),'synthetic')
                self.assertNotIn('直流口盖打开',text)
                self.assertNotIn('需留意',text)
