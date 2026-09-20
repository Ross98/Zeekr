const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sandbox = {window: {}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../zeekr_control/static/usage-reports.js'), 'utf8'), sandbox);
const analyze = sandbox.window.UsageReportPage.analyze;
assert.equal(typeof analyze, 'function', 'Report observations have a testable calculation boundary');
const current = {
  totals: {distance_km: 67, partial_trip_count: 1, partial_distance_km: 7},
  samples: {distance: 3},
  days: [
    {date: '2026-09-15', distance_km: 40, coverage: 'missing'},
    {date: '2026-09-16', distance_km: null, coverage: 'observed'},
    {date: '2026-09-17', distance_km: 0, coverage: 'observed'},
    {date: '2026-09-18', distance_km: 27, coverage: 'observed'},
    {date: '2026-09-19', distance_km: null, coverage: 'missing'},
    {date: '2026-09-20', distance_km: null, coverage: 'future'}
  ]
};
const result = analyze(current);
assert.equal(result.averageDistance, 67/3, 'All valid recorded-distance samples form the mean, including partials');
assert.equal(result.peakDistance, 40, 'Events remain usable without archive coverage');
assert.deepEqual(Array.from(result.peakDates), ['2026-09-15']);
assert.equal(result.elapsedDays, 5, 'Future dates do not dilute archive coverage');
assert.equal(result.coveredDays, 3);
assert.deepEqual(Array.from(result.days, day => day.state), ['value', 'missing', 'value', 'value', 'missing', 'future']);
assert.equal(result.days[2].distance, 0, 'A measured zero remains a zero');
assert.equal(result.days[2].ratio, 0);
assert.equal(result.days[1].distance, null, 'A missing value is never a zero');
assert.equal(result.days[1].ratio, null, 'No fabricated bar for missing observations');
assert.equal(result.days[3].ratio, .675);

const tied = analyze({...current, days: [...current.days, {date: '2026-09-21', distance_km: 40, coverage: 'observed'}]});
assert.deepEqual(Array.from(tied.peakDates), ['2026-09-15', '2026-09-21']);
for (const distance of [null, undefined, NaN, Infinity, -1]) {
  const unknown = analyze({...current, totals: {...current.totals, distance_km: distance}, days: [{date: '2026-09-01', distance_km: distance, coverage: 'missing'}]});
  assert.equal(unknown.averageDistance, null);
  assert.equal(unknown.peakDistance, null);
  assert.equal(unknown.days[0].distance, null);
}
assert.equal(analyze({...current, samples: {distance: 0}}).averageDistance, null);
const zero = analyze({...current, totals: {distance_km: 0}, samples: {distance: 1}, days: [{date: '2026-09-01', distance_km: 0, coverage: 'observed'}]});
assert.equal(zero.averageDistance, 0);
assert.equal(zero.peakDistance, 0);
assert.equal(zero.days[0].ratio, 0);
const future = analyze({...current, totals: {distance_km: null}, samples: {distance: 0}, days: [{date: '2026-11-01', distance_km: 20, coverage: 'future'}]});
assert.equal(future.elapsedDays, 0);
assert.equal(future.coveredDays, 0);
assert.equal(future.peakDistance, null);
assert.equal(future.days[0].distance, null);
assert.equal(analyze({...current, days: []}).peakDistance, null);
assert.equal(current.days[0].state, undefined, 'Analysis does not mutate response data');
console.log('USAGE_REPORT_ANALYSIS_PASS: valid-sample mean, ties, independent event/archive sources, missing/zero/future and bounded chart ratios');
