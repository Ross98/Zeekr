const assert=require('node:assert/strict');
const {summarize}=require('../zeekr_control/static/overview-dashboard.js');
const report={current:{days:[{date:'2026-10-03',distance_km:8.4,trip_count:2,partial_trip_count:1},{date:'2026-10-02',distance_km:null}],events:[{id:'a',kind:'trip_end',end_time:2}]},previous:{days:[{date:'2026-09-30',distance_km:0}],events:[{id:'b',kind:'charge_end',end_time:1}]}};
const ledger={totals:{actual_cents:0,actual_count:1,unpriced_count:1},events:[{id:'x',recorded:false},{id:'y',recorded:true}],entries:[{event:{id:'y'},actual_cents:null}]};
const result=summarize(report,ledger,'2026-10-03',7);
assert.equal(result.today.distance_km,8.4);assert.equal(result.today.partial_trip_count,1);assert.equal(result.days.length,7);assert.equal(result.days.at(-1).distance_km,8.4);assert.equal(result.days.at(-2).distance_km,null);assert.equal(result.days.find(d=>d.date==='2026-09-30').distance_km,0);assert.equal(result.actual,0);assert.equal(result.pending,2);assert.deepEqual(result.events.map(e=>e.id),['a','b']);
assert.equal(summarize(null,null,'2026-10-03',30).actual,null);assert.equal(summarize(null,null,'2026-10-03',30).today.distance_km,null);assert.equal(summarize(null,null,'2026-10-03',30).pending,null);
console.log('PASS trailing periods, fragments, missing/zero, pending unpriced bills, actual-only cost');
