const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const sandbox={window:{}};vm.runInNewContext(fs.readFileSync('zeekr_control/static/trip-tags.js','utf8'),sandbox);
const {placePairGroups,placePairStatistics}=sandbox.window.TripTagsPage;
const places=[{id:'h',label:'合成家园',statistics_key:'region:home',commute_alias:'家'}, {id:'old-home',label:'合成家园',statistics_key:'region:home',commute_alias:'家'}, {id:'b',label:'合成公司'}, {id:'elsewhere',label:'合成家园'}];
const events=[{id:'a',start_place:'h',end_place:'b',distance_km:10,duration_seconds:600,estimated_kwh:2,partial:false,tags:['通勤','上班']},
 {id:'fragment',start_place:'old-home',end_place:'b',distance_km:null,duration_seconds:0,estimated_kwh:null,partial:true,tags:['出行'],start_place_evidence:{source:'parking_inferred'}},
 {id:'return',start_place:'b',end_place:'h',distance_km:0,duration_seconds:300,estimated_kwh:0,partial:false,tags:['通勤'],end_place_evidence:{source:'parking_inferred'}},
 {id:'unknown',start_place:null,end_place:'b',distance_km:99}, {id:'different',start_place:'elsewhere',end_place:'b',distance_km:50}];
const before=JSON.stringify({places,events});
assert.equal(placePairGroups(places).length,3);
let s=placePairStatistics(events,places,'region:home','b','both','');
assert.equal(s.total.count,3);assert.equal(s.forward.count,2);assert.equal(s.backward.count,1);
assert.equal(s.total.partial,1);assert.equal(s.total.start_inferred,1);assert.equal(s.total.end_inferred,1);
assert.equal(s.total.distance.total,10);assert.equal(s.total.distance.samples,2);
assert.equal(s.total.duration.total,900);assert.equal(s.total.duration.samples,3);
assert.equal(s.total.energy.total,2);assert.equal(s.total.energy.samples,2);
assert.equal(placePairStatistics(events,places,'region:home','b','forward','tag:通勤').total.count,1);
assert.equal(placePairStatistics(events,places,'region:home','b','backward','').total.count,1);
s=placePairStatistics(events,places,'region:home','b','both','tag:不存在');assert.equal(s.total.count,0);assert.equal(s.total.distance.total,null);
assert.equal(placePairStatistics(events,places,'region:home','region:home','both','').valid,false);
assert.equal(placePairStatistics(events,places,'missing','b','both','').valid,false);
assert.equal(JSON.stringify({places,events}),before);
console.log('PLACE_PAIR_STATISTICS_PASS');
