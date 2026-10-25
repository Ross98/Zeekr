#!/usr/bin/env node
// One manifest, bounded independent children, truthful aggregate result.
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const {loadAndValidate}=require('./check-desktop-manifest.cjs');
function syntaxFiles(directory){
 return fs.readdirSync(directory,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name)).flatMap(entry=>{
  // AppleDouble is filesystem metadata, never an executable script.
  if(entry.name.startsWith('._'))return [];
  const file=path.join(directory,entry.name);
  if(entry.isSymbolicLink())throw Error('Unsupported syntax input symlink');
  return entry.isDirectory()?syntaxFiles(file):/\.(?:js|cjs)$/.test(entry.name)?[path.relative(root,file)]:[];
 });
}
function killGroup(child,signal){
 if(!child.pid)return;
 try{if(process.platform==='win32')child.kill(signal);else process.kill(-child.pid,signal);}catch(error){if(error.code!=='ESRCH')throw error;}
}
function trackTree(child,signal){
 if(!child.pid)return;
 try{
  const rows=execFileSync('ps',['-axo','uid=,pid=,ppid=,lstart='],{encoding:'utf8',timeout:2000,maxBuffer:4*1024*1024}).split('\n').flatMap(line=>{
   const match=line.match(/^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.+)$/);
   return match&&Number(match[1])===process.getuid()?[{pid:Number(match[2]),parent:Number(match[3]),birth:match[4]}]:[];
  });
  const group=new Set([child.pid]);let changed=true;
  while(changed){changed=false;for(const row of rows)if(group.has(row.parent)&&!group.has(row.pid)){group.add(row.pid);changed=true;}}
  child.owned??=new Map();for(const row of rows)if(group.has(row.pid))child.owned.set(row.pid,row.birth);
  // Browsers can create a new process group. Track ancestry too, and recheck
  // UID + creation time before signalling any remembered detached descendant.
  if(signal)for(const row of rows)if(row.pid!==child.pid&&child.owned.get(row.pid)===row.birth){try{process.kill(row.pid,signal);}catch(error){if(error.code!=='ESRCH')throw error;}}
 }catch{child.cleanupError=true;}
 if(signal)killGroup(child,signal);
}
function partition(files,shard){
 return shard?files.filter((_,i)=>i%shard.total===shard.index-1):files;
}
function ciIdentity(){
 const value={sha:process.env.GITHUB_SHA||null,run_id:process.env.GITHUB_RUN_ID||null,run_attempt:process.env.GITHUB_RUN_ATTEMPT||null};
 if(Object.values(value).some(v=>v!==null)&&(!/^[a-f0-9]{40}$/.test(value.sha||'')||!/^\d+$/.test(value.run_id||'')||!/^\d+$/.test(value.run_attempt||'')||Number(value.run_id)<1||Number(value.run_attempt)<1))throw Error('Invalid CI identity');
 return value;
}
function verifyShards(files,directory,total){
 if(!/^[1-9]\d*$/.test(total||'')||Number(total)>64||Number(total)>files.length)throw Error('Invalid shard total');
 total=Number(total);const identity=ciIdentity();
 const reports=fs.readdirSync(directory).filter(name=>/^desktop-shard-.*\.json$/.test(name));
 if(reports.length!==total)throw Error('Missing or duplicate desktop shard receipts');
 const seen=new Set();
 for(const file of reports){
  const r=JSON.parse(fs.readFileSync(path.join(directory,file),'utf8')),shard=r.shard;
  if(r.schema!==1||r.group!=='desktop'||r.passed!==true||r.interrupted!==false||!shard||shard.total!==total||!Number.isInteger(shard.index)||shard.index<1||shard.index>total||seen.has(shard.index)||!r.ci||Object.keys(identity).some(k=>r.ci[k]!==identity[k]))throw Error('Invalid, failed or stale desktop shard receipt');
  const expected=partition(files,shard);
  if(!Array.isArray(r.results)||r.results.length!==expected.length||r.results.some((row,i)=>row.file!==expected[i]||row.status!=='passed'||row.exit_code!==0||row.signal!==null))throw Error('Incomplete or unsuccessful desktop shard coverage');
  seen.add(shard.index);
 }
 console.log(`DESKTOP_SHARDS_VERIFIED: ${files.length} files exactly once across ${total} shards; current CI identity.`);
}
async function main(){
 const {manifest:{groups}}=loadAndValidate();
 groups.desktop=[...groups.smoke,...groups.review];groups.all=[...groups.unit,...groups.desktop];
 const group=process.argv[2]||'all',syntax=group==='syntax';
 if(group==='verify-shards'){
  if(process.argv.length!==5)throw Error('Expected verify-shards directory total');
  return verifyShards(groups.desktop,process.argv[3],process.argv[4]);
 }
 let shard=null;
 if(process.argv.length>3){
  const match=process.argv[3].match(/^--shard=([1-9]\d*)\/([1-9]\d*)$/);
  if(group!=='desktop'||process.argv.length!==4||!match||Number(match[1])>Number(match[2])||Number(match[2])>64||Number(match[2])>groups.desktop.length)throw Error('Invalid desktop shard');
  shard={index:Number(match[1]),total:Number(match[2])};
 }
 const identity=ciIdentity();
 const files=syntax?['zeekr_control/static','scripts','tests'].flatMap(d=>syntaxFiles(path.join(root,d))):partition(groups[group]||[],shard);
 if(!syntax&&!groups[group])throw Error('Choose all, unit, smoke, review, desktop or syntax.');
 const timeout=Number(process.env.DESKTOP_TEST_TIMEOUT_MS||180000);
 if(!Number.isInteger(timeout)||timeout<100||timeout>1200000)throw Error('Invalid DESKTOP_TEST_TIMEOUT_MS');
 const started=Date.now(),results=[];let interrupted=false,current,stopTimer;
 const childEnv={...process.env,DESKTOP_ONLY:'1',PYTHONDONTWRITEBYTECODE:'1'};
 // Old direct scripts may request system Chrome when the variable is absent.
 // Resolve the project-locked browser once for every normal runner invocation.
 if(!childEnv.CHROMIUM_EXECUTABLE){
  try{childEnv.CHROMIUM_EXECUTABLE=require('playwright').chromium.executablePath();}
  catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
 }
 const stop=()=>{interrupted=true;if(current){const child=current;trackTree(child,'SIGTERM');stopTimer=setTimeout(()=>trackTree(child,'SIGKILL'),500);}};
 process.on('SIGTERM',stop);process.on('SIGINT',stop);
 try{
  for(const file of files){
   if(interrupted){results.push({file,status:'not_run'});continue;}
   console.log(`\n[${group}] ${file}`);
   const start=Date.now();let timedOut=false;
   const child=spawn(process.execPath,[...(syntax?['--check']:[]),file],{cwd:root,
    env:childEnv,stdio:'inherit',detached:process.platform!=='win32'});
   current=child;
   trackTree(child);const tracker=setInterval(()=>trackTree(child),1000);
   const timer=setTimeout(()=>{timedOut=true;trackTree(child,'SIGTERM');},timeout);
   const hard=setTimeout(()=>trackTree(child,'SIGKILL'),timeout+500);
   const outcome=await new Promise(resolve=>{child.once('error',()=>resolve({error:true}));child.once('exit',(code,signal)=>resolve({code,signal}));});
   clearTimeout(timer);clearTimeout(hard);clearTimeout(stopTimer);clearInterval(tracker);
   // Every spawned child owns a fresh process group. Stop orphaned fixture /
   // browser children even if a test forgot cleanup or exited on a signal.
   trackTree(child,'SIGTERM');await new Promise(resolve=>setTimeout(resolve,100));trackTree(child,'SIGKILL');current=null;
   const status=timedOut?'timeout':outcome.code===0&&!child.cleanupError?'passed':'failed';
   results.push({file,status,exit_code:outcome.code??null,signal:outcome.signal??null,seconds:(Date.now()-start)/1000});
   if(status!=='passed')console.error(`${file}: ${status}`);
  }
 }finally{process.off('SIGTERM',stop);process.off('SIGINT',stop);if(current)trackTree(current,'SIGKILL');}
 const passed=!interrupted&&results.every(r=>r.status==='passed');
 const directory=path.resolve(root,process.env.DESKTOP_RESULT_DIR||'test-results/desktop');fs.mkdirSync(directory,{recursive:true});
 fs.writeFileSync(path.join(directory,`${group}${shard?`-shard-${shard.index}-of-${shard.total}`:''}-${process.pid}.json`),JSON.stringify({schema:1,group,shard,ci:identity,passed,interrupted,seconds:(Date.now()-started)/1000,results},null,2)+'\n');
 console.log(`\n${results.filter(r=>r.status==='passed').length}/${files.length} ${group} files passed in ${((Date.now()-started)/1000).toFixed(1)}s; desktop only.`);
 process.exitCode=passed?0:1;
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
