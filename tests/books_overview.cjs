const assert=require('node:assert/strict');
const {summarize}=require('../zeekr_control/static/books-overview.js');
const result=summarize({totals:{actual_cents:17000,charge_cents:10000,charge_parking_cents:2000,life_cents:5000,unknown_charge_count:1,unlinked_charge_count:2},duplicates:[{id:'test'}]});
assert.equal(result.total,17000);assert.equal(result.charge,10000);assert.equal(result.daily,5000);assert.equal(result.parking,2000);assert.equal(result.unknown,1);assert.equal(result.unlinked,2);assert.equal(result.duplicates.length,1);
assert.equal(summarize({totals:{actual_cents:null}}).total,null);assert.equal(summarize({totals:{actual_cents:0}}).total,0);
console.log('BOOKS_OVERVIEW_SERVER_TOTALS_PASS');
