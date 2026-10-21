const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const stored=new Map(),sessionStorage={getItem:key=>stored.get(key),setItem:(key,value)=>stored.set(key,value)};
const window={addEventListener(){}};vm.runInNewContext(fs.readFileSync('zeekr_control/static/navigation-state.js','utf8'),{window,URLSearchParams,Date,sessionStorage});
const nav=window.NavigationState;
for(const query of ['?p=energy&t=parking&start=2026-09-19&end=2026-09-20&q=1','?p=insights&t=parking&date=2026-09-19','?p=energy&t=parking']){
 const result=nav.read(query);
 assert.equal(result.p,'tracks','retired parking links must open local trips');
 assert.equal(result.s,'local');
 assert.equal(result.t,undefined);
 if(query.includes('2026-09-19'))assert.equal(result.date,'2026-09-19','preserve the selected parking start date');
}

assert.equal(nav.encode(nav.read('?p=tracks&s=cloud&date=2026-10-19&q=1')),'p=tracks&date=2026-10-19&q=1','retired cloud links retain the local query date');
assert.equal(nav.encode(nav.read('?p=energy&t=ledger&month=2026-09&latitude=31&name=家&token=SECRET')),'p=energy&t=ledger&month=2026-09');
assert.equal(nav.encode(nav.read('?p=invalid&date=2026-02-30&month=2026-13&period=invalid')),'');
assert.equal(nav.encode(nav.read('?p=tracks&s=tags&month=2026-09')),'p=tracks&s=tags&month=2026-09');
assert.equal(nav.encode(nav.read('?p=insights&t=parameters')),'p=insights&t=parameters');
assert.equal(nav.read('?p=insights&t=hypotheses').t,'hypotheses');
assert.equal(nav.encode(nav.read('?p=energy&range=range&date=2026-09-01&end=2026-09-30')),'p=energy&range=range&date=2026-09-01&end=2026-09-30');
assert.equal(nav.encode(nav.read('?p=books&t=life&start=2026-09-01&end=2026-09-30')),'p=books&t=life&start=2026-09-01&end=2026-09-30');
assert.equal(nav.read('?p=books&t=life&lifeMode=reminders').lifeMode,'reminders');
window.BookSession.write('owner-a','charge',{month:'2026-08',draft:{amount:'0',note:'保留'}});
assert.equal(window.BookSession.month('owner-a','2026-10'),'2026-08','migrate the saved ledger month');
window.BookSession.setMonth('owner-a','2026-09');
assert.equal(window.BookSession.month('owner-a','2026-10'),'2026-09');
assert.equal(window.BookSession.read('owner-a','charge').draft.note,'保留','month selection cannot overwrite drafts');
assert.equal(window.BookSession.month('owner-b','2026-10'),'2026-10','accounts have independent months');
window.BookSession.setMonth('owner-a','2026-13');
assert.equal(window.BookSession.month('owner-a','2026-10'),'2026-09','invalid input cannot poison the selected month');
assert.deepEqual(JSON.parse(JSON.stringify(window.BookSession.monthRange('2024-02'))),{start:'2024-02-01',end:'2024-02-29'});
console.log('NAVIGATION_STATE_PASS');

for(const old of ['?p=energy&energyTab=process','?p=energy&energyTab=statistics','?p=energy&t=charge-comparison'])assert.deepEqual({...nav.read(old)},{energyTab:'summary',p:'energy'});
assert.equal(nav.read('?p=energy&energyTab=summary&month=2026-09').month,'2026-09');

for(const query of ['?p=tracks&t=routes&month=2026-09','?p=insights&t=routes&date=2026-09-19&q=1']){
 const result=nav.read(query);assert.equal(result.p,'tracks');assert.equal(result.s,'local');assert.equal(result.t,undefined);
 if(query.includes('month='))assert.equal(result.month,'2026-09');
 else assert.equal(result.date,'2026-09-19');
}
