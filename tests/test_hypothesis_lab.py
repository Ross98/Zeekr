import unittest
from zeekr_control.hypothesis_lab import prepare, investigate
P='additionalVehicleStatus.drivingBehaviourStatus.gearAutoStatus'
Q='additionalVehicleStatus.drivingSafetyStatus.electricParkBrakeStatus'
class HypothesisTests(unittest.TestCase):
    def sample(self,t,gear,brake='0',flags=()):
        return ({'state_time':t*60000,'observed_at':t*60000,'flags':flags},
                {'additionalVehicleStatus':{'drivingBehaviourStatus':{'gearAutoStatus':gear},
                 'drivingSafetyStatus':{'electricParkBrakeStatus':brake}}})
    def test_scans_whole_catalog_and_finds_both_directions_of_counterevidence(self):
        data=prepare(iter([self.sample(1,'0'),self.sample(2,'3'),self.sample(3,'3','1'),self.sample(4,'0','1')]),
                     [{'start_time':120000,'end_time':240000}],[])
        result=investigate(data,'trip')
        row=next(r for r in result['candidates'] if r['path']==Q)
        self.assertEqual(row['transitions']['state_only'],2)
        self.assertEqual(row['transitions']['field_only'],1)
        self.assertGreater(len(data['fields']),100)
    def test_same_time_revision_is_one_sample(self):
        data=prepare(iter([self.sample(1,'0'),self.sample(1,'3'),self.sample(2,'1',flags=['stale'])]),[],[])
        self.assertEqual(len(data['samples']),1)
        self.assertEqual(data['samples'][0]['values'][P],'"3"')
    def test_no_gap_is_used_as_transition_proof(self):
        data=prepare(iter([self.sample(1,'0'),self.sample(50,'3')]),[{'start_time':200000,'end_time':4000000}],[])
        row=next(r for r in investigate(data,'trip')['candidates'] if r['path']==P)
        self.assertEqual(row['transitions']['both'],0)
        self.assertEqual(row['transitions']['gaps'],1)
    def test_custom_anchor_does_not_rank_itself(self):
        data=prepare(iter([self.sample(1,'0'),self.sample(2,'3')]),[],[])
        result=investigate(data,'anchor',anchor=P,value='"3"')
        self.assertFalse(any(r['path']==P for r in result['candidates']))
    def test_single_value_and_missing_fields_stay_visible_without_meaning(self):
        data=prepare(iter([self.sample(1,'0'),self.sample(2,'0')]),[],[])
        row=next(r for r in investigate(data,'trip')['candidates'] if r['path']==P)
        self.assertEqual(row['distinct'],1)
        self.assertEqual(row['status'],'single_value')
        self.assertNotIn('meaning',row)

class ProposalTests(unittest.TestCase):
    def test_bold_mapping_is_labelled_hypothesis_and_keeps_counterevidence(self):
        from zeekr_control.hypothesis_lab import propose
        row={'path':Q,'name':'电子驻车','kind':'enum','distinct':2,'status':'varied','inside':{'"1"':8},'outside':{'"0"':9,'"1"':2},'unknown':{},'transitions':{'both':2,'state_only':1,'field_only':3}}
        result=propose(row)
        self.assertEqual(result['source'],'自动假设，未确认')
        self.assertIn('1=驻车制动生效',result['meaning'])
        self.assertIn('反例',result['next'])
    def test_constant_zero_is_not_automatically_off(self):
        from zeekr_control.hypothesis_lab import propose
        row={'path':'x','name':'某开关','kind':'enum','distinct':1,'status':'single_value','inside':{'"0"':10},'outside':{},'unknown':{},'transitions':{}}
        self.assertIn('缺省',propose(row)['meaning'])
