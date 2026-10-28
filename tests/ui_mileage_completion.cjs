// Desktop, synthetic local records only; no vehicle calls or notification sends.
const {chromium}=require('playwright'),{spawn}=require('node:child_process');
const assert=require('node:assert/strict'),path=require('node:path');
const {startEvidence}=require('../scripts/browser-failure-evidence.cjs');
(async()=>{let browser,evidence;const server=spawn('python3',[path.join(__dirname,'recall_fixture.py'),'--mileage-gap']);try{
 const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture timeout')),30000);server.stdout.once('data',d=>{clearTimeout(timer);resolve(Number(String(d).trim()));});server.stderr.on('data',d=>process.stderr.write(d));server.once('exit',code=>reject(Error('fixture exited '+code)));});
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});const page=await browser.newPage({viewport:{width:1440,height:1080}});page.setDefaultTimeout(12000);
 evidence=await startEvidence(page,{testId:'ui_mileage_completion',synthetic:true});const errors=[],tracks=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(new URL(r.url()).pathname==='/api/tracks')tracks.push(r.url());});
 const origin='http://127.0.0.1:'+port;await page.goto(origin);
 await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();await page.getByLabel('轨迹日期').fill('2026-09-20');await page.getByRole('button',{name:'查询行程',exact:true}).click();
 await page.getByRole('button',{name:'核对并补全',exact:true}).click();
 assert.equal(await page.getByLabel('出发时间（北京时间）',{exact:true}).inputValue(),'','Do not invent a start time');
 await page.getByLabel('出发时间（北京时间）',{exact:true}).fill('2026-09-20T07:00');await page.getByLabel('到达时间（北京时间）',{exact:true}).fill('2026-09-20T07:30');
 await page.getByLabel('出发地点',{exact:true}).fill('合成住所 <b>标签</b>');await page.getByLabel('到达地点',{exact:true}).fill('合成公司');
 await page.getByRole('button',{name:'核对并补全',exact:true}).click();assert.equal(await page.getByLabel('到达地点',{exact:true}).inputValue(),'合成公司','Reopening retains unsaved input');
 await page.getByRole('button',{name:'预览补全',exact:true}).click();await page.getByRole('button',{name:'确认并计入行程',exact:true}).waitFor();
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);for(const width of [1024,1280,1440]){await page.setViewportSize({width,height:1080});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);}}
 await page.locator('.mileage-workspace').screenshot({path:'/private/tmp/zeekr-mileage-completion-preview.png'});
 await page.evaluate(()=>{const button=document.querySelector('[data-mileage-confirm]');button.click();button.click();});
 await page.waitForFunction(()=>document.querySelector('#mileage-gap-workspace')?.textContent.includes('已手动补全')&&!document.querySelector('#mileage-completion-form'));
 let timeline=await(await page.request.get(origin+'/api/timeline?date=2026-09-20')).json();
 const manual=timeline.records.filter(r=>r.record_source==='manual_completion');assert.equal(manual.length,1);assert.equal(manual[0].distance_km,26);assert.equal(manual[0].start_place.label,'合成住所 <b>标签</b>');assert.equal(manual[0]._position,undefined);
 assert.equal(timeline.summary.distance_km,53);assert.equal(timeline.summary.trip_count,3);assert.equal(timeline.summary.pending_mileage_km,null);assert.equal(timeline.mileage_gaps[0].odometer_before,200);
 const id=manual[0].id;await page.locator('[data-local-trip="'+id+'"]').click();assert.match(await page.locator('#local-trip-facts').innerText(),/手动补全/);
 assert.equal(await page.locator('#local-trip-facts b').filter({hasText:'标签'}).count(),0,'Place text must be escaped');
 await page.getByRole('button',{name:'查看／调整补全',exact:true}).first().click();assert.equal(await page.getByLabel('出发时间（北京时间）',{exact:true}).inputValue(),'2026-09-20T07:00');
 await page.getByLabel('到达时间（北京时间）',{exact:true}).fill('2026-09-20T07:40');await page.getByRole('button',{name:'预览补全',exact:true}).click();await page.getByRole('button',{name:'确认并计入行程',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#mileage-completion-form'));
 timeline=await(await page.request.get(origin+'/api/timeline?date=2026-09-20')).json();assert.equal(timeline.summary.distance_km,53);assert.equal(timeline.summary.trip_count,3);assert.equal(timeline.records.filter(r=>r.id===id).length,1);
 await page.getByRole('button',{name:'查看／调整补全',exact:true}).first().click();await page.getByLabel('出发时间（北京时间）',{exact:true}).fill('2026-09-20T08:00');await page.getByLabel('到达时间（北京时间）',{exact:true}).fill('2026-09-20T08:10');await page.getByRole('button',{name:'预览补全',exact:true}).click();await page.getByRole('button',{name:'确认并计入行程',exact:true}).click();
 await page.getByText(/时间与已有行程重叠/).waitFor();assert.equal(await page.getByLabel('出发时间（北京时间）',{exact:true}).inputValue(),'2026-09-20T08:00','Failed write retains draft');
 const stale=await page.evaluate(async()=>{const response=await fetch('/api/mileage-gaps/complete',{method:'POST',headers:{'Content-Type':'application/json','X-Request-Key':state.request_key},body:JSON.stringify({context:'stale-context'})});return response.status;});assert.equal(stale,409);
 assert.equal(tracks.length,0,'Completion never loads GPS');assert.deepEqual(errors,[]);
 console.log('MILEAGE_COMPLETION_DESKTOP_PASS: preview, manual source, immutable evidence, no double count, edit, overlap rejection, stale context, six desktop layouts and no GPS requests');
 }catch(error){if(evidence)await evidence.fail(error);throw error;}finally{if(evidence)await evidence.finish();if(browser)await browser.close();server.kill();}})().catch(e=>{console.error(e);process.exit(1);});
