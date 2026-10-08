// Real local APIs, synthetic saved evidence. No vehicle gateway.
const {chromium}=require('playwright'),{spawn}=require('node:child_process');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {contrast}=require('./ui_insight_helpers.cjs');
(async()=>{
 const server=spawn('python3',[path.join(__dirname,'recall_fixture.py'),...(process.env.RECALL_PERFORMANCE?['--performance']:[])]);let browser;
 try{
 const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture timeout')),30000);server.stdout.once('data',d=>{clearTimeout(timer);resolve(Number(String(d).trim()));});server.stderr.on('data',d=>process.stderr.write(d));server.once('exit',code=>reject(Error('fixture exited '+code)));});
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});const page=await browser.newPage({viewport:{width:1440,height:1080}});page.setDefaultTimeout(10000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://wprd0*.is.autonavi.com/**',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e5ece6"/><path d="M0 128H256M128 0V256" stroke="#fff" stroke-width="8"/></svg>'}));
 await page.goto('http://127.0.0.1:'+port);
 // Current overview shows location by default; exercise the user's hide action
 // before checking that summaries retain the explicitly hidden state.
 await page.getByRole('button',{name:'隐藏位置',exact:true}).click();
 await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();await page.getByLabel('轨迹日期').fill('2026-09-20');await page.getByRole('button',{name:'查询行程',exact:true}).click();
 await page.locator('[data-local-trip="recall-charge"]').waitFor();assert.match(await page.locator('#recall-summary').innerText(),/27 km/);
 assert.ok(await page.locator('[data-local-trip^="parking_"]').count());assert.equal(await page.locator('#map').count(),0);
 const hidden=await page.evaluate(()=>localTrips.events);assert.ok(hidden.every(r=>!r.position));
 await page.locator('[data-local-trip="recall-charge"]').focus();await page.keyboard.press('Enter');assert.equal(await page.evaluate(()=>localTrips.selection),'recall-charge');assert.match(await page.locator('#local-trip-facts').innerText(),/未知/);
 await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();await page.waitForFunction(()=>map&&localTrips.route?.count===1);
 await page.evaluate(()=>window.recallMap=map);
 await page.locator('[data-local-trip="recall-drive"]').click();await page.waitForFunction(()=>localTrips.route?.count>1);assert.equal(await page.evaluate(()=>window.recallMap===map&&map.getContainer()===document.querySelector('#map')),true);assert.ok(await page.locator('#map .leaflet-control-zoom').isVisible());
 await page.locator('[data-local-trip="recall-charge"]').click();await page.waitForFunction(()=>localTrips.route?.count===1);
 await page.locator('[data-recall-correct="end"]').click();await page.locator('#recall-name').fill('合成车库');await page.evaluate(()=>render());assert.equal(await page.locator('#recall-name').inputValue(),'合成车库');assert.equal(await page.evaluate(()=>document.activeElement.id),'recall-name');await page.getByRole('button',{name:'预览影响',exact:true}).click();await page.getByRole('button',{name:'保存修正',exact:true}).click();await page.waitForFunction(()=>localTrips.selected?.end_place?.label==='合成车库');
 await page.locator('[data-recall-history="end"]').click();await page.getByRole('heading',{name:/近 31 天/}).waitFor();
 await page.getByRole('button',{name:'撤销最近地点修正',exact:true}).click();await page.waitForFunction(()=>localTrips.timeline?.correction_revision===2);
 await page.locator('[data-recall-ledger]').click();await page.locator('#ledger-form').waitFor();assert.equal(await page.locator('#navigation [data-page=books]').getAttribute('aria-current'),'page');assert.equal(await page.locator('#ledger-event_id').inputValue(),'recall-charge');await page.locator('#ledger-amount').fill('12.34');await page.getByRole('button',{name:'保存账单',exact:true}).click();await page.getByText('账单已保存。',{exact:true}).waitFor();
 await page.getByRole('button',{name:'返回原充电记录',exact:true}).click();await page.waitForFunction(()=>localTrips.selection==='recall-charge');assert.match(await page.locator('#recall-summary').innerText(),/12.34 元/);
 await page.locator('.recall-year-panel>summary').click();await page.locator('#recall-year').fill('2026');await page.locator('[data-recall-year-load]').click();await page.locator('.recall-heat-day').first().waitFor();assert.equal(await page.locator('.recall-heat-day').count(),365);
 await page.locator('#recall-year-mode').selectOption('cost');assert.match(await page.locator('#recall-year-result').innerText(),/金额未知/);await page.reload();await page.locator('.recall-heat-day').first().waitFor();assert.equal(await page.locator('#recall-year-mode').inputValue(),'cost');await page.waitForFunction(()=>localTrips.selection==='recall-charge').catch(async e=>{console.error(await page.evaluate(()=>({url:location.search,selection:localTrips.selection,restore:localTrips.restoreSelection,queried:localTrips.queried,error:localTrips.listError})));throw e;});
 await page.locator('[data-recall-date="2026-09-19"]').first().click();await page.waitForFunction(()=>trackDate==='2026-09-19'&&localTrips.queried);await page.goBack();await page.waitForFunction(()=>trackDate==='2026-09-20'&&localTrips.selection==='recall-charge');
 const dir='/tmp/zeekr-recall-qa';fs.mkdirSync(dir,{recursive:true});
 for(const theme of ['light','dark']){await page.getByLabel('外观',{exact:true}).selectOption(theme);for(const width of (process.env.DESKTOP_ONLY?[1440,1280,1024]:[1440,390,320])){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),theme+width+' overflow');await contrast(page,'#local-trips');if(width!==320){await page.screenshot({path:`${dir}/recall-${theme}-${width}.png`,fullPage:true});}}}
 await page.setViewportSize({width:1440,height:1080});await page.getByLabel('外观',{exact:true}).selectOption('light');await page.locator('.recall-year-panel>summary').click();await page.locator('[data-local-trip="recall-drive"]').click();if(await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).isVisible())await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();await page.waitForFunction(()=>localTrips.route?.count>1);
 await page.locator('.local-observation-details>summary').click();await page.evaluate(()=>render());assert.equal(await page.locator('.local-observation-details').evaluate(el=>el.open),true);await page.locator('.local-observation-details>summary').click();
 await page.screenshot({path:dir+'/timeline-desktop-viewport.png'});await page.screenshot({path:dir+'/timeline-desktop.png',fullPage:true});if(!process.env.DESKTOP_ONLY){await page.setViewportSize({width:390,height:844});await page.screenshot({path:dir+'/timeline-mobile.png',fullPage:true});}
 await page.getByRole('button',{name:'隐藏位置',exact:true}).click();assert.equal(await page.locator('#map').count(),0);assert.ok((await page.evaluate(()=>localTrips.events)).every(r=>!r.position));
 await page.reload();await page.locator('[data-local-trip="recall-drive"]').waitFor();await page.waitForFunction(()=>localTrips.selection==='recall-drive');assert.equal(new URL(page.url()).searchParams.get('record'),'recall-drive');
 assert.deepEqual(errors,[]);console.log('Daily recall browser passed: timeline, consent, map reuse, correction, undo, history, ledger return, year, URL, responsive contrast.');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
