const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const window = {};
const document = {activeElement:{id:''}, getElementById:()=>null};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../zeekr_control/static/parking.js'),'utf8'), {window,document,Intl,Date,Number,encodeURIComponent});

const requests=[];
const page=window.ParkingPage.create({
  getState:()=>({insights_context:'synthetic-owner'}),
  request:url=>{requests.push(url);return new Promise(()=>{});},
  escape:value=>String(value),
  active:()=>true,
  time:value=>String(value)
});
const container={isConnected:true,innerHTML:'',contains:()=>true,querySelector:()=>({disabled:false})};

page.mount(container);
assert.equal(requests.length,0,'opening parking analysis must not start a request');
assert.match(container.innerHTML,/开始日期/);
assert.match(container.innerHTML,/结束日期/);
assert.match(container.innerHTML,/分析停车观测/);

page.handle({type:'input',target:{id:'parking-start',value:'2026-09-01'}});
page.handle({type:'input',target:{id:'parking-end',value:'2026-09-07'}});
assert.equal(requests.length,0,'editing the range must not start a request');
page.handle({type:'click',target:{closest:()=>({dataset:{parking:'load'},disabled:false})}});
assert.deepEqual(requests,['/api/insights/parking?start=2026-09-01&end=2026-09-07']);

page.openDate('2026-09-19');
page.mount({isConnected:true,innerHTML:'',contains:()=>true,querySelector:()=>({disabled:false})});
assert.equal(requests.length,1,'opening parking from calendar must not start another request');
console.log('PARKING_MANUAL_START_PASS');
