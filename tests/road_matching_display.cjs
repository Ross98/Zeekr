'use strict';
const assert=require('node:assert/strict');
const quality=require('../zeekr_control/static/route-quality.js');
const pts=[0,1,2,3].map(i=>({state_time:1000+60000*i,latitude:31,longitude:121+i*.001,trusted:true,plottable:true}));
const density=quality.analyze(pts,[pts],'state_time');
const matched={status:'partial',coordinate_system:'WGS84',lines:[[[121,31],[121.001,31.001],[121.002,31]]],spans:[[0,2]],matched_indices:[0,2],eligible_points:4,issues:1};
let display=quality.display({observations:pts,road_matching:matched},density);
assert.equal(display.roads.length,1);assert.deepEqual(display.fallback.map(p=>p.points),[[pts[2],pts[3]]]);
assert.equal(display.fallback[0].sparse,true);
assert.match(quality.matchSummary(matched),/算法推断/);assert.match(quality.matchSummary(matched),/2\/4/);
for(const status of ['unavailable','timeout','busy','error','unmatched','limit']){
 display=quality.display({observations:pts,road_matching:{...matched,status,lines:[],spans:[]}},density);
 assert.deepEqual(display.fallback,density.parts);assert.equal(display.roads.length,0);
 assert.match(quality.matchSummary({...matched,status}),/采样点连线/);
}
const gaps=quality.analyze(pts,[[pts[0],pts[1]],[pts[2],pts[3]]],'state_time');
assert.equal(quality.display({observations:pts,road_matching:{...matched,spans:[[0,1],[2,3]]}},gaps).fallback.length,0);
assert.deepEqual(quality.display({observations:pts},density).fallback,density.parts);
console.log('Road matching display: inferred geometry, source coverage, gaps, safe fallbacks passed');
