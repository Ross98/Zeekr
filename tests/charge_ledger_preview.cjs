const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const window={};
const entries={innerHTML:''},trash={innerHTML:''};
const node={isConnected:true,innerHTML:'',contains:()=>false,
  querySelector:selector=>({'#ledger-entries':entries,'#ledger-trash':trash}[selector]||null)};
const document={activeElement:null,getElementById:()=>null};
vm.runInNewContext(fs.readFileSync('zeekr_control/static/charge-ledger.js','utf8'),{window,document,Intl,Date,Number});
const event={start_time:1790000000000,end_time:1790005400000,duration_seconds:5400,estimated_kwh:20,battery_capacity_kwh:86,charge_mode:'ac'};
const row={id:'one',date:'2026-09-20',source:'public',event,charge_mode_override:'dc',actual_cents:2062,estimated_cents:null,
  parking_fee_cents:200,metered_kwh:23.46,estimate_basis:null,note:'停车2元'};
const dc={...row,id:'two',event:{...event,charge_mode:'dc'},charge_mode_override:null,actual_cents:4324,estimated_cents:4500,metered_kwh:45.52,estimate_basis:'metered_price'};
const unknown={...row,id:'three',event:{...event,charge_mode:null},charge_mode_override:null,metered_kwh:0};
const manual={...row,id:'four',event:null,charge_mode_override:'ac'};
const data={context:'owner',window:{start_date:'2026-09-01'},entries:[row,dc,unknown,manual],trash:[],events:[],totals:{},
  sources:{home:{},public:{},unknown:{}},trend:[],cost_per_km:{}};
const page=window.ChargeLedgerPage.create({getState:()=>({insights_context:'owner'}),request:async()=>data,
  escape:value=>String(value),active:()=>true,time:value=>String(value)});
page.mount(node);
setImmediate(()=>{
  assert.match(entries.innerHTML,/class="ledger-preview"/);
  assert.match(entries.innerHTML,/1790000000000/);
  assert.match(entries.innerHTML,/1790005400000/);
  assert.match(entries.innerHTML,/1 小时 30 分钟/);
  assert.match(entries.innerHTML,/23\.46 kWh/);
  assert.match(entries.innerHTML,/20\.62 元/);
  assert.match(entries.innerHTML,/<details/);
  assert.doesNotMatch(entries.innerHTML,/<details[^>]*open/);
  const preview=entries.innerHTML.match(/<summary class="ledger-preview">([\s\S]*?)<\/summary>/)?.[1];
  assert.ok(preview);
  assert.doesNotMatch(preview,/停车费|参考估算|停车2元|估算依据/);
  const acArticle=entries.innerHTML.match(/<article data-ledger-entry="one">([\s\S]*?)<\/article>/)?.[1];
  const dcArticle=entries.innerHTML.match(/<article data-ledger-entry="two">([\s\S]*?)<\/article>/)?.[1];
  const unknownArticle=entries.innerHTML.match(/<article data-ledger-entry="three">([\s\S]*?)<\/article>/)?.[1];
  const manualArticle=entries.innerHTML.match(/<article data-ledger-entry="four">([\s\S]*?)<\/article>/)?.[1];
  assert.match(acArticle,/直流 DC · 手动/);
  assert.match(acArticle,/等效充电单价[^<]*<strong>0\.8789 元\/kWh/);
  assert.doesNotMatch(acArticle,/参考估算/);
  assert.match(dcArticle,/直流 DC/);
  assert.match(dcArticle,/参考估算[^<]*<strong>45\.00 元/);
  assert.match(unknownArticle,/方式未知/);
  assert.doesNotMatch(unknownArticle,/元\/kWh/);
  assert.match(manualArticle,/交流 AC · 手动/);
  console.log('CHARGE_LEDGER_PREVIEW_PASS');
});
