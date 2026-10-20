import json
import sqlite3
import unittest
from unittest.mock import Mock

from zeekr_control.charging_review import ChargingReview
from zeekr_control.personal_store import PersonalStore
from zeekr_control.tracks import day_bounds
import test_usage_reports as fixtures


class ChargingPlaceTests(unittest.TestCase):
    setUp=fixtures.UsageReportsTests.setUp
    add=fixtures.UsageReportsTests.add

    def charge(self, identity='charge', day='2026-09-15', **changes):
        start=day_bounds(day)[0]+8*3600000
        self.add(identity,kind='charge_end',start_time=start,end_time=start+3600000,
                 start_soc=20,end_soc=80,soc_delta=60,**changes)
        return start

    def observe(self, stamp, lat=31.2, lon=121.4, vehicle='car', delay=1000, trusted=True):
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY,vehicle TEXT,cache_key TEXT,state_time INTEGER,observed_time INTEGER,gap_seconds INTEGER,location TEXT)')
            db.execute('INSERT INTO observations(vehicle,cache_key,state_time,observed_time,gap_seconds,location) VALUES (?,?,?,?,?,?)',
                       (vehicle,str(stamp),stamp,stamp+delay,1,json.dumps(dict(valid=True,trusted=trusted,plottable=True,coordinate_system='WGS84（社区解释）',latitude=lat,longitude=lon))))

    def review(self):
        return ChargingReview(self.db,PersonalStore(self.root/'personal.sqlite3'))

    def detail(self, identity='charge'):
        return self.review().places.detail('owner','car',identity)

    def proposal(self, scope='single', **extra):
        return dict(event_id='charge',revision=0,scope=scope,name='测试广场',station_name='',latitude=31.2,longitude=121.4,radius_m=75,**extra)

    def test_whole_session_majority_rejects_first_point_drift(self):
        start=self.charge()
        self.observe(start,32,122)
        for minute in (5,10,15,20,25):self.observe(start+minute*60000,31.2+minute/10000000,121.4)
        detail=self.detail();self.assertAlmostEqual(detail['location']['latitude'],31.2,places=4)
        self.assertEqual(detail['evidence']['source'],'charge_samples')
        self.assertEqual(detail['evidence']['outlier_count'],1)
        self.assertEqual(detail['evidence']['sample_count'],6)
        row=self.review().query('owner','car','2026-09-01',now=self.now)['records'][0]
        self.assertEqual(row['place_source'],'unknown')
        self.assertNotIn('latitude',json.dumps(row))

    def test_conflicting_clusters_stale_and_other_vehicle_never_become_confirmed(self):
        start=self.charge()
        for minute in (0,5):self.observe(start+minute*60000)
        for minute in (10,15):self.observe(start+minute*60000,32,122)
        self.observe(start+20*60000,31.2,121.4,vehicle='other')
        self.assertIsNone(self.detail()['location']);self.assertEqual(self.detail()['evidence']['source'],'conflict')
        with sqlite3.connect(self.db) as db:db.execute('DELETE FROM observations')
        self.observe(start,delay=3600000);self.observe(start+60000,trusted=False)
        self.assertIsNone(self.detail()['location'])

    def test_single_point_retains_reference_provenance(self):
        start=self.charge();self.observe(start)
        d=self.detail();self.assertEqual(d['evidence']['source'],'single_sample');self.assertTrue(d['reference'])

    def test_missing_gps_requires_continuous_stationary_telemetry(self):
        start=self.charge();end=start+3600000
        loc=dict(valid=True,trusted=True,plottable=True,coordinate_system='WGS84（社区解释）',latitude=31.2,longitude=121.4)
        self.add('arrival',start_time=start-600000,end_time=start-60000,end_location=loc)
        self.add('departure',start_time=end+60000,end_time=end+600000,start_location=loc)
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE report_observations(vehicle TEXT,state_time INTEGER,observed_at INTEGER,normalized_payload TEXT,decoder_version TEXT)')
            for stamp in range(start-60000,end+60001,60000):
                payload=dict(state_time=stamp,observed_at=stamp+1000,speed=0,odometer=1200,gear='P',charging=start<=stamp<=end)
                db.execute('INSERT INTO report_observations VALUES(?,?,?,?,?)',('car',stamp,stamp+1000,json.dumps(payload),'v1'))
        self.assertEqual(self.detail()['evidence']['source'],'stationary_between_trips')
        with sqlite3.connect(self.db) as db:db.execute('DELETE FROM report_observations WHERE state_time=?',(start+60000,));db.execute('DELETE FROM report_observations WHERE state_time=?',(start+120000,));db.execute('DELETE FROM report_observations WHERE state_time=?',(start+180000,))
        self.assertIsNone(self.detail()['location'])

    def test_saved_precharge_reference_requires_stationary_evidence_and_stays_reference(self):
        start=day_bounds('2026-09-15')[0]+8*3600000;end=start+3600000
        location=dict(valid=True,trusted=True,plottable=True,coordinate_system='WGS84（社区解释）',latitude=31.2,longitude=121.4)
        ref=dict(state_time=start-120000,observed_time=start-119000,age_seconds=120,location=location)
        report=dict(start=dict(state_time=start,observed_at=start+1000,odometer=1200,off=True,charging=True),end=dict(state_time=end,observed_at=end+1000,odometer=1200,off=True,charging=False))
        self.charge(start_location_reference=ref,start_location=dict(location,trusted=False),end_location=dict(location,trusted=False),report_v2=report)
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE report_observations(vehicle TEXT,state_time INTEGER,observed_at INTEGER,normalized_payload TEXT,decoder_version TEXT)')
            for stamp in range(start,end+1,60000):
                payload=dict(state_time=stamp,observed_at=stamp+1000,odometer=1200,off=True,charging=stamp<end,speed=0)
                db.execute('INSERT INTO report_observations VALUES(?,?,?,?,?)',('car',stamp,stamp+1000,json.dumps(payload),'v1'))
        detail=self.detail();self.assertIsNotNone(detail['location']);self.assertTrue(detail['reference'])
        self.assertEqual(detail['evidence']['source'],'saved_precharge_reference')
        self.assertEqual(detail['evidence']['reference_age_seconds'],120)
        with sqlite3.connect(self.db) as db:
            raw=json.loads(db.execute('SELECT normalized_payload FROM report_observations WHERE state_time=?',(start+60000,)).fetchone()[0]);raw['odometer']=1201
            db.execute('UPDATE report_observations SET normalized_payload=? WHERE state_time=?',(json.dumps(raw),start+60000))
        self.assertIsNone(self.detail()['location'])

    def test_disagreeing_saved_reference_is_only_an_explicit_correction_candidate(self):
        start=day_bounds('2026-09-15')[0]+8*3600000
        loc=dict(valid=True,trusted=True,plottable=True,coordinate_system='WGS84（社区解释）',latitude=31.2,longitude=121.4)
        ref=dict(location=loc,state_time=start-120000,observed_time=start-119000,age_seconds=120)
        self.charge(start_location_reference=ref,start_location=dict(loc,latitude=31.202,trusted=False))
        d=self.detail();self.assertIsNone(d['location'])
        self.assertEqual(d['reference_candidate']['location']['latitude'],31.2)
        self.assertEqual(d['reference_candidate']['age_seconds'],120)
        self.assertGreater(d['reference_candidate']['boundary_distance_m'],75)
        row=self.review().query('owner','car','2026-09-01',now=self.now)['records'][0]
        self.assertTrue(row['place_unlocated']);self.assertNotIn('latitude',json.dumps(row))

    def test_preview_is_readonly_save_requires_exact_proposal_and_revision(self):
        start=self.charge();self.observe(start);places=self.review().places;p=self.proposal()
        plan=places.preview('owner','car',p);self.assertEqual(plan['affected_count'],1)
        self.assertEqual(places.store.read('owner','car','charging_places')['revision'],0)
        with self.assertRaises(ValueError):places.update('owner','car',dict(p,action='save',token=plan['token'],name='换名'))
        saved=places.update('owner','car',dict(p,action='save',token=plan['token']))
        self.assertEqual(saved['revision'],1)
        self.assertEqual(places.detail('owner','car','charge')['name'],'测试广场')
        with self.assertRaises(ValueError):places.update('owner','car',dict(p,action='save',token=plan['token']))
        self.assertEqual(places.detail('other','car','charge')['name'],'地点未知')
        places.update('owner','car',dict(action='undo',revision=1))
        self.assertEqual(places.detail('owner','car','charge')['name'],'地点未知')

    def test_region_scope_matches_history_and_future_not_distant_same_name(self):
        for identity,day,lat in [('old','2026-08-15',31.2),('charge','2026-09-15',31.2001),('far','2026-09-16',32.2),('future','2026-10-15',31.2)]:
            start=self.charge(identity,day);self.observe(start,lat)
        places=self.review().places;p=self.proposal('place');plan=places.preview('owner','car',p)
        self.assertEqual({r['id'] for r in plan['affected']},{'old','charge','future'})
        places.update('owner','car',dict(p,action='save',token=plan['token']))
        self.assertEqual(places.detail('owner','car','old')['name'],'测试广场')
        self.assertEqual(places.detail('owner','car','far')['name'],'地点未知')
        self.assertEqual(places.detail('owner','car','future')['name'],'测试广场')
        # Matching stays at the observed anchor, even if the corrected marker moves.
        self.assertEqual(places.detail('owner','car','old')['location']['latitude'],31.2)

    def test_invalid_points_hidden_events_and_preview_after_event_change_rejected(self):
        start=self.charge();self.observe(start);places=self.review().places;p=self.proposal()
        for bad in (dict(latitude=True),dict(longitude=float('nan')),dict(name='\n'),dict(radius_m=5000)):
            with self.assertRaises(ValueError):places.preview('owner','car',dict(p,**bad))
        plan=places.preview('owner','car',p)
        self.observe(start+60000,32,122)
        with self.assertRaises(ValueError):places.update('owner','car',dict(p,action='save',token=plan['token']))
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE charge_record_trash(vehicle TEXT,event_id TEXT)');db.execute('INSERT INTO charge_record_trash VALUES(?,?)',('car','charge'))
        with self.assertRaises(ValueError):places.detail('owner','car','charge')

    def test_region_edits_reuse_original_anchor_and_keep_saved_radius(self):
        start=self.charge();self.observe(start)
        old=self.charge('neighbor','2026-08-15');self.observe(old,31.2009)
        places=self.review().places;p=dict(self.proposal('place'),radius_m=150,latitude=31.21)
        plan=places.preview('owner','car',p);places.update('owner','car',dict(p,action='save',token=plan['token']))
        d=places.detail('owner','car','neighbor');self.assertEqual(d['radius_m'],150)
        edit=dict(p,event_id='neighbor',revision=1,name='新名称')
        plan=places.preview('owner','car',edit);self.assertEqual(plan['affected_count'],2)
        places.update('owner','car',dict(edit,action='save',token=plan['token']))
        records=places.store.read('owner','car','charging_places')['records']
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['body']['anchor'],[31.2,121.4])

    def test_expanding_single_to_same_place_converts_selected_override_only(self):
        for identity,day in [('charge','2026-09-15'),('neighbor','2026-09-16'),('protected','2026-09-17')]:
            start=self.charge(identity,day);self.observe(start)
        places=self.review().places
        for revision,identity in enumerate(('charge','protected')):
            p=dict(self.proposal(),event_id=identity,revision=revision,name=identity)
            plan=places.preview('owner','car',p);places.update('owner','car',dict(p,action='save',token=plan['token']))
        p=dict(self.proposal('place'),revision=2,name='共享地点')
        plan=places.preview('owner','car',p)
        self.assertEqual({r['id'] for r in plan['affected']},{'charge','neighbor'})
        places.update('owner','car',dict(p,action='save',token=plan['token']))
        self.assertEqual(places.detail('owner','car','charge')['name'],'共享地点')
        self.assertEqual(places.detail('owner','car','protected')['name'],'protected')
        places.update('owner','car',dict(action='undo',revision=3))
        self.assertEqual(places.detail('owner','car','charge')['name'],'charge')

    def test_shrinking_region_preview_includes_records_losing_the_rule(self):
        start=self.charge();self.observe(start)
        near=self.charge('edge','2026-09-16');self.observe(near,31.2009)
        places=self.review().places;p=dict(self.proposal('place'),radius_m=150)
        plan=places.preview('owner','car',p);places.update('owner','car',dict(p,action='save',token=plan['token']))
        p=dict(p,revision=1,radius_m=25)
        plan=places.preview('owner','car',p)
        self.assertEqual({r['id'] for r in plan['affected']},{'charge','edge'})
        self.assertEqual(next(r for r in plan['affected'] if r['id']=='edge')['effect'],'outside_new_range')
        places.update('owner','car',dict(p,action='save',token=plan['token']))
        self.assertEqual(places.detail('owner','car','edge')['name'],'地点未知')

    def test_stationary_fallback_rejects_invalid_speed(self):
        # The same fixture proves continuity; malformed speed must not count as zero.
        start=self.charge();end=start+3600000
        loc=dict(valid=True,trusted=True,plottable=True,coordinate_system='WGS84（社区解释）',latitude=31.2,longitude=121.4)
        self.add('arrival',start_time=start-600000,end_time=start-60000,end_location=loc)
        self.add('departure',start_time=end+60000,end_time=end+600000,start_location=loc)
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE report_observations(vehicle TEXT,state_time INTEGER,observed_at INTEGER,normalized_payload TEXT,decoder_version TEXT)')
            for stamp in range(start-60000,end+60001,60000):
                payload=dict(state_time=stamp,observed_at=stamp+1000,speed='unknown' if stamp==start else 0,odometer=1200,gear='P')
                db.execute('INSERT INTO report_observations VALUES(?,?,?,?,?)',('car',stamp,stamp+1000,json.dumps(payload),'v1'))
        self.assertIsNone(self.detail()['location'])

    def test_candidate_lookup_does_not_confirm_station_and_provider_failure_is_safe(self):
        start=self.charge();self.observe(start);places=self.review().places
        provider=Mock();provider.charging_candidates.return_value=[dict(id='station-1',name='测试充电站',distance_m=20)]
        result=places.candidates('owner','car','charge',provider)
        self.assertEqual(result['candidates'][0]['name'],'测试充电站')
        self.assertIsNone(places.detail('owner','car','charge')['station_name'])
        provider.charging_candidates.side_effect=RuntimeError('SECRET')
        self.assertEqual(places.candidates('owner','car','charge',provider)['status'],'unavailable')

    def test_price_is_weighted_on_the_same_paired_bills_and_names_never_merge_distant_sites(self):
        for identity,day,lat in [('charge','2026-09-15',31.2),('second','2026-09-16',31.2),('far','2026-09-17',32.2)]:
            start=self.charge(identity,day);self.observe(start,lat)
        places=self.review().places
        p=self.proposal('place');plan=places.preview('owner','car',p);places.update('owner','car',dict(p,action='save',token=plan['token']))
        p=dict(p,event_id='far',revision=1,latitude=32.2);plan=places.preview('owner','car',p);places.update('owner','car',dict(p,action='save',token=plan['token']))
        from zeekr_control.charge_ledger import ChargeLedger
        for revision,(identity,amount,meter) in enumerate([('charge','20','10'),('second','30','60'),('far','10',None)]):
            ChargeLedger(places.store,self.db).update('owner','car',dict(action='save',revision=revision,event_id=identity,date='2026-09-15',source='unknown',amount=amount,metered_kwh=meter))
        groups=self.review().query('owner','car','2026-09-01',now=self.now)['place_summary']
        self.assertEqual(len(groups),2);paired=next(g for g in groups if g['paired_count']==2)
        self.assertAlmostEqual(paired['cents_per_kwh'],5000/70)
        self.assertEqual(paired['actual_cents'],5000)
        self.assertIsNone(next(g for g in groups if g['paired_count']==0)['cents_per_kwh'])

    def test_confirmation_is_bound_to_owner_expiry_and_storage_guard(self):
        start=self.charge();self.observe(start);places=self.review().places;p=self.proposal()
        from unittest.mock import patch
        with patch('zeekr_control.charging_places.time.time',return_value=1000):plan=places.preview('owner','car',p)
        with patch('zeekr_control.charging_places.time.time',return_value=1500):
            with self.assertRaises(ValueError):places.update('owner','car',dict(p,action='save',token=plan['token']))
        plan=places.preview('owner','car',p)
        with self.assertRaises(ValueError):places.update('other','car',dict(p,action='save',token=plan['token']))
        def guard():raise ValueError('account changed')
        with self.assertRaises(ValueError):places.update('owner','car',dict(p,action='save',token=plan['token']),guard=guard)
        self.assertEqual(places.store.read('owner','car','charging_places')['revision'],0)

    def test_month_place_stats_preserve_unknowns_weighted_prices_and_ac_dc(self):
        start=self.charge();self.observe(start);places=self.review().places;p=self.proposal()
        plan=places.preview('owner','car',p);places.update('owner','car',dict(p,action='save',token=plan['token']))
        self.charge('unknown','2026-09-16')
        from zeekr_control.charge_ledger import ChargeLedger
        ChargeLedger(places.store,self.db).update('owner','car',dict(action='save',revision=0,event_id='charge',date='2026-09-15',source='unknown',amount='0',metered_kwh='40',charge_mode_override='dc'))
        result=self.review().query('owner','car','2026-09-01',now=self.now)
        groups=result['place_summary'];known=next(g for g in groups if g['name']=='测试广场')
        unknown=next(g for g in groups if g['unlocated'])
        self.assertEqual(known['charge_count'],1);self.assertEqual(known['actual_cents'],0)
        self.assertEqual(known['cents_per_kwh'],0);self.assertEqual(known['modes']['dc'],1)
        self.assertIsNone(unknown['actual_cents']);self.assertIsNone(unknown['cents_per_kwh'])



    def named_sites(self):
        from zeekr_control.charge_ledger import ChargeLedger
        places=self.review().places
        for revision,(identity,lat) in enumerate([('region-a',31.2),('region-b',32.2)]):
            places.store.change('owner','car','place_names','save',identity,dict(name=identity,latitude=lat,longitude=121.4,radius_m=150,shape='circle'),revision)
        for revision,(identity,day,lat,amount) in enumerate([('charge','2026-09-15',31.2,'10'),('destination','2026-09-16',32.2,'20'),('stays','2026-09-17',31.2,'30')]):
            stamp=self.charge(identity,day);self.observe(stamp,lat)
            ChargeLedger(places.store,self.db).update('owner','car',dict(action='save',revision=revision,event_id=identity,date=day,source='unknown',amount=amount,metered_kwh='40'))
        return places

    def month_groups(self):
        result=self.review().query('owner','car','2026-09-01',now=self.now)
        self.assertEqual(result['summary']['actual_cents'],6000)
        self.assertEqual(sum(g['actual_cents'] or 0 for g in result['place_summary']),6000)
        return result

    def test_single_location_move_reassigns_costs_to_destination_region_and_undo_restores(self):
        places=self.named_sites();before=self.month_groups();keys={r['id']:r['place_key'] for r in before['records']}
        proposal=dict(self.proposal(),name='修正后的地点',latitude=32.2)
        plan=places.preview('owner','car',proposal);places.update('owner','car',dict(proposal,action='save',token=plan['token']))
        after=self.month_groups();rows={r['id']:r for r in after['records']};groups={g['key']:g for g in after['place_summary']}
        self.assertEqual(places.detail('owner','car','charge')['location']['latitude'],32.2)
        self.assertEqual(rows['charge']['place_key'],keys['destination'])
        self.assertEqual(groups[keys['destination']]['charge_count'],2);self.assertEqual(groups[keys['destination']]['actual_cents'],3000)
        self.assertEqual(groups[keys['charge']]['charge_count'],1);self.assertEqual(groups[keys['charge']]['actual_cents'],3000)
        places.update('owner','car',dict(action='undo',revision=1))
        restored=self.month_groups();self.assertEqual(restored['place_summary'],before['place_summary'])

    def test_cleared_location_moves_to_unknown_group_and_undo_restores(self):
        places=self.named_sites();before=self.month_groups();keys={r['id']:r['place_key'] for r in before['records']}
        proposal=dict(self.proposal(),latitude=None,longitude=None)
        plan=places.preview('owner','car',proposal);places.update('owner','car',dict(proposal,action='save',token=plan['token']))
        after=self.month_groups();row=next(r for r in after['records'] if r['id']=='charge')
        self.assertIsNone(places.detail('owner','car','charge')['location'])
        unknown=next(g for g in after['place_summary'] if g['unlocated'])
        self.assertEqual(row['place_key'],unknown['key']);self.assertNotEqual(row['place_key'],keys['charge'])
        self.assertEqual(unknown['charge_count'],1);self.assertEqual(unknown['actual_cents'],1000)
        places.update('owner','car',dict(action='undo',revision=1))
        self.assertEqual(self.month_groups()['place_summary'],before['place_summary'])

    def test_clearing_whole_site_does_not_leave_region_rule_as_a_location_group(self):
        places=self.named_sites();self.charge('prior-unknown','2026-09-19')
        proposal=dict(self.proposal('place'),latitude=None,longitude=None)
        plan=places.preview('owner','car',proposal);places.update('owner','car',dict(proposal,action='save',token=plan['token']))
        after=self.month_groups();unknown=next(g for g in after['place_summary'] if g['unlocated'])
        self.assertEqual(unknown['charge_count'],3);self.assertEqual(unknown['actual_cents'],4000)
        self.assertEqual(sum(g['unlocated'] for g in after['place_summary']),1)
        for row in after['records']:
            if row['id']!='destination':self.assertEqual(row['place_key'],unknown['key'])

    def test_whole_site_move_merges_with_effective_destination_region(self):
        places=self.named_sites();before=self.month_groups();destination=next(r['place_key'] for r in before['records'] if r['id']=='destination')
        proposal=dict(self.proposal('place'),latitude=32.2)
        plan=places.preview('owner','car',proposal);places.update('owner','car',dict(proposal,action='save',token=plan['token']))
        groups=self.month_groups()['place_summary']
        self.assertEqual(len(groups),1);self.assertEqual(groups[0]['key'],destination)
        self.assertEqual(groups[0]['charge_count'],3);self.assertEqual(groups[0]['actual_cents'],6000)


if __name__=='__main__':unittest.main()
