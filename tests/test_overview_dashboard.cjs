const assert=require('node:assert/strict');
const {summarize}=require('../zeekr_control/static/overview-dashboard.js');
const report={current:{days:[{date:'2026-10-03',distance_km:8.4,trip_count:2,partial_trip_count:1},{date:'2026-10-02',distance_km:null}],events:[{id:'a',kind:'trip_end',end_time:2}]},previous:{days:[{date:'2026-09-30',distance_km:0}],events:[{id:'b',kind:'charge_end',end_time:1}]}};
const ledger={totals:{actual_cents:17000,actual_charge_count:1,life_count:1,unknown_charge_count:1,unlinked_charge_count:1}};
const result=summarize(report,ledger,'2026-10-03',7);
assert.equal(result.today.distance_km,8.4);assert.equal(result.today.partial_trip_count,1);assert.equal(result.days.length,7);assert.equal(result.days.at(-1).distance_km,8.4);assert.equal(result.days.at(-2).distance_km,null);assert.equal(result.days.find(d=>d.date==='2026-09-30').distance_km,0);assert.equal(result.actual,17000);assert.equal(result.pending,2);assert.deepEqual(result.events.map(e=>e.id),['a','b']);
assert.equal(summarize(null,null,'2026-10-03',30).actual,null);assert.equal(summarize(null,null,'2026-10-03',30).today.distance_km,null);assert.equal(summarize(null,null,'2026-10-03',30).pending,null);
assert.equal(summarize(null,{totals:{actual_cents:0,unknown_charge_count:0,unlinked_charge_count:0}},'2026-10-03',7).actual,0);
console.log('PASS trailing periods, fragments, missing/zero, pending unpriced bills, actual-only cost');
// The last completed session must remain available even outside the report window.
const latest={trip_end:{id:'a',kind:'trip_end',end_time:2,distance_km:99},charge_end:{id:'old-charge',end_time:-20,partial:true}};
const withLatest=summarize(report,ledger,'2026-10-03',7,latest);
assert.deepEqual(withLatest.events.map(e=>e.id),['a','b','old-charge']);
assert.equal(withLatest.events[0].distance_km,undefined,'report wins over a duplicate latest summary');
assert.equal(withLatest.events.at(-1).kind,'charge_end');
assert.equal(summarize(null,null,'2026-10-03',7,latest).events.length,2);
console.log('PASS latest sessions outside report window, kind normalization, deduplication');
// A busy day must not push the latest charge out of the compact mixed list.
const {selectRecords}=require('../zeekr_control/static/overview-dashboard.js');
const mixed=[{id:'t1',kind:'trip_end',end_time:6},{id:'t2',kind:'trip_end',end_time:5},{id:'t3',kind:'trip_end',end_time:4},{id:'c1',kind:'charge_end',end_time:1}];
assert.deepEqual(selectRecords(mixed,'all').map(e=>e.id),['t1','t2','c1']);
assert.deepEqual(selectRecords(mixed,'charge_end').map(e=>e.id),['c1']);
assert.deepEqual(selectRecords(mixed,'trip_end').map(e=>e.id),['t1','t2','t3']);
assert.deepEqual(selectRecords([],'all'),[]);
console.log('PASS compact mixed list retains the latest charge and trip');

const pendingReport={current:{days:[{date:'2026-10-03',trip_count:0,distance_km:null,partial_trip_count:0}],events:[]},open_trip:{start_time:Date.parse('2026-10-03T08:00:00+08:00'),end_time:Date.parse('2026-10-03T09:00:00+08:00'),distance_km:25,status:'waiting'}};
let pendingDay=summarize(pendingReport,null,'2026-10-03',7).today;
assert.equal(pendingDay.distance_km,25);
assert.equal(pendingDay.open_distance_km,25);
assert.equal(pendingDay.trip_count,0);
assert.equal(summarize(pendingReport,null,'2026-10-04',7).today.distance_km,null,'never assign another day’s open trip');
pendingReport.current.days[0].distance_km=5;pendingReport.current.days[0].trip_count=1;
assert.equal(summarize(pendingReport,null,'2026-10-03',7).today.distance_km,30);
pendingReport.open_trip.distance_km=null;
assert.equal(summarize(pendingReport,null,'2026-10-03',7).today.distance_km,5);
console.log('PASS unfinished observed distance separate from completed count, missing and day boundaries');
