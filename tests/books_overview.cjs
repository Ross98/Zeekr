const assert=require('node:assert/strict');
const {summarize}=require('../zeekr_control/static/books-overview.js');
const charges={entries:[{date:'2026-09-20',actual_cents:2000,parking_fee_cents:500},{date:'2026-09-21',actual_cents:null,parking_fee_cents:0}],events:[{recorded:false}]};
const life={expenses:{entries:[{date:'2026-09-20',category:'停车',title:'停车费',amount_cents:500},{date:'2026-09-21',category:'洗车',amount_cents:1000}]}};
const result=summarize(charges,life);assert.equal(result.total,4000);assert.equal(result.unknown,1);assert.equal(result.unlinked,1);assert.equal(result.duplicates.length,1);
assert.equal(summarize({entries:[],events:[]},{expenses:{entries:[]}}).total,null);
assert.equal(summarize({entries:[{actual_cents:0,parking_fee_cents:0}],events:[]},{expenses:{entries:[]}}).total,0);
console.log('BOOKS_OVERVIEW_TOTALS_PASS');
