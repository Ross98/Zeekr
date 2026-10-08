const assert = require('node:assert/strict');
const {selectFields, stateKey} = require('../zeekr_control/static/vehicle.js');
const data = {groups:[{name:'门窗'},{name:'轮胎'}],fields:[
  {path:'missing',name:'无数据',group:'门窗',status:'missing'},
  {path:'pressure',name:'右后胎压',group:'轮胎',status:'known'},
  {path:'window.a',name:'左前车窗',group:'门窗',status:'known'},
  {path:'window.b',name:'右前车窗',group:'门窗',status:'pending'}]};
assert.deepEqual(selectFields(data,{}).fields.map(f=>f.path),['window.a','window.b','pressure','missing']);
assert.deepEqual(selectFields(data,{query:'WINDOW',status:'pending'}).fields.map(f=>f.path),['window.b']);
assert.equal(selectFields(data,{group:'轮胎',query:'左前'}).total,0);
assert.equal(selectFields(data,{query:'no match'}).total,0);
const large={...data,fields:Array.from({length:43},(_,i)=>({...data.fields[1],path:'p'+i}))};
assert.equal(selectFields(large).fields.length,43,'All filtered rows available for scrolling');
assert.equal(data.fields[0].path,'missing','selection does not reorder source');
const original={vehicle:1,request_key:'server',snapshot_revision:'one',read_time:10,field_reviews:{vehicle:'car-a'}};
for(const changed of [{snapshot_revision:'two'},{vehicle:2},{request_key:'new server'},{field_reviews:{vehicle:'car-b'}}])assert.notEqual(stateKey(original),stateKey({...original,...changed}));
console.log('VEHICLE_SELECTION_PASS');
(async()=>{
  let state={vehicle:1,request_key:'server',snapshot_revision:'a',read_time:1,field_reviews:{vehicle:'one'}};
  const queue=[];
  const view=require('../zeekr_control/static/vehicle.js').create({getState:()=>state,request:()=>new Promise((resolve,reject)=>queue.push({resolve,reject})),redraw:()=>{},escape:String,age:()=>'',active:()=>true});
  const payload=(vehicle,key,revision,name)=>({vehicle,vehicle_key:key,snapshot_revision:revision,updated_time:1,counts:{total:1,returned:1},groups:[{name:'门窗',count:1}],fields:[{path:'safe',name,group:'门窗',status:'pending',value:'待核实',raw:'0'}]});
  const first=view.ensure();state={...state,vehicle:2,field_reviews:{vehicle:'two'},snapshot_revision:'b'};
  const second=view.ensure();queue[1].resolve(payload(2,'two','b','NEW'));await second;
  queue[0].resolve(payload(1,'one','a','OLD'));await first;
  assert.match(view.render(()=>'',()=>''),/NEW/);assert.doesNotMatch(view.render(()=>'',()=>''),/OLD/);
  state={...state,snapshot_revision:'c'};const failed=view.ensure();queue[2].reject(Error('offline'));await failed;
  assert.match(view.render(()=>'',()=>''),/NEW/);assert.match(view.render(()=>'',()=>''),/保留上次参数快照/);
  await view.ensure();assert.equal(queue.length,3,'No automatic failure retry loop');
  const retry=view.ensure(true);queue[3].resolve(payload(2,'two','c','RECOVERED'));await retry;
  assert.match(view.render(()=>'',()=>''),/RECOVERED/);
  state={...state,vehicle:3,field_reviews:{vehicle:'three'}};
  assert.doesNotMatch(view.render(()=>'',()=>''),/RECOVERED/,'Clear old vehicle before next request');
  const mismatch=view.ensure();queue[4].resolve(payload(2,'two','c','WRONG'));await mismatch;
  assert.doesNotMatch(view.render(()=>'',()=>''),/WRONG/);
  console.log('VEHICLE_REQUEST_ISOLATION_PASS');
})().catch(error=>{console.error(error);process.exitCode=1});
