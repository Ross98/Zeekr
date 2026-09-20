'use strict';
const assert=require('node:assert/strict');
const quality=require('../zeekr_control/static/route-quality.js');
const point=(time,longitude=121,extra={})=>({time,latitude:31,longitude,trusted:true,plottable:true,...extra});
const a=point(1000),b=point(6000,121.0001),c=point(66000,121.006),d=point(71000,121.0061);
{
  const result=quality.analyze([a,b,c,d],[[a,b,c,d]],'time');
  assert.deepEqual(result.intervals,{count:3,median:5,max:60});
  assert.equal(result.sparseEdges,1);
  assert.equal(result.edgeCount,3);
  assert.deepEqual(result.parts.map(part=>part.sparse),[false,true,false]);
  assert.deepEqual(result.parts.map(part=>part.points),[[a,b],[b,c],[c,d]],'Every recorded corner and boundary stays');
  assert.ok(result.distances.max>500&&result.distances.max<600);
  assert.match(quality.summary(result),/稀疏示意线/);
  assert.match(quality.summary(result),/直线距离/);
  assert.doesNotMatch(quality.summary(result),/实际行驶.*5/);
}
{
  const untrusted=point(4000,121.001,{trusted:false});
  const result=quality.analyze([a,untrusted,c,d],[[a],[c,d]],'time');
  assert.equal(result.edgeCount,1,'No distance or line across source gaps');
  assert.equal(result.parts.length,1);
  assert.deepEqual(result.parts[0].points,[c,d]);
  assert.equal(result.trustedCount,3);
}
{
  const unknown=point(null),reversed=point(500),future=point(99999999999999);
  const result=quality.analyze([a,unknown,c,reversed,future],[[a,unknown,c,reversed,future]],'time');
  assert.deepEqual(result.intervals,{count:0,median:null,max:null},'Unknown, reversed, and invalid times do not create intervals');
  assert.equal(result.edgeCount,0,'Unknown time never becomes a dense solid line');
  assert.match(quality.summary(result),/未知/);
}
{
  const broken=point(7000,Infinity),untrusted=point(8000,121,{trusted:false});
  const result=quality.analyze([a,broken,untrusted,b],[[a,broken,untrusted,b]],'time');
  assert.equal(result.edgeCount,0,'No bridging over invalid or untrusted points');
  assert.ok(!quality.summary(result).includes('Infinity'));
}
{
  const zero=point(11000),far=point(12000,121.02);
  assert.equal(quality.analyze([a,zero],[[a,zero]],'time').sparseEdges,0,'10 seconds is a declared display boundary');
  assert.equal(quality.analyze([zero,far],[[zero,far]],'time').sparseEdges,1,'Large spatial gap matters even at a short interval');
  assert.equal(quality.analyze([],[],'time').intervals.median,null);
  const local=[{...a,state_time:1000,observed_time:1000},{...b,state_time:null,observed_time:6000}];
  assert.equal(quality.analyze(local,[local],'state_time').edgeCount,0,'Do not substitute observation time for unknown source time');
}
console.log('ROUTE_QUALITY_PASS');
