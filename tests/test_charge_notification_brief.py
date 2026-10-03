import copy
import unittest
from zeekr_control.report_render import render

BASE=1790000000000
class ChargeNotificationBriefTests(unittest.TestCase):
    def report(self):
        return dict(start_time=BASE,end_time=BASE+2700000,partial=False,
          start={'soc':35,'range_km':150,'charging_mode':'dc'},
          end={'soc':80,'range_km':340,'state_time':BASE+2700000,'charging':False,'dc_lid':'open','off':True,'locked':True,'trunk':'closed','closures':{'doors':['closed']*4,'windows':['closed']*4},'voltage':{'value':400},'current':{'value':0},'tyres':[]},
          metrics={'duration_seconds':2700,'soc_delta':45,'estimated_kwh':38.7,'range_delta_km':190,'sampled_peak_kw':120,'average_power_kw':51.6,'tail_power_drop_percent':30,'power_covered_seconds':2700,'power_coverage':1},
          quality={'observation_count':135},attention={'fresh':True,'items':[{'key':'dc_lid','level':'status','text':'直流口盖打开'}],'changes':[]},
          comparison={'items':[{'metric':'average_power_kw','note':'相近电量','n':10,'current':51.6,'median':50}]})
    def test_normal_report_is_core_only(self):
        text,_=render('charge_end',self.report(),'synthetic')
        for value in ['充电已停止','45 分钟','35% → 80%','38.7 kWh','增加190公里','类型：直流','120 kW','51.6 kW']:self.assertIn(value,text)
        for value in ['四门','锁车','胎压','停止观测','停止原因','目标电量','充电枪','后段较前段','历史参考','独立观测','直流口盖打开']:self.assertNotIn(value,text)
    def test_insufficient_samples_and_partial_remain_explicit(self):
        report=self.report();report['partial']=True;report['metrics'].update(average_power_kw=None,power_coverage=.4,power_covered_seconds=1080,estimated_kwh=None)
        text,_=render('charge_end',report,'synthetic')
        for value in ['部分记录','平均功率：未知','估算充入：未知','功率有效覆盖','仅汇总已观测区间']:self.assertIn(value,text)
        self.assertNotIn('充满',text)
    def test_verified_alert_survives_budget_and_stale_alert_is_suppressed(self):
        report=self.report();report['attention']['items']=[{'key':'verified','level':'warning','text':'已核验异常示例'}]
        text,_=render('charge_end',report,'synthetic',target=256);self.assertIn('已核验异常示例',text)
        self.assertIn('实际开始时间未知',text)
        report['attention']['fresh']=False
        text,_=render('charge_end',report,'synthetic');self.assertNotIn('已核验异常示例',text)
    def test_real_zero_is_kept_and_source_unchanged(self):
        report=self.report();report['metrics'].update(estimated_kwh=0,average_power_kw=0);before=copy.deepcopy(report)
        text,_=render('charge_end',report,'synthetic')
        self.assertIn('估算充入：约0 kWh',text);self.assertIn('平均功率：0 kW',text)
        self.assertEqual(report,before)
