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

const compareValues=sandbox.window.UsageReportPage.compareValues;
assert.equal(typeof compareValues,'function');
assert.equal(compareValues(152.8,186.4,true).difference,33.6);
assert.equal(compareValues(152.8,186.4,true).percent,21.99);
assert.equal(compareValues(0,0,true).reason,'zero_base');
assert.equal(compareValues(null,0,true).reason,'missing_samples');
assert.equal(compareValues(1,2,false).reason,'period_open');
for(const bad of [NaN,Infinity,-1,true])assert.equal(compareValues(bad,5,true).percent,null);
const pairedDays=sandbox.window.UsageReportPage.pairedDays;
const paired=pairedDays(current,{...current,days:[{date:'2026-09-08',distance_km:80,coverage:'observed'}]});
assert.equal(paired[0].previous.distance,80);
assert.equal(paired[0].current.ratio,.5);
assert.equal(paired[0].previous.ratio,1);
assert.equal(paired[1].previous,null);
assert.equal(paired[2].current.distance,0);
assert.equal(paired[5].current.distance,null);
console.log('REPORT_COMPARISON_PASS: closed/zero/missing/invalid values and shared daily scale');
const departureBins=sandbox.window.UsageReportPage.departureBins;
assert.equal(typeof departureBins,'function');
assert.deepEqual(Array.from(departureBins(Array(24).fill(0))),[0,0,0,0,0,0]);
assert.equal(departureBins([1,2,3,4])[0],10);
assert.equal(departureBins([1,2,3,4])[1],null);
assert.equal(departureBins([true,0,0,0])[0],null);
const eventGraphic=sandbox.window.UsageReportPage.eventGraphic;
const sample=eventGraphic({kind:'trip_end',distance_km:0,start_soc:70,end_soc:60,estimated_kwh:null},{trip:40,charge:60,energy:20});
assert.equal(sample.value,0);assert.equal(sample.ratio,0);assert.equal(sample.energyRatio,null);assert.equal(sample.startSoc,70);
assert.equal(eventGraphic({kind:'charge_end',duration_seconds:1800,start_soc:null,end_soc:80},{trip:40,charge:60,energy:20}).ratio,.5);
assert.equal(eventGraphic({kind:'trip_end',distance_km:-1,start_soc:101,end_soc:80},{trip:40,charge:60,energy:20}).startSoc,null);
console.log('REPORT_REMAINING_GRAPHICS_PASS: missing departure bins, real zero and bounded SOC endpoints');
const {changeExtent,deltaGeometry,dailyDeltas,differenceDomain}=sandbox.window.UsageReportPage;
assert.equal(changeExtent([22,-50,null]),60);
assert.equal(changeExtent([123.33,-200]),210);
assert.equal(changeExtent([null,Infinity,NaN]),60);
assert.equal(deltaGeometry(-30,60).left,25);
assert.equal(deltaGeometry(-30,60).width,25);
assert.equal(deltaGeometry(0,60).width,0);
assert.equal(deltaGeometry(null,60),null);
const deltas=dailyDeltas({...current,days:[{date:'2026-09-15',distance_km:20,coverage:'observed'},{date:'2026-09-16',distance_km:0,coverage:'observed'},{date:'2026-09-17',distance_km:9,coverage:'future'}]},
 {...current,days:[{date:'2026-09-08',distance_km:40,coverage:'observed'},{date:'2026-09-09',distance_km:0,coverage:'observed'},{date:'2026-09-10',distance_km:4,coverage:'observed'}]});
assert.deepEqual(Array.from(deltas,d=>d.difference),[-20,0,null]);
const positive=differenceDomain([8.6,11.2,0,null]);assert.equal(positive.low,0);assert.ok(positive.high>=11.2);
const negative=differenceDomain([-40,20]);assert.ok(negative.low<=-40&&negative.high>=20);
assert.ok(differenceDomain([0,0]).high>0);
console.log('COMPACT_REPORT_DELTA_PASS: shared untruncated percent scale, zero-centered geometry, signed daily differences and unknown/future');
