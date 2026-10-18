// Exercise the benchmark's CLI contract with a fresh, nested output path.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawnSync}=require('node:child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'zeekr-benchmark-cli-'));
try{
  const output=path.join(root,'new','nested','result.json');
  const result=spawnSync(process.execPath,[path.join(__dirname,'benchmark_overview.cjs'),output],{
    cwd:root,env:{...process.env,DESKTOP_ONLY:'1'},encoding:'utf8',timeout:60000
  });
  assert.ifError(result.error);
  assert.equal(result.status,0,result.stderr||result.stdout);
  assert.deepEqual(JSON.parse(fs.readFileSync(output,'utf8')),JSON.parse(result.stdout));
  console.log('OVERVIEW_BENCHMARK_CLI_PASS: fresh nested output, independent cwd, strict benchmark checks');
}finally{fs.rmSync(root,{recursive:true,force:true});}
