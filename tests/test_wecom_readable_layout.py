"""Approved readable summaries; synthetic reports, no outbound requests."""
import copy
import unittest
from zeekr_control.report_render import render
from zeekr_control.report_markdown import markdown_for
import test_trip_notification_status as fixture


class WeComReadableLayoutTests(unittest.TestCase):
    def report(self):
        report=fixture.TripNotificationStatusTests().report()
        report['metrics'].update(distance_km=25,duration_seconds=2340,estimated_kwh=6,
                                 estimated_kwh_100km=24)
        report['comparison']={'items':[{'metric':'minutes_per_km','note':'相近里程','n':10,'current':1,'median':2}]}
        return report

    def test_trip_sections_and_confirmed_parking_are_readable_without_diagnostics(self):
        report=self.report();before=copy.deepcopy(report)
        text,_=render('trip_end',report,'synthetic',{'start':'家','end':'公司'})
        for phrase in ('25 公里 · 39 分钟','【电量与能耗】','24 kWh/100km','【停车状态】',
                       '已锁车','四门、四窗、尾门已关闭','云端观测，可能延迟'):
            self.assertIn(phrase,text)
        for phrase in ('历史参考','独立观测','首次活动样本','发现延迟','编号：','胎温','温度与轮胎'):
            self.assertNotIn(phrase,text)
        self.assertEqual(report,before)
        self.assertIn('**电量与能耗**',markdown_for(text))
        self.assertIn('<font color="comment">',markdown_for(text))

    def test_unknown_stale_or_incomplete_parking_cannot_claim_all_closed(self):
        for changes in ({'closures':{'doors':['closed']*3,'windows':['closed']*4}},
                        {'state_time':0},{'trunk':'unknown'}):
            report=self.report();report['parking'].update(changes)
            text,_=render('trip_end',report,'synthetic')
            self.assertNotIn('四门、四窗、尾门已关闭',text)
        report=self.report();report['parking']['locked']=None
        text,_=render('trip_end',report,'synthetic')
        self.assertNotIn('已锁车',text)
        report=self.report();report['attention']['fresh']=False
        text,_=render('trip_end',report,'synthetic')
        self.assertNotIn('已锁车',text)

    def test_charge_keeps_estimates_and_mode_without_inventing_connector_or_stop_reason(self):
        report=self.report();report['start'].update(soc=35,charging_mode='dc')
        report['end']['soc']=80;report['metrics'].update(soc_delta=45,estimated_kwh=45)
        text,_=render('charge_end',report,'synthetic')
        for phrase in ('【充电概况】','35% → 80%','45 kWh','直流快充','SOC × 容量'):
            self.assertIn(phrase,text)
        for phrase in ('充满','充电枪仍连接','平均功率','最高采样功率','功率有效覆盖','编号：'):
            self.assertNotIn(phrase,text)

    def test_partial_and_verified_alert_survive_small_budget(self):
        report=self.report();report['partial']=True
        report['attention']['items']=[{'key':'verified','level':'warning','text':'已核验异常'}]
        text,_=render('trip_end',report,'synthetic',target=256,
                      address={'start':'超长地址'*100,'end':'超长地址'*100})
        self.assertIn('部分记录',text);self.assertIn('已核验异常',text)
        self.assertIn('实际开始时间未知',text)
        self.assertLessEqual(len(text.encode()),2048)
        self.assertNotIn('编号：',text)

    def test_starts_are_short_and_unknown_start_is_explicit(self):
        report=self.report();report['partial']=True
        text,_=render('charge_start',report,'synthetic')
        self.assertIn('首次观测',text);self.assertIn('实际开始时间未知',text)
        self.assertNotIn('首次活动样本',text);self.assertNotIn('目标电量：暂未取得',text)
        self.assertNotIn('电压',text);self.assertNotIn('四门',text)
        text,_=render('trip_start',report,'synthetic')
        self.assertIn('🚗 行程开始',text);self.assertNotIn('充电已停止',text)

    def test_legacy_trip_start_uses_same_layout_and_existing_range(self):
        from zeekr_control.monitor import message_for
        data=dict(start_time=1792889820000,end_time=1792889820000,
                  start_soc=62,end_soc=62,start_range_km=320,start_address='合成起点',partial=True)
        text=message_for('trip_start',data,'synthetic')
        self.assertIn('🚗 行程开始',text);self.assertIn('云端续航：320 km',text)
        self.assertIn('首次观测',text);self.assertIn('实际开始时间未知',text)
        self.assertNotIn('事件编号',text)

    def test_zero_is_valid_and_invalid_values_never_print_nan_inf_or_false_zero(self):
        report=self.report();report['metrics'].update(distance_km=0,estimated_kwh=0,estimated_kwh_100km=0)
        text,_=render('trip_end',report,'synthetic')
        self.assertIn('0 公里',text);self.assertIn('约 0 kWh',text)
        report['start']['soc']=float('inf');report['end']['soc']=float('nan')
        report['metrics'].update(distance_km=None,estimated_kwh=float('inf'),estimated_kwh_100km=-1)
        text,_=render('trip_end',report,'synthetic')
        self.assertIn('未知 公里',text);self.assertIn('估算耗电：未知',text)
        self.assertNotIn('nan',text);self.assertNotIn('inf',text)
        self.assertNotIn('电量：0%',text)
