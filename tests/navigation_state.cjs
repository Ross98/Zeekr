const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const window={};vm.runInNewContext(fs.readFileSync('zeekr_control/static/navigation-state.js','utf8'),{window,URLSearchParams,Date});
const nav=window.NavigationState;
assert.equal(nav.encode(nav.read('?p=energy&t=ledger&month=2026-09&latitude=31&name=家&token=SECRET')),'p=energy&t=ledger&month=2026-09');
assert.equal(nav.encode(nav.read('?p=invalid&date=2026-02-30&month=2026-13&period=invalid')),'');
assert.equal(nav.encode(nav.read('?p=tracks&s=tags&month=2026-09')),'p=tracks&s=tags&month=2026-09');
assert.equal(nav.encode(nav.read('?p=energy&range=range&date=2026-09-01&end=2026-09-30')),'p=energy&range=range&date=2026-09-01&end=2026-09-30');
console.log('NAVIGATION_STATE_PASS');
