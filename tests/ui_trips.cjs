// Real local APIs and synthetic records. Map tiles intercepted; no vehicle/network access.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
(async () => {
  const server = spawn('python3', [path.join(__dirname, 'trips_fixture.py')]);
  let browser;
  try {
    const port = await new Promise((resolve,reject) => {
      const timeout=setTimeout(()=>reject(Error('Fixture did not start')),10000);
      server.stdout.once('data',data=>{clearTimeout(timeout);resolve(Number(String(data).trim()));});
      server.stderr.on('data',data=>process.stderr.write(data));
      server.once('error',reject);
    });
    browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
    const page=await browser.newPage({viewport:{width:1440,height:1080},colorScheme:process.env.UI_COLOR_SCHEME||'light',timezoneId:'America/Los_Angeles'});
    page.setDefaultTimeout(7000);
    const errors=[],routeQueries=[],tileQueries=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>{if(request.url().includes('/api/tracks?'))routeQueries.push(request.url());});
    await page.route('https://tile.openstreetmap.org/**',route=>{
      tileQueries.push(route.request().url());
      return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e5ece6"/><path d="M0 128H256M128 0V256" stroke="#fff" stroke-width="8"/></svg>'});
    });
    await page.goto(`http://127.0.0.1:${port}`);
    assert.equal(await page.locator('html').getAttribute('data-theme'),process.env.UI_COLOR_SCHEME||'light');
    await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();
    await page.getByLabel('轨迹日期').fill('2024-01-02');
    await page.getByRole('button',{name:'全天总览',exact:true}).waitFor();
    const night=page.locator('[data-local-trip="night-trip"]');
    await night.click();
    assert.equal(await page.locator('#archive-vehicle').count(),0);
    assert.equal(routeQueries.length,0,'Trip summaries do not request coordinates');
    assert.equal(tileQueries.length,0,'No external tiles before consent');
    assert.match(await page.locator('#local-trip-detail').innerText(),/23:58/,'Times use Beijing even in another browser timezone');
    assert.match(await page.locator('#local-trip-detail').innerText(),/9.6/);
    await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();
    await page.getByLabel('轨迹回看位置').waitFor();
    assert.ok(routeQueries.at(-1).includes('trip=night-trip'));
    assert.match(await page.locator('#playback-label').innerText(),/23:58/,'Cross-midnight start included');
    assert.match(await page.locator('#local-route-quality').innerText(),/间断|缺口/);
    assert.match(await page.locator('.route-density').innerText(),/中位 60 秒/);
    assert.match(await page.locator('.route-density').innerText(),/可信连线跨度.*直线距离/s);
    assert.match(await page.locator('.route-density-note').innerText(),/4 段稀疏示意线/);
    assert.equal(await page.locator('path.route-sparse-line').count(),2,'Preserve the two original source segments');
    assert.equal(await page.locator('path.route-sparse-line').first().getAttribute('stroke-dasharray'),'7 7');
    assert.equal(await page.evaluate(()=>localTrips.route.count),7,'No original sampling point is discarded');
    assert.match(await page.locator('#map').innerText(),/首个采样点/);
    assert.match(await page.locator('#map').innerText(),/末个采样点/);
    assert.match(await page.locator('#map').innerText(),/采样间断/,'Known gap boundaries are marked on the map');
    await page.getByRole('button',{name:'查看全程',exact:true}).click();
    await page.getByRole('button',{name:'下一点',exact:true}).click();
    const pointBefore=await page.locator('#playback').inputValue();
    await page.waitForFunction(()=>map && !map._animatingZoom && !map._panAnim?._inProgress);
    await page.evaluate(()=>{window.__tripMap=map;map.stop();map.setView([31.01,121.02],12,{animate:false});});
    assert.equal(await page.evaluate(()=>map.getZoom()),12);
    await page.evaluate(async()=>{state.recording.last_sample='force local refresh';await pollState();});
    await page.waitForTimeout(300);
    assert.equal(await page.evaluate(()=>map===window.__tripMap),true,'Polling preserves map instance');
    assert.equal(await page.locator('#playback').inputValue(),pointBefore,'Polling preserves replay selection');
    assert.equal(await page.evaluate(()=>map.getZoom()),12);
    await page.getByRole('button',{name:'播放',exact:true}).click();
    await page.waitForTimeout(1150);
    assert.ok(Number(await page.locator('#playback').inputValue())>Number(pointBefore));
    await page.getByRole('button',{name:'暂停',exact:true}).click();
    const stopped=await page.locator('#playback').inputValue();
    await page.waitForTimeout(1100);
    assert.equal(await page.locator('#playback').inputValue(),stopped);
    await page.getByLabel('回放速度').selectOption('4');
    await page.getByRole('button',{name:'上一点',exact:true}).click();
    await page.getByRole('button',{name:'隐藏位置',exact:true}).click();
    assert.equal(await page.locator('#map').count(),0);
    assert.equal(await page.locator('.route-density').count(),0,'Hiding location also clears coordinate-derived density');
    assert.equal(await page.evaluate(()=>playback.length),0);
    // A delayed route from the previous selection must never replace the new trip.
    let release;
    const delayed=new Promise(resolve=>release=resolve);
    await page.route('**/api/tracks?**',async route=>{
      const response=await route.fetch();
      if(new URL(route.request().url()).searchParams.get('trip')==='night-trip')await delayed;
      await route.fulfill({response});
    });
    const pending=page.waitForRequest(request=>request.url().includes('trip=night-trip'));
    await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();
    await pending;
    await page.locator('[data-local-trip="morning-trip"]').click();
    await page.getByLabel('轨迹回看位置').waitFor();
    release();
    await page.waitForTimeout(200);
    assert.match(await page.locator('#local-trip-detail').innerText(),/16.8/);
    assert.match(await page.locator('#playback-label').innerText(),/09:58/);
    await page.unroute('**/api/tracks?**');
    // Completing a request while away must release its busy state for re-entry.
    await page.getByRole('button',{name:'隐藏位置',exact:true}).click();
    let finishAway;
    const away=new Promise(resolve=>finishAway=resolve);
    await page.route('**/api/tracks?**',async route=>{
      const response=await route.fetch();await away;await route.fulfill({response});
    });
    const awayRequest=page.waitForRequest(request=>request.url().includes('/api/tracks?'));
    await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();
    await awayRequest;
    await page.getByRole('button',{name:'车辆',exact:true}).first().click();
    const awayResponse=page.waitForResponse(response=>response.url().includes('/api/tracks?'));
    finishAway();await awayResponse;
    await page.waitForTimeout(100);
    await page.unroute('**/api/tracks?**');
    await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();
    await page.getByLabel('轨迹回看位置').waitFor();
    fs.mkdirSync('/tmp/zeekr-trips-qa',{recursive:true});
    await page.screenshot({path:`/tmp/zeekr-trips-qa/desktop-${process.env.UI_COLOR_SCHEME||'light'}.png`,fullPage:true});
    for(const width of [390,320]){
      await page.setViewportSize({width,height:920});
      await page.getByRole('button',{name:'查看全程',exact:true}).click();
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`No overflow at ${width}`);
      await page.waitForFunction(()=>{
        let loading=false;map.eachLayer(layer=>{if(layer instanceof L.TileLayer&&layer.isLoading())loading=true;});return !loading;
      });
      await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});
      await page.screenshot({path:`/tmp/zeekr-trips-qa/mobile-${width}-${process.env.UI_COLOR_SCHEME||'light'}.png`,fullPage:true});
    }
    await page.getByRole('button',{name:'全天总览',exact:true}).click();
    await page.getByLabel('轨迹回看位置').waitFor();
    assert.equal(new URL(routeQueries.at(-1)).searchParams.has('trip'),false);
    await page.route('**/api/trips?**',route=>route.fulfill({status:500,json:{error:'合成行程读取失败'}}));
    await page.getByLabel('轨迹日期').fill('2024-01-03');
    await page.getByText('合成行程读取失败',{exact:false}).first().waitFor();
    assert.doesNotMatch(await page.locator('#local-trip-list').innerText(),/暂无已结束行程/,'Failure is not an empty list');
    assert.doesNotMatch(await page.locator('#local-trip-activity').innerText(),/暂无进行中/,'Failure is not an idle state');
    await page.unroute('**/api/trips?**');
    await page.getByRole('button',{name:'重试',exact:true}).click();
    await page.getByText('这一天暂无已结束行程。仍可查看全天采样。',{exact:true}).waitFor();
    // Current status comes from the local summary; this overlay exercises presentation only.
    let activity='driving';
    await page.route('**/api/trips?**',async route=>{
      const response=await route.fetch(),body=await response.json();
      body.active={id:'current',status:activity,start_time:1704124800000,end_time:1704124920000,duration_seconds:120,distance_km:1,start_soc:70,end_soc:69,partial:false};
      await route.fulfill({json:body});
    });
    await page.getByLabel('轨迹日期').fill('2024-01-02');
    await page.locator('#local-trip-activity').getByText(/行程记录中/).waitFor();
    activity='waiting';
    await page.getByRole('button',{name:'重新查询',exact:true}).click();
    await page.locator('#local-trip-activity').getByText(/停车确认中/).waitFor();
    await page.unroute('**/api/trips?**');
    // Two trips can transition between polls: keep the trip the user selected.
    let activeTrip='night-trip';
    await page.route('**/api/trips?**',async route=>{
      const response=await route.fetch(),body=await response.json();
      body.active=activeTrip?{...body.events.find(event=>event.id===activeTrip),id:'current',status:'driving'}:null;
      body.events=body.events.filter(event=>event.id!==activeTrip);
      await route.fulfill({json:body});
    });
    await page.route('**/api/tracks?**',async route=>{
      const url=new URL(route.request().url());
      if(url.searchParams.get('trip')==='current')url.searchParams.set('trip',activeTrip||'no-longer-current');
      const response=await route.fetch({url:url.toString()});await route.fulfill({response});
    });
    await page.getByRole('button',{name:'重新查询',exact:true}).click();
    await page.waitForFunction(()=>localTrips.active?.distance_km===9.6);
    await page.locator('[data-local-trip="current"]').click();
    await page.getByLabel('轨迹回看位置').waitFor();
    activeTrip='morning-trip';
    await page.evaluate(()=>refreshLocalTrips());
    await page.waitForFunction(()=>localTrips.selection==='night-trip');
    await page.getByLabel('轨迹回看位置').waitFor();
    assert.match(await page.locator('#local-trip-detail').innerText(),/9.6/);
    await page.locator('[data-local-trip="current"]').click();
    await page.getByLabel('轨迹回看位置').waitFor();
    activeTrip=null;
    await page.getByRole('button',{name:'重新查询',exact:true}).click();
    await page.waitForFunction(()=>localTrips.selection==='morning-trip');
    await page.getByLabel('轨迹回看位置').waitFor();
    assert.match(await page.locator('#playback-label').innerText(),/09:58/);
    await page.unroute('**/api/trips?**');await page.unroute('**/api/tracks?**');
    await page.getByLabel('轨迹日期').fill('');
    await page.getByRole('button',{name:'前一天',exact:true}).click();
    assert.match(await page.getByLabel('轨迹日期').inputValue(),/^\d{4}-\d{2}-\d{2}$/);
    assert.deepEqual(errors,[]);
    console.log('Trip browser tests passed: consent, single-car selection, midnight, quality, polling, playback, late requests, responsive layouts.');
  } finally {if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
