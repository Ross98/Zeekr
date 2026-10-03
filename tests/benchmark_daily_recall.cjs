// Fixed synthetic sizes and real local interfaces. Writes benchmark evidence only.
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),os=require('node:os');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
(async()=>{
 const server=spawn('python3',[path.join(__dirname,'recall_fixture.py'),'--performance']);let browser;
 try{
  const port=await new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error('fixture timeout')),60000);server.stdout.once('data',d=>{clearTimeout(t);resolve(Number(String(d).trim()));});server.stderr.on('data',d=>process.stderr.write(d));server.once('exit',c=>reject(Error('fixture exit '+c)));});
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});const page=await browser.newPage({viewport:{width:1440,height:1080}});
  await page.route('https://tile.openstreetmap.org/**',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e5ece6"/></svg>'}));
  await page.goto('http://127.0.0.1:'+port);await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();await page.getByLabel('轨迹日期').fill('2026-09-20');
  const data=await page.evaluate(async()=>{
    const measure=async url=>{const times=[];let bytes,result;for(let i=0;i<3;i++){const start=performance.now();const r=await fetch(url),text=await r.text();times.push(performance.now()-start);bytes=new TextEncoder().encode(text).length;result=JSON.parse(text);if(!r.ok)throw Error(text);}return {milliseconds:times,bytes,result};};
    const day=await measure('/api/timeline?date=2026-09-20');
    const reference=await measure('/api/timeline?date=2026-09-01');
    const p=reference.result.records.find(r=>r.type==='trip'&&r.id.startsWith('history-')).end_place;
    const history=await measure('/api/place-history?start=2026-08-21&end=2026-09-20&key='+p.key);
    const year=await measure('/api/year-review?year=2024');
    return {timeline:{milliseconds:day.milliseconds,bytes:day.bytes,records:day.result.records.length},history:{milliseconds:history.milliseconds,bytes:history.bytes,records:history.result.count,page_records:history.result.records.length,has_next_page:!!history.result.next_cursor},year:{milliseconds:year.milliseconds,bytes:year.bytes,days:year.result.days.length,trips:year.result.totals.trip_count}};
  });
  await page.getByRole('button',{name:'查询行程',exact:true}).click();await page.locator('[data-local-trip="recall-drive"]').waitFor();
  await page.evaluate(()=>{window.recallLongTasks=[];new PerformanceObserver(list=>recallLongTasks.push(...list.getEntries().map(e=>e.duration))).observe({type:'longtask',buffered:false});window.recallBenchStart=performance.now();});
  await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();await page.waitForFunction(()=>map&&localTrips.route?.count>4000);await page.waitForTimeout(100);
  data.map=await page.evaluate(()=>({elapsed_ms:performance.now()-recallBenchStart,observations:localTrips.route.count,long_tasks_ms:recallLongTasks,max_long_task_ms:Math.max(0,...recallLongTasks),connected:map.getContainer()===document.querySelector('#map')}));
  await page.evaluate(()=>{window.recallLongTasks=[];window.recallBenchStart=performance.now();});await page.locator('[data-local-trip="recall-charge"]').click();await page.waitForFunction(()=>localTrips.route?.count===1);await page.waitForTimeout(100);
  data.selection=await page.evaluate(()=>({elapsed_ms:performance.now()-recallBenchStart,long_tasks_ms:recallLongTasks,max_long_task_ms:Math.max(0,...recallLongTasks)}));
  data.environment={platform:os.platform(),arch:os.arch(),cpu:os.cpus()[0].model,browser:await browser.version(),viewport:'1440x1080',tiles:'local synthetic intercepted',sizes:'4000 dense points plus 181 minute samples; 120 extra daily trips; 366 yearly trips; 19 observed parking days; 60 place-history trips'};
  data.measured_at=new Date().toISOString();
  fs.mkdirSync('/tmp/zeekr-recall-qa',{recursive:true});fs.writeFileSync('/tmp/zeekr-recall-qa/performance.json',JSON.stringify(data,null,2));console.log(JSON.stringify(data,null,2));
  for(const key of ['timeline','history','year'])assert.ok(Math.max(...data[key].milliseconds)<2000,key+' <2s');assert.ok(data.map.elapsed_ms<2000,'map <2s');assert.ok(data.map.max_long_task_ms<=200,'map no >200ms task');assert.ok(data.selection.max_long_task_ms<=200,'selection no >200ms task');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
