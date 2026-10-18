// Real CLI, fresh nested artifact parent, separate cwd, and repeated-run isolation.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawnSync}=require('node:child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'zeekr-recall-cli-'));
try{
  const parent=path.join(root,'new','nested');
  function run(){
    const result=spawnSync(process.execPath,[path.join(__dirname,'benchmark_daily_recall.cjs'),parent],{
      cwd:root,env:{...process.env,DESKTOP_ONLY:'1'},encoding:'utf8',timeout:120000
    });
    assert.ifError(result.error);assert.equal(result.status,0,result.stderr||result.stdout);
    const data=JSON.parse(result.stdout);
    assert.equal(path.dirname(path.dirname(data.output_file)),parent);
    assert.deepEqual(JSON.parse(fs.readFileSync(data.output_file,'utf8')),data);
    assert.deepEqual(data.requests.measured,{timeline:3,reference:3,history:3,year:3});
    assert.deepEqual(data.requests.unexpected,[]);assert.deepEqual(data.requests.posts,[]);
    assert.ok(data.requests.synthetic_tiles>0);
    assert.equal(data.map.observations,4181);assert.equal(data.map.connected,true);
    assert.equal(data.map.drawing.samples,4181);assert.equal(data.map.drawing.positions_preserved,true);
    assert.equal(data.map.drawing.endpoints_preserved,true);assert.equal(data.map.drawing.gaps_preserved,true);assert.ok(data.map.drawing.gap_markers>0);
    assert.ok(data.map.drawing.vector_dom_nodes<100);
    assert.equal(data.selection.observations,1);assert.equal(data.selection.retains_map,true);
    assert.equal(data.year.days,366);assert.equal(data.year.trips,366);
    return data;
  }
  const first=run(),saved=fs.readFileSync(first.output_file,'utf8'),second=run();
  assert.notEqual(first.output_file,second.output_file,'each invocation owns its artifact directory');
  assert.equal(fs.readFileSync(first.output_file,'utf8'),saved,'second invocation preserves first evidence');
  console.log('DAILY_RECALL_BENCHMARK_CLI_PASS: nested output, independent cwd, isolated runs, strict benchmark checks');
}finally{fs.rmSync(root,{recursive:true,force:true});}
