const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const manifest=require('../scripts/desktop-test-manifest.json');
const files=[...manifest.groups.smoke,...manifest.groups.review].filter(f=>!f.endsWith('/browser_failure_evidence.cjs'));
let count=0;
for(const entry of files){
 const file=entry.endsWith('/ui_overview_benchmark.cjs')?'tests/benchmark_overview.cjs':entry;
 const source=fs.readFileSync(path.resolve(__dirname,'..',file),'utf8');
 if(source.includes('fixture(')&&source.includes('ui_insight_helpers.cjs'))assert.match(source,/await f\.fail\(/,file+' must capture before fixture teardown');
 else{
  assert.match(source,/startEvidence/,file+' must opt into synthetic evidence');
  assert.match(source,/await evidence\.fail\(/,file+' must capture before browser teardown');
 }
 count++;
}
console.log(`BROWSER_EVIDENCE_COVERAGE_PASS: ${count} product scripts capture before teardown`);
