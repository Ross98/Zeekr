// Desktop only, isolated local evidence; no vehicle network requests.
const {chromium}=require('playwright'),{spawn}=require('node:child_process');
const assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const server=spawn('python3',[path.join(__dirname,'recall_fixture.py')]);let browser;try{
 const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture timeout')),30000);server.stdout.once('data',d=>{clearTimeout(timer);resolve(Number(String(d).trim()));});server.stderr.on('data',d=>process.stderr.write(d));});
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
 const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[],routes=[];
 page.setDefaultTimeout(12000);page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(new URL(r.url()).pathname==='/api/tracks')routes.push(r.url());});
 await page.goto('http://127.0.0.1:'+port);
 await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();await page.getByLabel('轨迹日期').fill('2026-09-20');await page.getByRole('button',{name:'查询行程',exact:true}).click();
 await page.locator('#local-trip-list [data-local-trip="recall-drive"]').waitFor();
 await page.locator('.tv-clock').waitFor();assert.equal(routes.length,0);
 assert.equal(await page.locator('#local-trip-details-disclosure').evaluate(el=>el.open),false,'Sampling detail is collapsed by default');
 assert.equal(await page.locator('#local-trip-route').isVisible(),false);
 await page.locator('#local-trip-details-disclosure>summary').click();assert.ok(await page.locator('#local-trip-route').isVisible());assert.equal(routes.length,0,'Opening details does not load coordinates');
 await page.locator('#local-trip-details-disclosure>summary').click();
 const geometry=await page.locator('.tv-day-cards').evaluate(el=>{const a=el.children[0].getBoundingClientRect(),b=el.children[1].getBoundingClientRect();return {parallel:a.right<b.left,top:Math.abs(a.top-b.top),height:Math.abs(a.height-b.height)};});
 assert.ok(geometry.parallel&&geometry.top<1&&geometry.height<1,JSON.stringify(geometry));
 await page.locator('.tv-clock-rows [data-local-select="recall-drive"]').click();await page.waitForFunction(()=>localTrips.selection==='recall-drive');assert.ok(await page.locator('#local-trip-facts').isVisible());
 await page.locator('.tv-overview>summary').click();await page.locator('[data-trip-trend] svg').waitFor();
 for(const title of ['近 7 天里程','常走路线','常去地点'])await page.locator('#local-trip-overview-body').getByRole('heading',{name:title,exact:true}).waitFor();
 await page.screenshot({path:'/private/tmp/zeekr-local-trips-preview.png',fullPage:true});
 // A crowded day must scroll within the equal-height card and keep position.
 await page.evaluate(()=>{const base=localTrips.events.find(r=>r.type==='trip');localTrips.events=Array.from({length:30},(_,i)=>({...base,id:'many-'+i,start_time:base.start_time+i*60000,end_time:base.end_time+i*60000}));renderLocalTripList();const list=document.querySelector('#local-trip-list');list.scrollTop=250;});
 assert.ok(await page.locator('#local-trip-list').evaluate(el=>el.scrollHeight>el.clientHeight));
 const before=await page.locator('#local-trip-list').evaluate(el=>el.scrollTop);await page.evaluate(()=>renderLocalTripList());assert.equal(await page.locator('#local-trip-list').evaluate(el=>el.scrollTop),before);
 await page.locator('.tv-clock-rows [data-local-select="many-29"]').click();await page.waitForFunction(()=>localTrips.selection==='many-29');assert.ok(await page.locator('#local-trip-list').evaluate(el=>el.scrollTop)>before);
 const clockScroll=page.locator('#local-trip-clock-rows');await clockScroll.evaluate(el=>el.scrollTop=150);const clockBefore=await clockScroll.evaluate(el=>el.scrollTop);await page.evaluate(()=>renderLocalTripList());assert.equal(await clockScroll.evaluate(el=>el.scrollTop),clockBefore);
 for(const width of [1440,1280,1024]){await page.setViewportSize({width,height:1050});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
 assert.equal(routes.length,0);assert.deepEqual(errors,[]);
 console.log('Desktop local travel visuals passed: equal cards, clock, overview, crowded-day scrolling, selection and map privacy.');
}finally{if(browser)await browser.close();server.kill();}})().catch(e=>{console.error(e);process.exitCode=1;});
