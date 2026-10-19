#!/usr/bin/env node
// Explicit manifests prevent older mixed mobile suites entering desktop checks.
const {spawnSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const {loadAndValidate}=require('./check-desktop-manifest.cjs');
let groups;
try{({manifest:{groups}}=loadAndValidate());}
catch(error){console.error(error.message);process.exit(1);}
const group=process.argv[2]||'review';
if(group==='desktop')groups.desktop=[...groups.smoke,...groups.review];
const syntax=group==='syntax';
const files=syntax?fs.readdirSync(path.join(root,'zeekr_control/static'))
  .filter(name=>name.endsWith('.js')).map(name=>path.join('zeekr_control/static',name))
  :Object.hasOwn(groups,group)?groups[group]:undefined;
if(!files){console.error('Choose unit, smoke, review, desktop or syntax.');process.exit(2);}
const started=Date.now();
for(const file of files){
  console.log(`\n[${group}] ${file}`);
  const result=spawnSync(process.execPath,[...(syntax?['--check']:[]),file],{
    cwd:root,env:{...process.env,DESKTOP_ONLY:'1',PYTHONDONTWRITEBYTECODE:'1'},stdio:'inherit'
  });
  if(result.error||result.status!==0){
    if(result.error)console.error(result.error.message);
    process.exit(result.status||1);
  }
}
console.log(`\n${files.length} ${group} files passed in ${((Date.now()-started)/1000).toFixed(1)}s; desktop only.`);
