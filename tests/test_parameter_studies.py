import json
import unittest
from zeekr_control.parameter_studies import evidence_profiles, study_for
PREFIX='additionalVehicleStatus.'
def point(minute,trip=False,charging=False,**values):
    return {'time':minute*60000+1790140000000,'states':{'trip':trip,'charging':charging,'parked':not(trip or charging)},'values':{k:json.dumps(v) for k,v in values.items()}}
class StudyTests(unittest.TestCase):
    def test_service_distance_matches_odometer_conservation(self):
        a=PREFIX+'maintenanceStatus.distanceToService';b=PREFIX+'maintenanceStatus.odometer'
        samples=[point(i,**{a:100-i,b:1000+i}) for i in range(5)]
        e=evidence_profiles(samples)
        self.assertEqual(e['distanceToService']['spread'],0)
        self.assertEqual(e['distanceToService']['anchor_span'],4)
    def test_pack_current_sign_is_opposite_pile_charging_current(self):
        a=PREFIX+'electricVehicleStatus.dcChargeIAct';b=PREFIX+'electricVehicleStatus.dcChargePileIAct'
        e=evidence_profiles([point(1,charging=True,**{a:-100,b:103}),point(2,trip=True,**{a:150,b:0})])
        self.assertEqual(e['dcChargeIAct']['charge_negative'],1)
        self.assertEqual(e['dcChargeIAct']['trip_positive'],1)
    def test_humidity_over_100_is_not_silently_converted(self):
        p=PREFIX+'pollutionStatus.relHumSts';e=evidence_profiles([point(1,**{p:155})])
        self.assertEqual(e['relHumSts']['over_100'],1)
        row={'path':p,'status':'varied','kind':'number','name':'湿度','pending':True}
        s=study_for(row,e)
        self.assertIn('未标定',s['definition'])
    def test_constant_heating_setting_not_claimed_as_running(self):
        p=PREFIX+'climateStatus.drvHeatDetail';state=PREFIX+'climateStatus.drvHeatSts'
        e=evidence_profiles([point(i,**{p:'2',state:'0'}) for i in range(3)])
        s=study_for({'path':p,'status':'single_value','kind':'enum','name':'加热','pending':True},e)
        self.assertIn('设定',s['definition'])
        self.assertEqual(s['stage'],'constant_only')
    def test_missing_and_generic_fields_never_marked_cross_checked(self):
        for status in ['missing','single_value','varied']:
            s=study_for({'path':'basicVehicleStatus.carMode','status':status,'kind':'enum','name':'模式','pending':True},{})
            self.assertNotEqual(s['stage'],'cross_checked')

    def test_heading_zero_point_compares_with_motion_and_exports_no_coordinates(self):
        from zeekr_control.parameter_studies import heading_profile
        a=point(1,trip=True,**{'basicVehicleStatus.direction':90})
        b=point(2,trip=True,**{'basicVehicleStatus.direction':90})
        a.update(_trusted=True,_position=(30,120,'WGS84'))
        b.update(_trusted=True,_position=(30,120.001,'WGS84'))
        result=heading_profile([a,b])
        self.assertEqual(result['paired_motion'],1)
        self.assertLess(result['median_angle_error'],.1)
        self.assertEqual(result['best_offset'],0)
        self.assertNotIn('latitude',json.dumps(result))

    def test_new_variation_falsifies_old_no_option_assumption(self):
        row={'path':'additionalVehicleStatus.climateStatus.steerWhlHeatingSts','status':'varied','kind':'enum','name':'方向盘加热','pending':True}
        self.assertIn('冲突',study_for(row,{})['definition'])
