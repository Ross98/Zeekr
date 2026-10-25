const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawnSync}=require('node:child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'zeekr-runner-'));
try{
 fs.mkdirSync(path.join(root,'scripts'));fs.mkdirSync(path.join(root,'tests'));
 for(const file of ['test-desktop.cjs','check-desktop-manifest.cjs'])fs.copyFileSync(path.resolve(__dirname,'../scripts',file),path.join(root,'scripts',file));
 fs.writeFileSync(path.join(root,'tests/failure.cjs'),'process.exit(7)');
 fs.writeFileSync(path.join(root,'tests/success.cjs'),"console.log('SUCCESS_AFTER_FAILURE '+process.env.DESKTOP_ONLY)");
 fs.writeFileSync(path.join(root,'tests/hang.cjs'),`const {spawn}=require('node:child_process');const fs=require('node:fs');const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore',detached:true});fs.writeFileSync('descendant.pid',String(child.pid));setInterval(()=>{},1000);`);
 const manifest={groups:{unit:['tests/failure.cjs','tests/success.cjs','tests/hang.cjs'],smoke:[],review:[]},exclusions:[]};
 fs.writeFileSync(path.join(root,'scripts/desktop-test-manifest.json'),JSON.stringify(manifest));
 const run=spawnSync(process.execPath,[path.join(root,'scripts/test-desktop.cjs'),'unit'],{cwd:root,encoding:'utf8',timeout:10000,env:{...process.env,DESKTOP_TEST_TIMEOUT_MS:'500',DESKTOP_RESULT_DIR:path.join(root,'results')}});
 assert.equal(run.status,1,run.stderr);assert.match(run.stdout,/SUCCESS_AFTER_FAILURE 1/);
 const files=fs.readdirSync(path.join(root,'results'));assert.equal(files.length,1);
 const result=JSON.parse(fs.readFileSync(path.join(root,'results',files[0]),'utf8'));
 assert.equal(result.passed,false);assert.deepEqual(result.results.map(r=>r.status),['failed','passed','timeout']);
 assert.equal(result.results[0].exit_code,7);
 const pid=Number(fs.readFileSync(path.join(root,'descendant.pid'),'utf8'));
 // A terminated orphan may briefly be a zombie on Linux, never a live worker.
 const ps=spawnSync('ps',['-o','stat=','-p',String(pid)],{encoding:'utf8'});
 assert.ok(ps.status!==0||!ps.stdout.trim()||ps.stdout.trim().startsWith('Z'),'timed-out descendants must be stopped');
 fs.mkdirSync(path.join(root,'zeekr_control/static'),{recursive:true});
 fs.writeFileSync(path.join(root,'zeekr_control/static/feature.js'),'const usable=true;');
 fs.writeFileSync(path.join(root,'zeekr_control/static/._feature.js'),Buffer.from([0,5,22,7]));
 const syntax=spawnSync(process.execPath,[path.join(root,'scripts/test-desktop.cjs'),'syntax'],{cwd:root,encoding:'utf8',timeout:10000});
 assert.equal(syntax.status,0,syntax.stdout+syntax.stderr);
 assert.match(syntax.stdout,/\[syntax\] zeekr_control\/static\/feature\.js/);
 assert.doesNotMatch(syntax.stdout,/\._feature\.js/);
 console.log('DESKTOP_RUNNER_PASS: continue after failure, truthful summary, bounded timeout, descendant cleanup');
}finally{
 const file=path.join(root,'descendant.pid');if(fs.existsSync(file)){try{process.kill(Number(fs.readFileSync(file,'utf8')),'SIGKILL');}catch(error){if(error.code!=='ESRCH')throw error;}}
 fs.rmSync(root,{recursive:true,force:true});
}

// Real two-shard execution + fail-closed aggregation in an isolated repository.
const shards=fs.mkdtempSync(path.join(os.tmpdir(),'zeekr-shards-'));
try{
 fs.mkdirSync(path.join(shards,'scripts'));fs.mkdirSync(path.join(shards,'tests'));
 for(const file of ['test-desktop.cjs','check-desktop-manifest.cjs'])fs.copyFileSync(path.resolve(__dirname,'../scripts',file),path.join(shards,'scripts',file));
 const files=['a','b','c','d'].map(name=>`tests/${name}.cjs`);
 for(const file of files)fs.writeFileSync(path.join(shards,file),`console.log('EXECUTED ${file} '+process.env.DESKTOP_ONLY);`);
 fs.writeFileSync(path.join(shards,'scripts/desktop-test-manifest.json'),JSON.stringify({groups:{unit:[],smoke:files.slice(0,1),review:files.slice(1)},exclusions:[]}));
 const resultDir=path.join(shards,'results'),env={...process.env,DESKTOP_RESULT_DIR:resultDir,GITHUB_SHA:'a'.repeat(40),GITHUB_RUN_ID:'101',GITHUB_RUN_ATTEMPT:'2'};
 const run=(args,extra={})=>spawnSync(process.execPath,[path.join(shards,'scripts/test-desktop.cjs'),...args],{cwd:shards,encoding:'utf8',timeout:15000,env:{...env,...extra}});
 for(const [index,expected] of [[1,[files[0],files[2]]],[2,[files[1],files[3]]]]){
  const result=run(['desktop',`--shard=${index}/2`]);assert.equal(result.status,0,result.stdout+result.stderr);
  assert.deepEqual([...result.stdout.matchAll(/EXECUTED (tests\/\w+.cjs) 1/g)].map(m=>m[1]),expected);
 }
 const reports=fs.readdirSync(resultDir).map(name=>path.join(resultDir,name));assert.equal(reports.length,2);
 const originals=reports.map(file=>fs.readFileSync(file,'utf8'));
 const verify=()=>run(['verify-shards',resultDir,'2']);
 assert.equal(verify().status,0,'complete partition passes');
 for(const change of [r=>r.results.pop(),r=>r.results.push({...r.results[0]}),r=>{r.results[0].status='failed';},r=>{r.passed=false;},r=>{r.interrupted=true;},r=>{r.shard.index=2;},r=>{r.ci.sha='b'.repeat(40);},r=>{r.ci.run_attempt='1';},r=>{r.ci.run_id='99';}]){
  const r=JSON.parse(originals[0]);change(r);fs.writeFileSync(reports[0],JSON.stringify(r));
  assert.equal(verify().status,1,'missing, duplicate, failed, interrupted or stale evidence must fail');
  fs.writeFileSync(reports[0],originals[0]);
 }
 fs.unlinkSync(reports[1]);assert.equal(verify().status,1,'missing shard fails');fs.writeFileSync(reports[1],originals[1]);
 for(const args of [['desktop','--shard=0/2'],['desktop','--shard=3/2'],['desktop','--shard=1/0'],['unit','--shard=1/2'],['desktop','--shard=1/2','unexpected']]){
  const r=run(args);assert.equal(r.status,1);assert.doesNotMatch(r.stdout,/EXECUTED/);
 }
 console.log('DESKTOP_SHARDS_PASS: exact partition, complete receipts, current CI identity, fail closed');
}finally{fs.rmSync(shards,{recursive:true,force:true});}
