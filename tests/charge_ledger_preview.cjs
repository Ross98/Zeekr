const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const window={};
const entries={innerHTML:''},trash={innerHTML:''};
const node={isConnected:true,innerHTML:'',contains:()=>false,
  querySelector:selector=>({'#ledger-entries':entries,'#ledger-trash':trash}[selector]||null)};
const document={activeElement:null,getElementById:()=>null};
vm.runInNewContext(fs.readFileSync('zeekr_control/static/charge-ledger.js','utf8'),{window,document,Intl,Date,Number});
const event={start_time:1790000000000,end_time:1790005400000,duration_seconds:5400,estimated_kwh:20,battery_capacity_kwh:86};
const row={id:'one',date:'2026-09-20',source:'public',event,actual_cents:4324,estimated_cents:4500,
  parking_fee_cents:200,metered_kwh:45.52,estimate_basis:'metered_price',note:'停车2元'};
const data={context:'owner',window:{start_date:'2026-09-01'},entries:[row],trash:[],events:[],totals:{},
  sources:{home:{},public:{},unknown:{}},trend:[],cost_per_km:{}};
const page=window.ChargeLedgerPage.create({getState:()=>({insights_context:'owner'}),request:async()=>data,
  escape:value=>String(value),active:()=>true,time:value=>String(value)});
page.mount(node);
setImmediate(()=>{
  assert.match(entries.innerHTML,/class="ledger-preview"/);
  assert.match(entries.innerHTML,/1790000000000/);
  assert.match(entries.innerHTML,/1790005400000/);
  assert.match(entries.innerHTML,/1 小时 30 分钟/);
  assert.match(entries.innerHTML,/45\.52 kWh/);
  assert.match(entries.innerHTML,/43\.24 元/);
  assert.match(entries.innerHTML,/<details/);
  assert.doesNotMatch(entries.innerHTML,/<details[^>]*open/);
  const preview=entries.innerHTML.match(/<summary class="ledger-preview">([\s\S]*?)<\/summary>/)?.[1];
  assert.ok(preview);
  assert.doesNotMatch(preview,/停车费|参考估算|停车2元|估算依据/);
  console.log('CHARGE_LEDGER_PREVIEW_PASS');
});
