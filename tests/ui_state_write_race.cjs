// Delayed loopback responses must not overwrite completed settings changes.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
function gate(){let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};}
async function started(hold){
 let timer;try{await Promise.race([hold.started.promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('request did not reach controlled gate')),5000);})]);}
 finally{clearTimeout(timer);}
}
(async()=>{
 const f=await fixture({initialResearch:false}),{page}=f;
 const held=[];let nextRead=null,nextWrite=null,reads=0;
 const hold=error=>{const value={started:gate(),release:gate(),error};held.push(value);return value;};
 try{
  await page.waitForFunction(()=>state?.request_key&&!busy&&!polling);
  await page.route('**/api/state',async route=>{
   reads++;const response=await route.fetch(),data=await response.json(),current=nextRead;nextRead=null;
   if(current){current.started.resolve();await current.release.promise;if(current.error)return route.fulfill({status:503,json:{error:'合成延迟读取失败'}});}
   await route.fulfill({response,json:data});
  });
  await page.route('**/api/recording',async route=>{
   const response=await route.fetch(),data=await response.json(),current=nextWrite;nextWrite=null;
   if(current){current.started.resolve();await current.release.promise;}
   await route.fulfill({response,json:data});
  });
  await page.getByRole('button',{name:'设置',exact:true}).first().click();
  await page.getByRole('button',{name:'暂停采集',exact:true}).click();
  await page.waitForFunction(()=>!busy&&!polling);
  for(const [error,interval] of [[false,10],[true,25]]){
   const current=hold(error);nextRead=current;
   await page.evaluate(()=>{void pollState(true);});await started(current);
   await page.locator('#interval').fill(String(interval));
   await page.getByRole('button',{name:'保存间隔',exact:true}).click();
   await page.waitForFunction(()=>!busy);
   assert.equal(await page.evaluate(()=>state.recording.interval),interval);
   current.release.resolve();await page.waitForFunction(()=>!polling);
   assert.equal(await page.evaluate(()=>state.recording.interval),interval,'late pre-write state cannot undo the successful update');
   assert.equal(await page.evaluate(()=>connectionFailures),0,'obsolete read failures cannot mark the current connection failed');
  }
  const identity=await page.evaluate(()=>state.request_key);
  const changed=await page.request.post(f.origin+'/api/recording',{headers:{Origin:f.origin,'X-Request-Key':identity},data:{operation:'interval',interval:20}});
  assert.equal(changed.status(),200);
  await page.evaluate(()=>pollState(true));
  assert.equal(await page.evaluate(()=>state.recording.interval),20,'fresh later reads still accept external updates');

  const writing=hold(false);nextWrite=writing;
  await page.evaluate(()=>{window.__settingsChange=api('/api/recording',{operation:'interval',interval:30}).then(result=>{state=result;render();});});
  await started(writing);const before=reads;
  try{
   await page.evaluate(()=>pollState(true));
   assert.equal(reads,before,'polling does not start during a write without the global busy flag');
  }finally{writing.release.resolve();}
  await page.evaluate(()=>window.__settingsChange);
  await page.evaluate(()=>pollState(true));assert.equal(reads,before+1);
  assert.equal(await page.evaluate(()=>state.recording.interval),30);
  const message=await page.evaluate(()=>api('/api/recording',{active:'invalid'}).catch(error=>error.message));
  assert.match(message,/布尔/);
  const after=reads;await page.evaluate(()=>pollState(true));
  assert.equal(reads,after+1,'failed writes release the polling guard too');
  for(const [error,interval] of [[false,40],[true,45]]){
   const current=hold(error);nextRead=current;
   await page.evaluate(()=>{void pollState(true);});await started(current);
   const changed=await page.request.post(f.origin+'/api/recording',{headers:{Origin:f.origin,'X-Request-Key':identity},data:{operation:'interval',interval}});
   assert.equal(changed.status(),200);
   const before=reads;
   try{
    await page.evaluate(()=>{
     window.__forceResolved=false;
     window.__forcedReads=Promise.all([pollState(true),pollState(true)]).then(()=>{window.__forceResolved=true;});
    });
    assert.equal(await page.evaluate(()=>window.__forceResolved),false,'forced reads must await a fresh follow-up instead of returning early');
   }finally{current.release.resolve();}
   await page.evaluate(()=>window.__forcedReads);
   assert.equal(reads,before+1,'overlapping forced callers share exactly one follow-up read');
   assert.equal(await page.evaluate(()=>state.recording.interval),interval);
   assert.equal(await page.evaluate(()=>connectionFailures),0);
  }
  const bodyErrors=await page.evaluate(async()=>{
   const original=window.fetch;
   window.fetch=(url,options)=>{
    if(!String(url).includes('syntheticBody=1'))return original(url,options);
    if(String(url).includes('invalid-json'))return Promise.resolve(new Response('broken JSON',{status:200}));
    const body=new ReadableStream({start(controller){
     controller.enqueue(new TextEncoder().encode('{"waiting":'));
     options.signal.addEventListener('abort',()=>controller.error(new DOMException('Body read aborted','AbortError')),{once:true});
    }});
    return Promise.resolve(new Response(body,{status:200,headers:{'Content-Type':'application/json'}}));
   };
   try{
    const timeout=await api('/api/synthetic-body?syntheticBody=1',undefined,100).catch(error=>error.message);
    const write=await api('/api/synthetic-body?syntheticBody=1',{},100).catch(error=>error.message);
    const signal=new AbortController(),timer=setTimeout(()=>signal.abort(),20);
    let cancelled;
    try{cancelled=await api('/api/timeline?syntheticBody=1',undefined,5000,{signal:signal.signal}).catch(error=>error.message);}
    finally{clearTimeout(timer);}
    const invalid=await api('/api/invalid-json?syntheticBody=1').catch(error=>error.message);
    return {timeout,write,cancelled,invalid,pending:stateChangesPending};
   }finally{window.fetch=original;}
  });
  assert.deepEqual(bodyErrors,{timeout:'本机服务响应超时，请稍后重试。',write:'本机服务响应超时，请稍后重试。',
   cancelled:'分析已取消。',invalid:'本机服务响应无效，请重试。',pending:0},'body-read aborts retain timeout/cancellation reason and release write guards');
  const shapes=await page.evaluate(async()=>{
   const original=window.fetch,results=[];
   let reply=null,status=200;
   window.fetch=(url,options)=>String(url).includes('synthetic-shape')||['/api/state','/api/refresh'].includes(String(url))
    ?Promise.resolve(new Response(JSON.stringify(reply),{status,headers:{'Content-Type':'application/json'}})):original(url,options);
   try{
    for(reply of [null,[],42,'wrong'])results.push(await api('/api/synthetic-shape').then(()=>null,error=>error.message));
    status=500;
    for(reply of [null,{error:{private:'wrong'}},{error:'合成服务错误'}])results.push(await api('/api/synthetic-shape').then(()=>null,error=>error.message));
    status=200;
    const previous=state;state.next_query_at=null;
    for(reply of [null,[],{}, {request_key:'incomplete',recording:{},monitoring:{}},
                 {...previous,model:{}},{...previous,recording:{}}]){
     await refresh();
     results.push({retained:state===previous,pending:stateChangesPending,busy,error:transientError});
    }
    return results;
   }finally{window.fetch=original;}
  });
  assert.deepEqual(shapes,[...Array(5).fill('本机服务响应无效，请重试。'),'请求失败，请稍后重试。','合成服务错误',
   ...Array.from({length:6},()=>({retained:true,pending:0,busy:false,error:'本机服务响应无效，请重试。'}))],
   'invalid response shapes cannot replace the current state or leak a JavaScript TypeError');
  const clocks=await page.evaluate(async()=>{
   const results=[],originalFetch=window.fetch,originalDate=Date.now,ownPerformance=Object.getOwnPropertyDescriptor(performance,'now');
   try{
    for(const expire of [false,true]){
     let wall=originalDate(),elapsed=100,requests=0,cancellations=0;
     Date.now=()=>wall;Object.defineProperty(performance,'now',{configurable:true,value:()=>elapsed});
     const ticket='/api/analysis/'+'a'.repeat(32);
     window.fetch=(url,options)=>{
      if(String(url)===ticket+'/cancel'){cancellations++;return Promise.resolve(new Response('{}'));}
      if(!String(url).includes('syntheticClock=1')&&String(url)!==ticket)return originalFetch(url,options);
      requests++;
      if(requests===1){
       wall+=expire?-3600000:3600000;elapsed+=expire?600001:1;
       return Promise.resolve(new Response(JSON.stringify({analysis_job_url:ticket,retry_after_ms:50}),{status:202}));
      }
      return Promise.resolve(new Response('{"done":true}'));
     };
     const result=await api('/api/timeline?syntheticClock=1',undefined,5000).then(value=>value.done?'ok':'unexpected',error=>error.message);
     results.push({expire,result,requests,cancellations});
    }
    return results;
   }finally{
    window.fetch=originalFetch;Date.now=originalDate;
    if(ownPerformance)Object.defineProperty(performance,'now',ownPerformance);else delete performance.now;
   }
  });
  assert.deepEqual(clocks,[{expire:false,result:'ok',requests:2,cancellations:0},
   {expire:true,result:'分析等待超过 10 分钟，请稍后重试。',requests:1,cancellations:1}],
   'analysis lifetime follows elapsed time even when the system clock moves');
  assert.deepEqual(f.errors,[]);assert.deepEqual(f.external,[]);
  console.log('DESKTOP_STATE_WRITE_RACE_PASS: late success/failure, external updates, pending and failed writes');
 }catch(error){await f.fail(error);throw error;}
 finally{for(const current of held)current.release.resolve();await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
