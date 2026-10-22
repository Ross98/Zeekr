#!/usr/bin/env node
// One manifest, bounded independent children, truthful aggregate result.
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const {loadAndValidate}=require('./check-desktop-manifest.cjs');
function syntaxFiles(directory){
 return fs.readdirSync(directory,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name)).flatMap(entry=>{
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
async function main(){
 const {manifest:{groups}}=loadAndValidate();
 groups.desktop=[...groups.smoke,...groups.review];groups.all=[...groups.unit,...groups.desktop];
 const group=process.argv[2]||'all',syntax=group==='syntax';
 const files=syntax?['zeekr_control/static','scripts','tests'].flatMap(d=>syntaxFiles(path.join(root,d))):groups[group];
 if(!files)throw Error('Choose all, unit, smoke, review, desktop or syntax.');
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
 fs.writeFileSync(path.join(directory,`${group}-${process.pid}.json`),JSON.stringify({schema:1,group,passed,interrupted,seconds:(Date.now()-started)/1000,results},null,2)+'\n');
 console.log(`\n${results.filter(r=>r.status==='passed').length}/${files.length} ${group} files passed in ${((Date.now()-started)/1000).toFixed(1)}s; desktop only.`);
 process.exitCode=passed?0:1;
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
