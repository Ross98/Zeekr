"""Design acceptance tests use synthetic data only."""
import unittest
import json
import sqlite3
import tempfile
from pathlib import Path

from zeekr_control.report_telemetry import normalize
from zeekr_control.report_telemetry import capability_registry
from zeekr_control.report_metrics import trip_metrics, charge_metrics, historical_median
from zeekr_control.report_render import clean_text, render
from zeekr_control.report_history import compare
try:
    from test_monitor import BASE, sample
except ImportError:
    from tests.test_monitor import BASE, sample


class TelemetryTests(unittest.TestCase):
    def test_ac_report_keeps_generic_electrical_values_separate_from_dc(self):
        from test_ac_charging import ac_sample
        raw = ac_sample(chargeUAct=220, chargeIAct=16, dcChargePileUAct=360)
        report = normalize(raw, BASE)
        self.assertEqual(report['charging_mode'], 'ac')
        self.assertEqual(report['ac_voltage']['value'], 220)
        self.assertEqual(report['ac_current']['value'], 16)
        self.assertEqual(report['voltage']['value'], 360)
        self.assertAlmostEqual(report['power_kw'], 3.52)
        self.assertEqual(report['ac_lid'], 'open')
        self.assertEqual(capability_registry()['ac_charging']['status'], 'enabled')

    def test_numeric_confusion_and_pending_capabilities_are_conservative(self):
        raw = sample(0, soc=80)
        raw['additionalVehicleStatus']['electricVehicleStatus']['chargeLevel'] = True
        data = normalize(raw, BASE)
        self.assertIsNone(data['soc'])
        self.assertEqual(data['capabilities']['target_soc'], 'pending_evidence')

    def test_capability_registry_keeps_unverified_rules_disabled(self):
        registry=capability_registry()
        self.assertEqual(registry['target_soc']['status'],'pending_evidence')
        self.assertIsNone(registry['target_soc']['decoder'])
        self.assertEqual(registry['dc_charging']['status'],'enabled')
        raw=sample(0)
        self.assertEqual(normalize(raw,BASE,capabilities=('target_soc',))['capabilities']['target_soc'],'pending_evidence')

    def test_nonzero_openings_are_unknown_and_positions_do_not_shift(self):
        raw = sample(0)
        raw['additionalVehicleStatus']['drivingSafetyStatus'] = {
            'doorOpenStatusDriver': 0, 'doorOpenStatusPassenger': 9}
        data = normalize(raw, BASE)
        self.assertEqual(data['closures']['doors'], ['closed', 'unknown', 'unknown', 'unknown'])
        self.assertEqual([x['position'] for x in data['tyres']], ['左前', '右前', '左后', '右后'])

    def test_temperature_future_over_30_seconds_is_invalid(self):
        raw=sample(0); raw['additionalVehicleStatus']['climateStatus']={'interiorTemp':25,'temperatureUpdateTime':BASE+31000}
        data=normalize(raw,BASE)
        self.assertIsNone(data['inside_temp']['value'])
        self.assertEqual(data['inside_temp']['validity'],'invalid')


class MetricTests(unittest.TestCase):
    def test_trip_formula_uses_unrounded_values_and_thresholds(self):
        start = {'state_time': BASE, 'observed_at': BASE, 'odometer': 100, 'soc': 78, 'speed': 10}
        end = {'state_time': BASE+2520000, 'observed_at': BASE+2520000, 'odometer': 123.6, 'soc': 72, 'speed': 76}
        result = trip_metrics(start, end, [start, end], {'battery_capacity_kwh': 86})
        self.assertAlmostEqual(result['estimated_kwh'], 5.16)
        self.assertAlmostEqual(result['estimated_kwh_100km'], 21.8644, places=3)

    def test_charge_average_is_time_weighted_and_coverage_gated(self):
        points = [{'state_time': BASE+t*1000, 'observed_at': BASE+t*1000, 'charging': True, 'power_kw': p}
                  for t, p in ((0, 20), (60, 40), (120, 80))]
        end = {'state_time': BASE+120000, 'observed_at': BASE+120000, 'soc': 60}
        result = charge_metrics(dict(points[0], soc=50), end, points, {'battery_capacity_kwh': 80})
        self.assertAlmostEqual(result['average_power_kw'], 45)
        self.assertEqual(historical_median([1, 2, 3, 4]), None)
        self.assertEqual(historical_median([1, 2, 3, 4, 5]), 3)

    def test_charge_time_coverage_does_not_count_last_active_to_stop(self):
        points = [{'state_time': BASE+t*1000, 'observed_at': BASE+t*1000,
                   'charging': active, 'charging_mode': 'dc', 'power_kw': 40 if active else None}
                  for t,active in ((0,True),(60,True),(120,True),(180,False))]
        result = charge_metrics(dict(points[0],soc=20), dict(points[-1],soc=50), points, {'battery_capacity_kwh':86})
        self.assertEqual(result['charging_time_covered_seconds'], 120)
        self.assertAlmostEqual(result['charging_time_coverage'], 2/3)

    def test_negative_or_zero_duration_never_divides_or_invents_speed(self):
        start={'state_time':BASE,'observed_at':BASE,'odometer':10,'soc':50}
        end={'state_time':BASE,'observed_at':BASE,'odometer':11,'soc':49}
        result=trip_metrics(start,end,[start,end],{'battery_capacity_kwh':86})
        self.assertIsNone(result['average_speed_kmh'])


class RenderTests(unittest.TestCase):
    def test_ac_start_and_end_use_calibrated_ac_power_without_dc_residual(self):
        from test_ac_charging import ac_sample
        start = normalize(ac_sample(chargeUAct=220, chargeIAct=16,
                                    dcChargePileUAct=360), BASE)
        end = normalize(ac_sample(60, chargeUAct=0, chargeIAct=0,
                                  chargerState=0, statusOfChargerConnection=0), BASE + 60000)
        report = {'start_time': BASE, 'end_time': BASE + 60000,
                  'start': start, 'end': end, 'partial': True, 'metrics': {}}
        text, _ = render('charge_start', report, 'synthetic-ac')
        self.assertIn('开始充电｜交流', text)
        self.assertIn('接口观测电压：220 V', text)
        self.assertIn('接口观测电流：16 A', text)
        self.assertNotIn('桩侧', text)
        self.assertNotIn('360 V', text)
        self.assertIn('交流观测功率：3.5 kW（电压×电流）', text)
        text, _ = render('charge_end', report, 'synthetic-ac')
        self.assertIn('类型：交流', text)
        self.assertNotIn('停止观测：', text)
        self.assertNotIn('桩侧', text)
        self.assertNotIn('停止原因：未确认', text)

    def test_whole_minutes_and_percentages_keep_trailing_zeroes(self):
        start = {'state_time': BASE, 'observed_at': BASE, 'soc': 50,
                 'remaining_minutes': 30}
        report = {'start_time': BASE, 'end_time': BASE + 600000,
                  'start': start, 'end': {'soc': 60}, 'partial': False,
                  'metrics': {'duration_seconds': 600, 'distance_km': 10,
                              'soc_delta': 10, 'power_covered_seconds': 480,
                              'power_coverage': .8, 'max_gap_seconds': 60},
                  'quality': {'observation_count': 10}}
        text, _ = render('charge_start', report, 'synthetic-id')
        self.assertIn('车辆估计剩余30分钟', text)
        text, _ = render('trip_end', report, 'synthetic-id')
        self.assertIn('10 公里 · 10 分钟', text)
        self.assertIn('最大间隔60秒', text)
        text, _ = render('charge_end', report, 'synthetic-id')
        self.assertNotIn('功率有效覆盖：', text)
        start['remaining_minutes'] = 0
        text, _ = render('charge_start', report, 'synthetic-id')
        self.assertIn('车辆估计剩余0分钟', text)

    def test_control_text_is_flat_and_message_is_bounded(self):
        self.assertEqual(clean_text('站点\n伪造标题\x00'), '站点 伪造标题')
        report = {'start_time': BASE, 'end_time': BASE+60000, 'start': {'soc': 10},
                  'end': {'soc': 20}, 'partial': True, 'metrics': {'duration_seconds': 60,
                  'soc_delta': 10, 'power_covered_seconds': 0, 'power_coverage': 0}}
        text, _ = render('charge_end', report, 'abcdef123456789', {'start': '很长地点'*100})
        self.assertLessEqual(len(text.encode()), 2048)
        self.assertIn('部分记录', text)
        self.assertIn('未确认', text)

    def test_full_report_degrades_by_utf8_bytes_without_cutting_negation(self):
        report={'kind':'trip_end','start_time':BASE,'end_time':BASE+60000,'partial':True,
          'start':{'soc':80},'end':{'soc':70,'tyres':[]},'parking':None,
          'metrics':{'distance_km':10,'duration_seconds':60,'soc_delta':-10,'estimated_kwh':8.6,
                     'estimated_kwh_100km':86,'average_speed_kmh':600,'sampled_max_speed_kmh':100,
                     'speed_samples':10},'quality':{'observation_count':2},
          'comparison':{'items':[{'metric':'minutes_per_km','note':'相近里程','n':20,'current':1,'median':2,'difference':-1,'event_ids':[]}]*8}}
        text,omitted=render('trip_end',report,'abcdef123456',{'start':'超长地址'*100,'end':'超长地址'*100},target=300)
        self.assertLessEqual(len(text.encode()),2048)
        self.assertIn('部分记录',text)
        self.assertNotIn('锁车、门窗及尾门',text)
        self.assertIn('缓存',text)
        self.assertTrue(omitted)


class HistoryTests(unittest.TestCase):
    def test_current_event_is_excluded_and_five_compatible_events_compare(self):
        db = sqlite3.connect(':memory:')
        db.execute('CREATE TABLE monitor_events(id TEXT,vehicle TEXT,kind TEXT,summary TEXT,created INTEGER)')
        db.execute('CREATE TABLE report_metric_index(event_id TEXT,vehicle TEXT,kind TEXT,end_time INTEGER,decoder_version TEXT,partial INTEGER,metrics TEXT)')
        for index in range(5):
            report = {'schema_version':2,'decoder_version':'we86-v1','kind':'trip_end','partial':False,
                      'start_time':BASE-index*100000,'end_time':BASE-index*100000+60000,
                      'quality':{},'metrics':{'distance_km':10,'duration_seconds':600,'average_speed_kmh':60}}
            db.execute('INSERT INTO monitor_events VALUES(?,?,?,?,?)', (str(index),'car','trip_end',json.dumps({'report_v2':report}),report['end_time']))
            db.execute('INSERT INTO report_metric_index VALUES(?,?,?,?,?,?,?)',(str(index),'car','trip_end',report['end_time'],'we86-v1',0,'{}'))
        current = {'schema_version':2,'decoder_version':'we86-v1','kind':'trip_end','partial':False,
                   'start_time':BASE+100000,'end_time':BASE+160000,'quality':{},
                   'metrics':{'distance_km':10,'duration_seconds':540,'average_speed_kmh':66}}
        result = compare(db,'car',current)
        self.assertTrue(result['available'])
        self.assertEqual(result['items'][0]['n'],5)
        self.assertEqual(result['items'][0]['median'],1)


class PreviewTests(unittest.TestCase):
    def test_fixture_preview_is_offline_and_reports_bytes(self):
        from zeekr_control.report_preview import preview
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'fixture.json'
            path.write_text(json.dumps({'kind':'charge_start','id':'abc123abc123',
                'report_v2':{'start_time':BASE,'start':{'soc':30},'metrics':{},'partial':True}}))
            result = preview(fixture_path=path,target_bytes=300)
            self.assertEqual(result['utf8_bytes'],len(result['text'].encode()))
            self.assertIn('开始时间未知',result['text'])


if __name__ == '__main__':
    unittest.main()
