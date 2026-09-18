// Pure page filtering rules: readable unverified values stay usable; unknowns stay hidden.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({URL,document:{addEventListener(){}},search:'',groupFilter:'',unknownOnly:false,
  state:{model:{fields:[
    {path:'known',name:'有原值',group:'测试',raw:'0',value:'0',evidence:'待核实'},
    {path:'missing',name:'缺失',group:'测试',raw:'未知',value:'未知',evidence:'未知'},
    {path:'invalid',name:'无有效读数',group:'测试',raw:'999',value:'未知',evidence:'未知'}
  ]},field_reviews:{vehicle:'test',revision:0,records:[]}}});
vm.runInContext(fs.readFileSync('zeekr_control/static/field-reviews.js','utf8'),context);
assert.equal(JSON.stringify(context.reviewItems().map(f=>f.path)),JSON.stringify(['known']));
context.state.field_reviews.records=[{path:'known',scope:'value',raw:'0',status:'confirmed',meaning:'关闭'}];
assert.equal(context.reviewStatus(context.state.model.fields[0]),'confirmed');
context.state.model.fields[0].raw='1';
assert.equal(context.reviewStatus(context.state.model.fields[0]),'partial');
context.state.field_reviews.records.push({path:'known',scope:'field',raw:'0',status:'na'});
assert.equal(context.reviewStatus(context.state.model.fields[0]),'na');
console.log('Review rules passed: unknowns hidden, unverified visible, enum isolation, whole-field not applicable.');
context.esc = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
context.state.model.fields[0].reference = {unit:'未知',basis:'术语推测',note:'动态弯道照明',sources:[]};
context.search = '动态弯道';
assert.equal(context.reviewItems().length,1,'Search includes dictionary explanations');
assert.match(context.renderFieldReference(context.state.model.fields[0]),/术语推测/);
const unsafe = context.renderFieldReference({reference:{unit:'<img src=x>',basis:'推测',note:'<script>bad()</script>',
  sources:[{title:'bad',url:'javascript:alert(1)'},{title:'HELLA',url:'https://www.hella.com/'}]}});
assert.ok(!unsafe.includes('<script>') && !unsafe.includes('<img') && !unsafe.includes('javascript:'));
assert.match(unsafe,/https:\/\/www.hella.com/);
assert.match(unsafe,/noopener noreferrer/);
assert.equal(context.newReviewDraft(context.state.model.fields[0]).meaning,'','Dictionary must not preconfirm manual reviews');
console.log('Dictionary references passed: search, inference labels, escaping and unchanged manual defaults.');
