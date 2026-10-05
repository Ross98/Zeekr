from copy import deepcopy
import unittest

from zeekr_control.tracks import day_bounds
from zeekr_control.parking_analytics import analyze_parking


class ParkingAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.start, self.end = day_bounds('2026-09-20')

    def point(self, minute, soc=70, off=True, speed=0, charging=False, km=1000, flags=(), change='new'):
        stamp = self.start + minute * 60000
        return {'record': {'key': '202609.%d' % (minute + 100), 'state_time': stamp,
                          'observed_at': stamp, 'fetched_at': stamp, 'flags': list(flags),
                          'change': change, 'gap_seconds': None},
                'state': {'time': stamp, 'off': off, 'speed': speed, 'charging': charging,
                          'soc': soc, 'km': km}, 'inside_temp': 25}

    def result(self, points, capacity=86):
        return analyze_parking(points, self.start, self.end, capacity)

    def complete(self):
        return [self.point(0, off=False, speed=30), self.point(5, soc=70),
                self.point(10, soc=69), self.point(15, soc=68), self.point(20, off=False, speed=30, soc=67)]

    def test_observed_endpoints_exclude_next_driving_soc(self):
        result = self.result(self.complete())
        row = result['sessions'][0]
        self.assertEqual((row['start_soc'], row['end_soc']), (70, 68))
        self.assertEqual(row['duration_seconds'], 600)
        self.assertEqual(row['soc_drop'], 2)
        self.assertAlmostEqual(row['estimated_kwh'], 1.72)
        self.assertTrue(row['eligible'])
        self.assertEqual(result['eligible_count'], 1)

    def test_first_and_last_observations_are_clipped_not_complete(self):
        row = self.result(self.complete()[1:4])['sessions'][0]
        self.assertFalse(row['eligible'])
        self.assertIn('start_unobserved', row['reasons'])
        self.assertIn('end_unobserved', row['reasons'])
        self.assertIsNone(row['estimated_kwh'])
        self.assertEqual(row['soc_drop'], 2)

    def test_charging_never_joins_two_parked_intervals(self):
        points = self.complete()
        points[2] = self.point(10, charging=True, soc=75)
        result = self.result(points)
        self.assertEqual(result['eligible_count'], 0)
        for row in result['sessions']:
            self.assertIsNone(row['estimated_kwh'])
        self.assertTrue(any('charging_boundary' in row['reasons'] for row in result['sessions']))

    def test_gap_and_stale_caches_exclude_ranking(self):
        points = [self.point(0, off=False, speed=10), self.point(5), self.point(30, soc=69),
                  self.point(35, soc=68, flags=['stale']), self.point(40, off=False, speed=30)]
        result = self.result(points)
        self.assertEqual(result['eligible_count'], 0)
        self.assertTrue(all(row['reasons'] for row in result['sessions']))
        self.assertGreater(result['quality']['excluded_reads'], 0)

    def test_advancing_time_with_identical_values_is_continuous_parking(self):
        points = [self.point(0, off=False, speed=30)]
        points += [self.point(minute, change='repeat' if minute > 5 else 'new')
                   for minute in range(5, 66, 5)]
        points += [self.point(70, off=False, speed=30)]
        result = self.result(points)
        row = result['sessions'][0]
        self.assertEqual(row['sample_count'], 13)
        self.assertEqual(row['duration_seconds'], 3600)
        self.assertNotIn('gap', row['reasons'])
        self.assertEqual(result['quality']['repeat_reads'], 0)
        self.assertEqual(row['soc_drop'], 0)
        self.assertTrue(row['eligible'])

    def test_repeats_do_not_add_samples_or_extend_vehicle_duration(self):
        points = self.complete()
        repeat = deepcopy(points[1]);repeat['record']['observed_at'] += 60000
        repeat['record']['change'] = 'repeat'
        points.insert(2, repeat)
        row = self.result(points)['sessions'][0]
        self.assertEqual(row['sample_count'], 3)
        self.assertEqual(row['duration_seconds'], 600)

    def test_revision_replaces_value_without_double_counting(self):
        points = self.complete()
        revision = deepcopy(points[2]);revision['state']['soc'] = 68.5
        revision['record']['change'] = 'revision';revision['record']['key'] = '202609.500'
        points.insert(3, revision)
        row = self.result(points)['sessions'][0]
        self.assertEqual(row['sample_count'], 3)
        self.assertTrue(row['eligible'])

    def test_soc_rise_or_missing_value_prevents_consumption_estimate(self):
        for middle in (71, None):
            points = self.complete();points[2]['state']['soc'] = middle
            row = self.result(points)['sessions'][0]
            self.assertFalse(row['eligible'])
            self.assertIsNone(row['estimated_kwh'])

    def test_odometer_change_or_unknown_charging_breaks_stationarity(self):
        for field, value in [('km',1001),('charging',None),('off',None),('speed',5)]:
            points = self.complete();points[2]['state'][field]=value
            result = self.result(points)
            self.assertEqual(result['eligible_count'], 0, field)

    def test_missing_speed_requires_unchanged_odometer_and_off_evidence(self):
        points = self.complete()
        for point in points[1:4]:
            point['state']['speed'] = None
        row = self.result(points)['sessions'][0]
        self.assertTrue(row['eligible'])
        points = self.complete()
        for point in points[1:4]:
            point['state']['speed'] = None;point['state']['km'] = None
        self.assertEqual(self.result(points)['sessions'], [])

    def test_no_capacity_still_reports_soc_not_kwh(self):
        for capacity in (None, 0, True, float('nan')):
            row = self.result(self.complete(), capacity)['sessions'][0]
            self.assertEqual(row['soc_drop'], 2)
            self.assertIsNone(row['estimated_kwh'])

    def test_zero_soc_change_is_valid_but_not_proof_of_zero_drain(self):
        points = self.complete()
        for point in points:point['state']['soc']=70
        row = self.result(points)['sessions'][0]
        self.assertTrue(row['eligible'])
        self.assertEqual(row['soc_drop'], 0)
        self.assertEqual(row['estimated_kwh'], 0)

    def test_boundary_windows_do_not_count_outside_parking_sessions(self):
        points = self.complete()
        result = analyze_parking(points, self.start + 86400000, self.end + 86400000, 86)
        self.assertEqual(result['sessions'], [])

    def test_cross_midnight_and_multiple_days_are_classified(self):
        for duration, expected in [(600, 'overnight'), (1500, 'multi_day')]:
            points=[self.point(1300,off=False,speed=20)]
            points += [self.point(t,soc=70-(t-1305)/1000) for t in range(1305,1305+duration+1,5)]
            points.append(self.point(1310+duration,off=False,speed=20))
            row=analyze_parking(points,self.start,self.end+2*86400000,86)['sessions'][0]
            self.assertEqual(row['category'],expected)
            self.assertTrue(row['eligible'])

    def test_conflicting_off_and_speed_cannot_close_a_comparable_parking_session(self):
        points = self.complete()
        points[-1] = self.point(20, off=True, speed=30)
        row = self.result(points)['sessions'][0]
        self.assertFalse(row['eligible'])
        self.assertIn('movement_conflict', row['reasons'])

    def test_boundary_reads_are_not_counted_as_in_range_quality(self):
        points = [self.point(-5, off=False, speed=10), self.point(0), self.point(5, soc=69),
                  self.point(10, off=False, speed=10)]
        result = analyze_parking(points, self.start, self.start+10*60000, 86)
        self.assertEqual(result['quality']['read_count'], 2)
        self.assertEqual(result['quality']['boundary_reads'], 2)
        self.assertEqual(result['eligible_count'], 1)


if __name__ == '__main__':
    unittest.main()
