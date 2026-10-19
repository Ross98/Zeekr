// Real CLI and isolated files: catches omitted scans, duplicate registrations,
// stale paths, invalid exclusions, and checks that validation precedes execution.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawnSync}=require('node:child_process');
const checker=path.resolve(__dirname,'../scripts/check-desktop-manifest.cjs');
let count=0;
function check(name,files,manifest,status,pattern){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'zeekr-manifest-'));
  try{
    for(const file of files){fs.mkdirSync(path.dirname(path.join(root,file)),{recursive:true});fs.writeFileSync(path.join(root,file),'throw new Error("must never execute fixture");\n');}
    fs.writeFileSync(path.join(root,'manifest.json'),JSON.stringify(manifest));
    const run=spawnSync(process.execPath,[checker,root,path.join(root,'manifest.json')],{encoding:'utf8'});
    assert.equal(run.status,status,`${name}: ${run.stdout}${run.stderr}`);
    assert.match(run.stdout+run.stderr,pattern,name);count++;
  }finally{fs.rmSync(root,{recursive:true,force:true});}
}
const base=()=>({groups:{unit:['tests/a.cjs'],smoke:[],review:[]},exclusions:[]});
check('new nested file cannot disappear from inventory',['tests/a.cjs','tests/nested/new.cjs'],base(),1,/unclassified.*tests\/nested\/new.cjs/);
check('same-group duplicate',['tests/a.cjs'],{...base(),groups:{unit:['tests/a.cjs','tests/a.cjs'],smoke:[],review:[]}},1,/duplicate.*tests\/a.cjs/);
check('cross-group duplicate',['tests/a.cjs'],{...base(),groups:{unit:['tests/a.cjs'],smoke:['tests/a.cjs'],review:[]}},1,/duplicate.*tests\/a.cjs/);
check('missing listed path',['tests/a.cjs'],{...base(),groups:{unit:['tests/a.cjs','tests/typo.cjs'],smoke:[],review:[]}},1,/missing.*tests\/typo.cjs/);
check('reasoned exclusion passes without executing',['tests/a.cjs','tests/old.cjs'],{...base(),exclusions:[{path:'tests/old.cjs',reason:'Legacy mobile viewports need desktop migration.'}]},0,/2 files classified/);
check('blank exclusion fails',['tests/a.cjs','tests/old.cjs'],{...base(),exclusions:[{path:'tests/old.cjs',reason:'  '}]},1,/reason.*tests\/old.cjs/);
check('excluded missing path',['tests/a.cjs'],{...base(),exclusions:[{path:'tests/deleted.cjs',reason:'Retired'}]},1,/missing.*tests\/deleted.cjs/);
check('executed and excluded overlap',['tests/a.cjs'],{...base(),exclusions:[{path:'tests/a.cjs',reason:'Already runs'}]},1,/duplicate.*tests\/a.cjs/);
check('duplicate exclusions',['tests/a.cjs','tests/old.cjs'],{...base(),exclusions:[{path:'tests/old.cjs',reason:'Legacy'},{path:'tests/old.cjs',reason:'Legacy again'}]},1,/duplicate.*tests\/old.cjs/);
check('directory exemption rejected',['tests/a.cjs','tests/old.cjs'],{...base(),exclusions:[{path:'tests/',reason:'Legacy'}]},1,/invalid path/);
check('path alias rejected',['tests/a.cjs'],{...base(),groups:{unit:['tests/../tests/a.cjs'],smoke:[],review:[]}},1,/invalid path/);
check('unknown groups rejected',['tests/a.cjs'],{...base(),groups:{...base().groups,typo:[]}},1,/groups/);
check('malformed exclusions rejected',['tests/a.cjs'],{...base(),exclusions:{}},1,/exclusions/);
check('non-CJS files outside scope',['tests/a.cjs','tests/test_backend.py'],base(),0,/1 files classified/);
// Exercise runner in an isolated project; successful files record actual order/env.
const project=fs.mkdtempSync(path.join(os.tmpdir(),'zeekr-manifest-runner-'));
try{
  fs.mkdirSync(path.join(project,'scripts'));fs.mkdirSync(path.join(project,'tests'));
  for(const name of ['test-desktop.cjs','check-desktop-manifest.cjs'])fs.copyFileSync(path.resolve(__dirname,'../scripts',name),path.join(project,'scripts',name));
  const manifest={groups:{unit:[],smoke:['tests/smoke.cjs'],review:['tests/review.cjs']},exclusions:[]};
  for(const name of ['smoke','review'])fs.writeFileSync(path.join(project,'tests',`${name}.cjs`),`console.log('EXECUTED_${name} '+process.env.DESKTOP_ONLY);`);
  const target=path.join(project,'scripts/desktop-test-manifest.json');
  fs.writeFileSync(target,JSON.stringify(manifest));
  const run=group=>spawnSync(process.execPath,[path.join(project,'scripts/test-desktop.cjs'),group],{encoding:'utf8'});
  let result=run('desktop');assert.equal(result.status,0,result.stderr);
  assert.deepEqual(result.stdout.match(/EXECUTED_\w+ 1/g),['EXECUTED_smoke 1','EXECUTED_review 1']);count++;
  fs.writeFileSync(path.join(project,'tests/new.cjs'),'throw new Error("must not run");');
  for(const group of ['unit','smoke','review','desktop','syntax']){
    result=run(group);assert.equal(result.status,1);assert.match(result.stderr,/unclassified.*tests\/new.cjs/);
    assert.doesNotMatch(result.stdout,/EXECUTED_/);count++;
  }
}finally{fs.rmSync(project,{recursive:true,force:true});}
console.log(`DESKTOP_MANIFEST_TEST_PASS: ${count} isolated CLI cases; fixtures removed`);
