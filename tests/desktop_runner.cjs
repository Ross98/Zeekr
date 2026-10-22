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
 console.log('DESKTOP_RUNNER_PASS: continue after failure, truthful summary, bounded timeout, descendant cleanup');
}finally{
 const file=path.join(root,'descendant.pid');if(fs.existsSync(file)){try{process.kill(Number(fs.readFileSync(file,'utf8')),'SIGKILL');}catch(error){if(error.code!=='ESRCH')throw error;}}
 fs.rmSync(root,{recursive:true,force:true});
}
