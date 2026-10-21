// Cloud history is retired. Exercise the local replacement with synthetic data.
const assert=require('node:assert/strict');
const {fixture,contrast}=require('./ui_insight_helpers.cjs');
(async()=>{
  const historyRequests=[];
  const f=await fixture({initialResearch:false,beforeGoto:async page=>{
    page.on('request',request=>{if(new URL(request.url()).pathname.startsWith('/api/history'))historyRequests.push(request.url());});
    await page.route('https://wprd0*.is.autonavi.com/**',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e5ece6"/></svg>'}));
  }});
  const {page}=f;
  try{
    await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();
    const navigation=page.getByRole('navigation',{name:'行程与轨迹子功能',exact:true});
    assert.deepEqual(await navigation.locator('button').allTextContents(),['本地记录','行程标签']);
    const retiredRequests=[];page.on('request',request=>{if(/\/(?:travel-insights\.js|api\/insights\/routes)(?:\?|$)/.test(request.url()))retiredRequests.push(request.url());});
    await page.goto(f.origin+'/?p=tracks&t=routes&month=2026-09');
    await page.getByLabel('轨迹日期').waitFor();
    assert.equal(new URL(page.url()).searchParams.get('t'),null);
    assert.equal(await page.locator('#route-comparison').count(),0);
    assert.deepEqual(retiredRequests,[]);
    await page.goto(f.origin+'/?p=tracks&s=cloud&date=2026-09-19&q=1');
    await page.waitForFunction(()=>localTrips?.queried&&!localTrips.listBusy&&localTrips.events?.length);
    assert.equal(await page.getByLabel('轨迹日期').inputValue(),'2026-09-19');
    assert.equal(new URL(page.url()).searchParams.get('s'),'local','old cloud links normalize to local records');
    assert.equal(await page.locator('#map').count(),0);
    assert.equal(await page.locator('script[src="/history.js"]').count(),0);
    assert.ok((await page.evaluate(()=>localTrips.events)).some(row=>row.type==='trip'));
    await page.locator('#local-trip-details-disclosure>summary').click();
    await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();
    await page.waitForFunction(()=>localTrips.route&&!localTrips.routeBusy);
    assert.equal(await page.locator('#map').count(),1);
    await page.getByRole('button',{name:'隐藏位置',exact:true}).click();
    assert.equal(await page.locator('#map').count(),0);
    for(const theme of ['light','dark']){
      await page.getByLabel('外观',{exact:true}).selectOption(theme);
      for(const width of [1024,1280,1440]){
        await page.setViewportSize({width,height:1000});
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
        await contrast(page,'#local-trips');
      }
    }
    await page.getByRole('button',{name:'设置',exact:true}).first().click();
    assert.doesNotMatch(await page.locator('main').innerText(),/历史轨迹接口|云端历史/);
    assert.deepEqual(historyRequests,[]);
    assert.deepEqual(f.errors,[]);
    console.log('CLOUD_HISTORY_REMOVAL_DESKTOP_PASS: local links, explicit maps, navigation, settings, no cloud requests');
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
