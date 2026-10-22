#!/usr/bin/env node
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const manifestPath=path.join(__dirname,'desktop-test-manifest.json');
// Scope is intentionally code-owned: a manifest cannot narrow its own inventory.
function inventory(directory,prefix='tests'){
  return fs.readdirSync(directory,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name)).flatMap(entry=>{
    const file=`${prefix}/${entry.name}`;
    if(entry.isSymbolicLink())throw new Error(`unsupported symlink: ${file}`);
    if(entry.isDirectory())return inventory(path.join(directory,entry.name),file);
    return entry.isFile()&&entry.name.endsWith('.cjs')?[file]:[];
  });
}
function validate(rootDirectory,manifest){
  const files=inventory(path.join(rootDirectory,'tests')),known=new Set(files),seen=new Map(),errors=[];
  if(!manifest||typeof manifest.groups!=='object'||!manifest.groups||Array.isArray(manifest.groups)||
    Object.keys(manifest.groups).sort().join(',')!=='review,smoke,unit')throw new Error('groups must contain exactly unit, smoke, review');
  if(!Array.isArray(manifest.exclusions))throw new Error('exclusions must be an array');
  function register(file,owner){
    if(typeof file!=='string'||!/^tests\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+\.cjs$/.test(file)){
      errors.push(`invalid path: ${String(file)}`);return;
    }
    if(seen.has(file))errors.push(`duplicate: ${file} (${seen.get(file)}, ${owner})`);
    seen.set(file,owner);
    if(!known.has(file))errors.push(`missing: ${file}`);
  }
  for(const [group,entries] of Object.entries(manifest.groups)){
    if(!Array.isArray(entries))throw new Error(`groups.${group} must be an array`);
    for(const file of entries)register(file,group);
  }
  for(const exclusion of manifest.exclusions){
    if(!exclusion||typeof exclusion!=='object')throw new Error('exclusions entries must contain path and reason');
    register(exclusion.path,'exclusion');
    if(typeof exclusion.reason!=='string'||!exclusion.reason.trim())errors.push(`reason required: ${exclusion.path}`);
    if(!['helper','benchmark','manual-artifact','retired-mobile','coverage-debt'].includes(exclusion.kind))errors.push(`kind required: ${exclusion.path}`);
    if(typeof exclusion.review_when!=='string'||!exclusion.review_when.trim())errors.push(`review_when required: ${exclusion.path}`);
  }
  for(const file of files)if(!seen.has(file))errors.push(`unclassified: ${file}`);
  if(errors.length)throw new Error(errors.join('\n'));
  return {files:files.length,executed:files.length-manifest.exclusions.length,excluded:manifest.exclusions.length};
}
function loadAndValidate(rootDirectory=root,file=manifestPath){
  const manifest=JSON.parse(fs.readFileSync(file,'utf8'));
  const summary=validate(rootDirectory,manifest);
  return {manifest,summary};
}
if(require.main===module){
  try{
    const {summary}=loadAndValidate(process.argv[2]||root,process.argv[3]||manifestPath);
    console.log(`${summary.files} files classified: ${summary.executed} executable, ${summary.excluded} excluded with reasons; tests/**/*.cjs`);
  }catch(error){console.error(error.message);process.exitCode=1;}
}
module.exports={loadAndValidate};
