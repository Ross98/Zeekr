// Synthetic history responses: no real account, coordinates or cloud requests.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
(async () => {
  const server = spawn('python3', [path.join(__dirname, 'web_fixture.py')]);
  let browser;
  try {
    const port = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('Fixture did not start')), 10000);
      server.stdout.once('data', data => { clearTimeout(timer); resolve(Number(String(data).trim())); });
      server.once('error', reject);
    });
    browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath:process.env.CHROMIUM_EXECUTABLE} : {})});
    const page = await browser.newPage({viewport:{width:1440,height:1050}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.stack));
    await page.route('https://tile.openstreetmap.org/**', route => route.abort());
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByRole('button',{name:'刷新状态',exact:true}).click();
    await page.getByText('64%',{exact:true}).first().waitFor();
    await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();
    await page.getByRole('button',{name:'云端历史',exact:true}).click();
    assert.match(await page.locator('main').innerText(), /需要连接云端历史账号/);
    await page.getByText('如何连接历史账号', {exact:true}).click();
    assert.match(await page.locator('main').innerText(), /history-connect/);
    let queries = [], pointQueries = 0, state = await page.evaluate(() => fetch('/api/state').then(r=>r.json()));
    state.history = {status:'ready',message:'可查询云端历史', connection_id:'fixture-session'};
    await page.route('**/api/state', route => route.fulfill({json:state}));
    await page.evaluate(() => pollState(true));
    const trip = {key:'trip-1',report_at:'2024-01-01 09:00:00（北京时间）',start_at:'2024-01-01 08:00:00（北京时间）',end_at:'2024-01-01 09:00:00（北京时间）',distance_km:42.5,duration_minutes:60,average_speed_kmh:42.5};
    let response = {status:'available',date:'2024-01-01',trips:[trip],next_cursor:1704070000000,total:21,read_at:'测试查询时间',cached:false};
    await page.route('**/api/history?**', async route => {
      queries.push(route.request().url());
      await route.fulfill({json:response});
    });
    let pointResponse = {status:'available',count:2,points:[{latitude:31,longitude:121,plottable:false,time_label:'未知'},{latitude:31.1,longitude:121.1,plottable:false,time_label:'未知'}],segments:[],unplottable_count:2,truncated:false};
    await page.route('**/api/history/points?**', async route => {
      pointQueries++;
      await route.fulfill({json:pointResponse});
    });
    await page.getByLabel('轨迹日期').fill('2024-01-01');
    assert.equal(queries.length, 0, 'opening tab, polling state and changing date must not query the cloud');
    await page.getByRole('button',{name:'查询行程',exact:true}).click();
    await page.getByRole('button',{name:/查看行程 1/}).waitFor();
    assert.equal(queries.length, 1);
    await page.getByRole('button',{name:/查看行程 1/}).click();
    assert.equal(pointQueries, 0, 'location disclosure must be explicit');
    assert.match(await page.locator('#cloud-detail').innerText(), /42.5 km/);
    await page.getByRole('button',{name:'显示行程路线',exact:true}).click();
    await page.getByText('坐标系未确认', {exact:true}).waitFor();
    assert.equal(pointQueries, 1);
    assert.equal(await page.locator('.leaflet-container').count(), 0);
    await page.getByRole('button',{name:'隐藏位置',exact:true}).click();
    const points = [
      {latitude:31,longitude:121,plottable:true,trusted:true,time:1704067200000,time_label:'08:00',time_source:'轨迹点上报时间'},
      {latitude:31.01,longitude:121.01,plottable:true,trusted:true,time:1704067260000,time_label:'08:01',time_source:'轨迹点上报时间'},
      {latitude:31.02,longitude:121.02,plottable:true,trusted:true,time:1704068400000,time_label:'08:20',time_source:'轨迹点上报时间'}];
    pointResponse = {status:'available',count:3,points,segments:[points.slice(0,2),points.slice(2)],unplottable_count:0,truncated:false};
    await page.getByRole('button',{name:'显示行程路线',exact:true}).click();
    await page.locator('.leaflet-container').waitFor();
    assert.equal(await page.locator('path.leaflet-interactive[fill="none"]').count(),1,'only the continuous segment should have a line');
    assert.match(await page.locator('#cloud-route-density').innerText(),/1 段稀疏示意线/);
    assert.equal(await page.locator('path.route-sparse-line').getAttribute('stroke-dasharray'),'7 7');
    await page.getByLabel('轨迹回看位置').fill('2');
    assert.match(await page.locator('#playback-label').innerText(), /3 \/ 3.*08:20/);
    for(const width of [320,390,1024,1440]) {
      await page.setViewportSize({width,height:1050});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),false,`overflow at ${width}`);
    }
    await page.setViewportSize({width:390,height:1050});
    fs.mkdirSync('/tmp/zeekr-history-qa',{recursive:true});
    await page.evaluate(() => window.scrollTo(0,0));
    await page.screenshot({path:'/tmp/zeekr-history-qa/history-mobile.png',fullPage:true});
    await page.setViewportSize({width:1440,height:1050});
    fs.mkdirSync('/tmp/zeekr-history-qa',{recursive:true});
    await page.evaluate(() => window.scrollTo(0,0));
    await page.screenshot({path:'/tmp/zeekr-history-qa/history-desktop.png',fullPage:true});
    response = {...response,trips:[{...trip,key:'trip-2'}],next_cursor:null};
    await page.getByRole('button',{name:'下一页',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('[data-action="cloud-next"]')?.disabled);
    assert.match(queries[1], /cursor=1704070000000/);
    assert.equal(await page.locator('#cloud-detail').count(), 0);
    for (const [status,message] of [['empty','这一天没有云端行程'],['forbidden','账号无权读取云端历史'],['session_expired','历史会话已失效'],['request_failed','历史查询失败']]) {
      response = {status,message,trips:status==='empty'?[]:undefined,next_cursor:null};
      await page.getByRole('button',{name:'查询行程',exact:true}).click();
      await page.getByText(message,{exact:true}).first().waitFor();
    }
    // A late response for a different date must never replace the current view.
    let finish;
    await page.unroute('**/api/history?**');
    await page.route('**/api/history?**', async route => {
      await new Promise(resolve => {finish=resolve;});
      await route.fulfill({json:{status:'available',trips:[trip],next_cursor:null}});
    });
    await page.getByRole('button',{name:'查询行程',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('[data-action="cloud-query"]')?.disabled);
    await page.getByLabel('轨迹日期').fill('2024-01-02');
    finish();
    await page.waitForTimeout(100);
    assert.equal(await page.getByRole('button',{name:/查看行程 1/}).count(), 0);
    assert.match(await page.locator('main').innerText(), /查询所选日期/);
    assert.deepEqual(errors,[]);
    console.log('History UI passed: authorization, explicit query, privacy, detail, pagination, states, stale response, four widths.');
  } finally { if(browser) await browser.close(); server.kill(); }
})().catch(error => { console.error(error); process.exitCode=1; });
