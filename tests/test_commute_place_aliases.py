import copy
import unittest
from tests import test_commute_tags as fixtures

class CommutePlaceAliasesTests(unittest.TestCase):
    setUp=fixtures.CommuteTagTests.setUp
    save_rule=fixtures.CommuteTagTests.save_rule

    def apply(self,rule=None):
        places=[dict(id='inside',label='参考地点 1',latitude=31.2,longitude=121.4),
                dict(id='outside',label='参考地点 2',latitude=31.2006,longitude=121.4),
                dict(id='other',label='参考地点 3',latitude=32.2,longitude=122.4)]
        return self.tags.place_names.apply('owner','car',dict(places=places),rule or self.tags.commute.rule('owner','car'))

    def test_named_home_and_home_fallback_share_statistics_identity_without_moving_rule(self):
        self.save_rule();before=self.tags.commute.rule('owner','car')
        self.tags.store.change('owner','car','place_names','save','home-name',dict(name='合成家园',latitude=31.2,longitude=121.4,radius_m=25),0)
        self.tags.store.change('owner','car','place_names','save','unrelated-name',dict(name='合成家园',latitude=32.2,longitude=122.4,radius_m=25),1)
        original=self.tags.store.path.read_bytes();result=self.apply();a,b,c=result['places']
        self.assertEqual([a['label'],b['label']],['合成家园','合成家园'])
        self.assertEqual(a['statistics_key'],b['statistics_key'])
        self.assertEqual([a['commute_alias'],b['commute_alias']],['家','家'])
        self.assertNotEqual(a['statistics_key'],c['statistics_key'])
        self.assertEqual(b['name_source'],'commute');self.assertIsNone(b.get('name_region_id'))
        self.assertEqual(result['commute_place_names']['home'],'合成家园')
        self.assertEqual(self.tags.commute.rule('owner','car'),before)
        self.assertEqual(self.tags.store.path.read_bytes(),original)

    def test_manual_other_name_and_deleted_rule_are_not_overridden(self):
        self.save_rule()
        self.tags.store.change('owner','car','place_names','save','home-name',dict(name='合成家园',latitude=31.2,longitude=121.4,radius_m=25),0)
        self.tags.store.change('owner','car','place_names','save','shop',dict(name='合成商店',latitude=31.2006,longitude=121.4,radius_m=25),1)
        self.assertEqual(self.apply()['places'][1]['label'],'合成商店')
        self.assertNotIn('commute_alias',self.apply()['places'][1])
        rule=copy.deepcopy(self.tags.commute.rule('owner','car'));rule['deleted']=True
        result=self.apply(rule)
        self.assertEqual(result['commute_place_names'],{})
        self.assertTrue(all('commute_alias' not in p for p in result['places']))

    def test_other_owner_does_not_inherit_home_name(self):
        self.save_rule();self.tags.store.change('other','car','place_names','save','foreign',dict(name='其他账号地点',latitude=31.2,longitude=121.4,radius_m=150),0)
        result=self.apply()
        self.assertEqual(result['places'][0]['label'],'家')
        self.assertEqual(result['commute_place_names'],{})

if __name__=='__main__':unittest.main()
