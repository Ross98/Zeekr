const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));

function harness(file){
 const clock={wall:Date.parse('2026-10-23T12:00:00+08:00'),elapsed:0},nodes=new Map();
 const node=()=>({style:{},innerHTML:'',textContent:'',value:'',addEventListener(){},querySelector(){return null;},getBoundingClientRect(){return {height:100};}});
 class ClockDate extends Date{constructor(...args){super(...(args.length?args:[clock.wall]));}static now(){return clock.wall;}}
 const document={createElement:node,getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}};
 const window={},context={window,document,Date:ClockDate,performance:{now:()=>clock.elapsed},Intl,Map,WeakMap,Number,Promise,setTimeout,clearTimeout};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../zeekr_control/static',file),'utf8'),context,{filename:file});
 return {clock,window,document};
}

async function check(kind,forward){
 const {clock,window}=harness(kind==='overview'?'overview-dashboard.js':'storage-management.js');
 let requests=0,mount;
 if(kind==='overview'){
  const state={insights_context:'synthetic',recent_events:{}};
  const controller=window.OverviewDashboard.create({getState:()=>state,request:async url=>{
   requests++;return url.includes('/report?')?{context:'synthetic',current:{days:[],events:[]},previous:{days:[],events:[]}}
    :{context:'synthetic',totals:{actual_cents:0,unlinked_charge_count:0,unknown_charge_count:0}};
  },escape:String,active:()=>true,openRecord(){},openTool(){},attention:()=>[],time:String});
  mount=()=>controller.mount();
 }else{
  const root={querySelector:()=>({after(){}})};
  mount=()=>window.StorageManagement.mount(root,async url=>{requests++;return url.endsWith('/archives')?{archives:[],trash:[]}:{};});
 }
 mount();await flush();assert.equal(requests,2,kind+' loads immediately even at elapsed time zero');
 clock.wall+=forward?3600000:-3600000;
 clock.elapsed=forward?1000:(kind==='overview'?31001:61001);
 mount();await flush();
 assert.equal(requests,forward?2:4,kind+' cache expiry follows elapsed time despite wall-clock correction');
}

async function checkRollover(start,next){
 const {clock,window,document}=harness('overview-dashboard.js'),queries=[];let active=true;
 clock.wall=Date.parse(start);
 const controller=window.OverviewDashboard.create({getState:()=>({insights_context:'synthetic'}),request:async url=>{
  queries.push(url);return url.includes('/report?')?{context:'synthetic',current:{days:[],events:[]},previous:{days:[],events:[]}}
   :{context:'synthetic',totals:{actual_cents:0,unlinked_charge_count:0,unknown_charge_count:0}};
 },escape:String,active:()=>active,openRecord(){},openTool(){},attention:()=>[],time:String});
 controller.mount();await flush();assert.equal(queries.length,2);
 clock.wall+=1000;clock.elapsed=1000;
 document.hidden=true;controller.refreshDate?.();await flush();assert.equal(queries.length,2,'hidden page defers rollover read');
 document.hidden=false;active=false;controller.refreshDate?.();await flush();assert.equal(queries.length,2,'another active page defers overview rollover read');
 active=true;
 controller.refreshDate?.();await flush();
 assert.equal(queries.length,4,'date rollover refreshes local report and costs without a new vehicle state');
 assert.ok(queries.slice(-2).every(url=>url.includes('date='+next)));
 clock.elapsed=120000;controller.refreshDate?.();await flush();
 assert.equal(queries.length,4,'date check alone does not introduce same-day polling');
}

(async()=>{
 for(const kind of ['overview','storage'])for(const forward of [true,false])await check(kind,forward);
 await checkRollover('2026-10-23T23:59:59.500+08:00','2026-10-24');
 await checkRollover('2026-10-31T23:59:59.500+08:00','2026-11-01');
 await checkRollover('2026-12-31T23:59:59.500+08:00','2027-01-01');
 console.log('CACHE_CLOCKS_PASS: initial zero, monotonic expiry, Beijing day/month rollover, hidden/inactive deferral, no same-day polling');
})().catch(error=>{console.error(error);process.exitCode=1;});
