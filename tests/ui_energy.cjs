// Synthetic state only; catches snapshot fallback, missing trip states and disclosure loss.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const server = spawn('python3', [path.join(__dirname, 'web_fixture.py')]);
  let browser;
  try {
    const port = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(Error('Fixture did not start')), 10000);
      server.stdout.once('data', data => { clearTimeout(timeout); resolve(Number(String(data).trim())); });
      server.once('error', reject);
    });
    browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath:process.env.CHROMIUM_EXECUTABLE} : {})});
    const page = await browser.newPage({colorScheme:process.env.UI_COLOR_SCHEME || 'light',viewport:{width:1440,height:1050}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const chargeQueries = [];
    let chargeFailure = false;
    let chargeResponse = {events:[
      {id:'charge-complete',kind:'charge_end',start_time:1704067200000,end_time:1704070800000,duration_seconds:3600,start_soc:20,end_soc:80,soc_delta:60,partial:false,battery_capacity_kwh:86,estimated_kwh:51.6},
      {id:'charge-partial',kind:'charge_end',start_time:null,end_time:1703984400000,duration_seconds:1200,start_soc:70,end_soc:75,soc_delta:5,partial:true,battery_capacity_kwh:86,estimated_kwh:null}
    ],next_cursor:'next-page'};
    await page.route('**/api/events?**', async route => {
      chargeQueries.push(route.request().url());
      if (chargeFailure) return route.fulfill({status:500,json:{error:'合成记录读取失败'}});
      await route.fulfill({json:chargeResponse});
    });
    const analyticsPoints=[
      {time:1704067200000,soc:20,power_kw:6,segment_id:0,quality:'valid'},
      {time:1704067260000,soc:21,power_kw:6.2,segment_id:0,quality:'valid'},
      {time:1704067600000,soc:30,power_kw:6.4,segment_id:1,quality:'valid'}
    ];
    const analyticsQueries=[],statisticsQueries=[];
    await page.route('**/api/charging/process?**', route => {
      analyticsQueries.push(route.request().url());
      const electrical=new URL(route.request().url()).searchParams.get('view')==='electrical';
      const points=analyticsPoints.map(point=>electrical?{time:point.time,soc:point.soc,voltage:220,current:29,mode:'ac',segment_id:point.segment_id,quality:'valid'}:point);
      return route.fulfill({json:{session:{id:'current',status:'active',partial:false,start_time:1704067200000,end_time:1704067600000,start_soc:20,end_soc:30,power_kw:6.4,mode:'ac'},series:{id:'current',view:electrical?'electrical':'power-soc',points,segments:[{id:0},{id:1}],raw_count:3,display_count:3,has_gaps:true,downsampled:false}}});
    });
    await page.route('**/api/charging/statistics?**', route => {statisticsQueries.push(route.request().url());return route.fulfill({json:{days:30,mode:'all',timezone:'Asia/Shanghai',summary:{ended_count:2,complete_count:1,partial_count:1,estimated_kwh:51.6,included_energy_count:1,excluded_energy_count:1,complete_duration_seconds:3600,duration_seconds:3600,included_duration_count:1,partial_energy_count:0},daily:Array.from({length:30},(_,index)=>({date:`2024-01-${String(index+1).padStart(2,'0')}`,count:index===1?2:0,estimated_kwh:index===1?51.6:null,ac_kwh:index===1?51.6:0,dc_kwh:0,unknown_kwh:0})),records:[{id:'charge-complete',end_time:1704070800000,start_time:1704067200000,date:'2024-01-01',mode:'ac',partial:false,start_soc:20,end_soc:80,duration_seconds:3600,estimated_kwh:51.6},{id:'charge-partial',end_time:1703984400000,date:'2023-12-31',mode:'dc',partial:true,start_soc:70,end_soc:75,duration_seconds:null,estimated_kwh:null}]}});});
    await page.goto(`http://127.0.0.1:${port}`);
    await page.getByRole('button',{name:'能源与充电',exact:true}).first().click();
    assert.match(await page.locator('main').innerText(), /尚未读取/);
    await page.getByRole('button',{name:'刷新状态',exact:true}).click();
    await page.getByText('64%',{exact:true}).first().waitFor();
    await page.getByRole('tab',{name:'本次过程'}).waitFor();
    assert.match(await page.locator('.charging-tab-panel').innerText(),/本次观测.*观测功率.*有缺口.*动力电池 SOC/s);
    assert.match(await page.locator('.charging-chart').first().innerText(),/北京时间/,'chart axes must state time zone');
    const graph = page.locator('.charging-chart').first();
    assert.equal((await graph.locator('.chart-line').getAttribute('d')).match(/M/g).length,2,'sampling gaps remain disconnected');
    assert.equal(await graph.locator('.chart-point').count(),3,'isolated samples remain visible');
    assert.equal(await graph.locator('.chart-gap').count(),1,'sampling gaps receive a visible marker');
    assert.equal(await graph.locator('.chart-cursor').count(),1,'both charts expose the synchronized selected time');
    const queriesAfterFirstLoad=analyticsQueries.length;
    assert.equal(new URL(analyticsQueries[0]).searchParams.get('id'),'current','history list defaults must not replace the current process chart');
    await page.evaluate(()=>render());
    await page.waitForTimeout(50);
    assert.equal(analyticsQueries.length,queriesAfterFirstLoad,'unrelated page renders must reuse the loaded chart');
    await page.getByRole('button',{name:'电气细节'}).click();
    assert.match(await page.locator('.charging-tab-panel').innerText(),/电压.*电流/s);
    await page.getByRole('tab',{name:'统计趋势'}).click();
    assert.equal(statisticsQueries.length,0,'statistics must wait for explicit query');
    await page.getByRole('button',{name:'查询充电统计',exact:true}).click();
    await page.getByText('估算充入电量',{exact:true}).waitFor();
    assert.match(await page.locator('.charging-tab-panel').innerText(),/已结束次数.*2.*完整 1.*部分 1.*51\.6/s);
    await page.getByRole('button',{name:'最近 7 天',exact:true}).click();
    assert.equal(await page.locator('.charging-stat-summary').count(),0);
    assert.equal(statisticsQueries.length,1);
    await page.getByRole('button',{name:'查询充电统计',exact:true}).click();
    await page.getByText('估算充入电量',{exact:true}).waitFor();
    assert.equal(new URL(statisticsQueries.at(-1)).searchParams.get('days'),'7');
    const beforeContextChange=statisticsQueries.length;
    await page.evaluate(()=>{window.savedEnergyContext=state.insights_context;state.insights_context='different-account';render();});
    assert.equal(await page.locator('.charging-stat-summary').count(),0,'account switch clears previously queried statistics');
    assert.equal(statisticsQueries.length,beforeContextChange,'account switch must not query statistics');
    await page.evaluate(()=>{state.insights_context=window.savedEnergyContext;render();});
    let releaseStatistics;
    const delayedStatistics=async route=>{await new Promise(resolve=>{releaseStatistics=resolve;});await route.fallback();};
    await page.route('**/api/charging/statistics?**',delayedStatistics);
    const pendingStatistics=page.waitForRequest('**/api/charging/statistics?**');
    await page.getByRole('button',{name:'查询充电统计',exact:true}).click();
    await pendingStatistics;
    await page.locator('#charging-mode').selectOption('ac');
    const oldStatistics=page.waitForResponse('**/api/charging/statistics?**');
    releaseStatistics();await oldStatistics;await page.evaluate(()=>new Promise(requestAnimationFrame));
    assert.equal(await page.locator('.charging-stat-summary').count(),0,'old statistics response must not restore results after editing conditions');
    await page.unroute('**/api/charging/statistics?**',delayedStatistics);
    await page.locator('#charging-mode').selectOption('all');
    await page.getByRole('tab',{name:'本次过程'}).click();
    await page.locator('#charge-history').waitFor();
    assert.equal(chargeQueries.length,0,'opening and rendering energy must not query history');
    await page.getByLabel('充电记录日期').fill('2024-01-01');
    assert.equal(chargeQueries.length,0,'changing dates must not query history');
    await page.getByRole('button',{name:'查询充电记录',exact:true}).click();
    await page.evaluate(()=>render());
    await page.getByRole('button',{name:/查看充电记录 1/}).waitFor();
    assert.match(chargeQueries[0], /date=2024-01-01&kind=charge_end/);
    assert.match(await page.locator('#charge-history').innerText(), /充电记录.*20%.*80%.*完整记录/s);
    assert.match(await page.locator('#charge-detail').innerText(), /记录起点.*结束时间.*1 小时.*60 个百分点.*51\.6 kWh.*估算/s);
    assert.match(await page.locator('#charge-detail').innerText(), /未保存充电参数/);
    await page.getByRole('tab',{name:'参数详情'}).click();
    const parameterCard=page.locator('#charging-parameters');
    assert.equal(await parameterCard.locator('.charging-parameter').count(),27);
    assert.match(await parameterCard.innerText(), /高压充电相关状态码/);
    assert.match(await parameterCard.innerText(), /预约充电状态码/);
    assert.match(await parameterCard.innerText(), /充电限值.*未提供或未核验/s);
    await page.getByRole('tab',{name:'本次过程'}).click();
    await page.getByRole('button',{name:/查看充电记录 2/}).click();
    assert.equal(new URL(analyticsQueries.at(-1)).searchParams.get('id'),'charge-partial','an explicit history selection changes the process chart');
    assert.match(await page.locator('#charge-detail').innerText(), /部分记录.*起止时间.*不满足估算条件.*已有观测保留/s);
    assert.doesNotMatch(await page.locator('#charge-detail').innerText(), /4\.3 kWh/);
    await page.evaluate(() => render());
    await page.getByRole('button',{name:/查看充电记录 2/}).waitFor();
    assert.match(await page.locator('#charge-detail').innerText(), /部分记录/,'state refresh must preserve selected charging record');
    fs.mkdirSync('/tmp/zeekr-energy-qa',{recursive:true});
    await page.setViewportSize({width:1440,height:900});
    await page.screenshot({path:'/tmp/zeekr-energy-qa/charging-detail-1440.png',fullPage:true});
    await page.setViewportSize({width:1280,height:800});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true,'Overflow at 1280');
    const chargingColumns=await page.evaluate(()=>{
      const list=document.querySelector('.charge-list-card').getBoundingClientRect();
      const detail=document.querySelector('.charge-detail').getBoundingClientRect();
      const pagination=document.querySelector('.charge-list-card .event-pagination').getBoundingClientRect();
      return {listWidth:list.width,detailWidth:detail.width,listBottom:list.bottom,paginationBottom:pagination.bottom};
    });
    assert.ok(Math.abs(chargingColumns.listWidth-chargingColumns.detailWidth)<4,'selected charging detail uses the full list width');
    assert.ok(Math.abs(chargingColumns.listBottom-chargingColumns.paginationBottom)<2,'pagination must sit at the bottom of the charging list card');
    await page.screenshot({path:'/tmp/zeekr-energy-qa/charging-detail-1280.png',fullPage:true});
    chargeResponse={events:[{id:'charge-complete',kind:'charge_end',start_time:1704067200000,end_time:1704070800000,duration_seconds:3600,start_soc:20,end_soc:80,soc_delta:60,partial:false,battery_capacity_kwh:86,estimated_kwh:51.6}],next_cursor:'next-page'};
    await page.evaluate(() => render());
    await page.getByRole('button',{name:/查看充电记录 1/}).waitFor();
    assert.match(await page.locator('#charge-detail').innerText(), /部分记录/,'new first-page record must not replace a detail the user is reading');
    chargeResponse={events:[{id:'page-two',kind:'charge_end',start_time:1704067200000,end_time:1704070800000,duration_seconds:3600,start_soc:30,end_soc:60,soc_delta:30,partial:false,battery_capacity_kwh:null,estimated_kwh:null}],next_cursor:null};
    await page.getByRole('button',{name:'下一页',exact:true}).click();
    await page.getByText('充入电量无法估算',{exact:true}).waitFor();
    chargeResponse.next_cursor='range-next';
    const beforeRange=chargeQueries.length;
    await page.getByLabel('充电记录查询方式').selectOption('range');
    await page.getByLabel('充电记录开始日期').fill('2024-01-01');
    await page.getByLabel('充电记录结束日期').fill('2024-01-03');
    assert.equal(chargeQueries.length,beforeRange,'range edits must not query');
    for(const width of [390,320]){
      await page.setViewportSize({width,height:1050});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`Range controls overflow at ${width}`);
    }
    await page.setViewportSize({width:1440,height:1050});
    await page.getByRole('button',{name:'查询充电记录',exact:true}).click();
    await page.getByRole('button',{name:/查看充电记录 1/}).waitFor();
    chargeResponse={events:[],next_cursor:null};
    await page.getByRole('button',{name:'下一页',exact:true}).click();
    await page.getByText('该日期暂无充电记录',{exact:true}).waitFor();
    assert.equal(new URL(chargeQueries.at(-1)).searchParams.get('date'),'2024-01-01');
    assert.equal(new URL(chargeQueries.at(-1)).searchParams.get('end'),'2024-01-03');
    assert.equal(new URL(chargeQueries.at(-1)).searchParams.get('cursor'),'range-next');
    const beforeInvalid=chargeQueries.length;
    await page.getByLabel('充电记录结束日期').fill('2023-12-31');
    await page.getByRole('button',{name:'查询充电记录',exact:true}).click();
    assert.equal(chargeQueries.length,beforeInvalid,'invalid range must not query');
    assert.match(await page.locator('#charge-list').innerText(),/结束日期不能早于开始日期/);
    chargeFailure=true;
    await page.getByLabel('充电记录结束日期').fill('2024-01-04');
    await page.getByRole('button',{name:'查询充电记录',exact:true}).click();
    await page.getByText('充电记录读取失败',{exact:true}).waitFor();
    assert.match(await page.locator('#charge-list').innerText(),/合成记录读取失败.*重试/s);
    chargeFailure=false;
    await page.getByRole('button',{name:'重试',exact:true}).click();
    await page.getByText('该日期暂无充电记录',{exact:true}).waitFor();
    const original = await page.evaluate(() => fetch('/api/state').then(r=>r.json()));
    const saved=structuredClone(original.model.charging_details);
    saved.mode='ac'; saved.charging=true; saved.power_kw=6.375;
    saved.parameters.find(item=>item.key==='chargeUAct').value=206.2;
    chargeResponse={events:[{id:'saved-charge',kind:'charge_end',start_time:1704067200000,end_time:1704070800000,duration_seconds:3600,start_soc:20,end_soc:80,partial:false,battery_capacity_kwh:86,charging_details:{start:saved,end:saved,metrics:{sampled_peak_kw:6.5,average_power_kw:6.2,power_coverage:.85,power_sample_count:10}}}],next_cursor:null};
    await page.getByLabel('充电记录查询方式').selectOption('day');
    await page.getByLabel('充电记录日期').fill('2024-01-01');
    await page.getByRole('button',{name:'查询充电记录',exact:true}).click();
    await page.getByText('已保存充电参数',{exact:true}).waitFor();
    assert.match(await page.locator('#charge-detail').innerText(),/交流 → 交流.*6\.375 kW.*6\.5 kW.*6\.2 kW.*85 %/s);
    await page.locator('[data-detail="charge-saved-parameters"] summary').click();
    assert.match(await page.locator('#charge-detail').innerText(),/起点：206\.2 V.*终点：206\.2 V/s);
    await page.evaluate(()=>render());
    await page.getByText('已保存充电参数',{exact:true}).waitFor();
    assert.equal(await page.locator('[data-detail="charge-saved-parameters"]').getAttribute('open'),'');
    // Background refresh must keep the reading position after restoring tall disclosures.
    for (const width of [1440,390]) {
      await page.setViewportSize({width,height:700});
      const before=await page.evaluate(()=>{
        document.activeElement?.blur();
        window.scrollTo(0,document.documentElement.scrollHeight-innerHeight);
        return scrollY;
      });
      assert.ok(before>500,'regression must exercise a deeply scrolled page');
      await page.evaluate(()=>render());
      await page.waitForTimeout(50);
      assert.ok(Math.abs(await page.evaluate(()=>scrollY)-before)<2,`background refresh moved reading position at ${width}`);
      await page.locator('[data-detail="charge-saved-parameters"] summary').focus();
      await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight-innerHeight));
      const workspaceBefore=await page.evaluate(()=>scrollY);
      await page.evaluate(()=>renderChargingWorkspace());
      await page.waitForTimeout(50);
      assert.ok(Math.abs(await page.evaluate(()=>scrollY)-workspaceBefore)<2,`chart refresh moved reading position at ${width}`);
    }

    for (const width of [1440,390,320]) {
      await page.setViewportSize({width,height:1050});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`Expanded history overflow at ${width}`);
    }
    await page.locator('[data-detail="charge-saved-parameters"] summary').click();
    await page.setViewportSize({width:1440,height:1050});
    const data = structuredClone(original);
    data.profile = {name:'验收车辆',variant:'合成数据',range_km:546,range_standard:'CLTC',range_source:'合成配置'};
    data.model.metric_details.battery.value = 50;
    data.model.metric_details.range.value = 230;
    data.model.metrics.battery = '50%';
    data.model.metrics.range = '230 km';
    data.range_attainment = {status:'available', partial:true, ratio:73.26007326, distance_km:80, start_soc:80, end_soc:60, used_soc:20, reference_km:109.2, standard:'CLTC', start_at:'2024-01-01 08:00',end_at:'2024-01-01 09:00'};
    await page.route('**/api/state', route=>route.fulfill({json:data}));
    await page.route('**/api/refresh', route=>route.fulfill({json:data}));
    const refresh = async () => {
      await page.getByRole('button',{name:'刷新状态',exact:true}).click();
      await page.waitForFunction(() => !document.querySelector('[data-action="refresh"]').disabled);
    };
    await refresh();
    assert.match(await page.locator('main').innerText(), /73\.3/,'80 km driven on 20 percentage points must use trip attainment');
    assert.match(await page.locator('.energy-achievement').innerText(), /片段/);
    assert.match(await page.locator('.energy-rating').innerText(), /546/);
    assert.match(await page.locator('.energy-rating').innerText(), /CLTC/);
    assert.match(await page.locator('.energy-charge').innerText(), /暂无有效时间估计/);
    assert.match(await page.locator('#charge-history').innerText(), /充电记录/);
    assert.doesNotMatch(await page.locator('main').innerText(), /chargeUAct|mainBatteryStatus/);
    const details = page.locator('details[data-detail="energy-electric"]');
    await details.locator('summary').focus();
    await page.keyboard.press('Enter');
    assert.match(await details.innerText(), /chargeUAct/);
    await refresh();
    assert.equal(await details.getAttribute('open'), '');
    await details.locator('summary').click();
    for (const width of [1440,1024,390,320]) {
      await page.setViewportSize({width,height:1050});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true,`Overflow at ${width}`);
      await page.evaluate(()=>{document.querySelector('#toast').hidden=true; document.activeElement?.blur(); window.scrollTo(0,0);});
      await page.screenshot({path:`/tmp/zeekr-energy-qa/energy-${width}.png`,fullPage:true});
    }
    await page.locator('details[data-detail="energy-low-voltage"] > summary').click();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true,'Expanded low-voltage fields fit mobile');
    await page.setViewportSize({width:1440,height:1050});
    // Current snapshot changes must not change an already completed trip.
    data.model.metric_details.battery.value=0;
    data.model.metric_details.range.value=null;
    await refresh();
    assert.match(await page.locator('.energy-achievement').innerText(), /73\.3/);
    assert.match(await page.locator('.energy-achievement').innerText(), /80.*60/s);
    for (const status of ['no_trip','incomplete','invalid','no_consumption','no_rating','unavailable']) {
      data.range_attainment={status};
      await refresh();
      assert.doesNotMatch(await page.locator('.energy-achievement').innerText(), /73\.3|84\.2|NaN|Infinity/);
      assert.match(await page.locator('.energy-achievement').innerText(), /暂无可计算行程|无法计算/);
    }
    delete data.range_attainment;
    await refresh();
    assert.match(await page.locator('.energy-achievement').innerText(), /暂无可计算行程/);
    data.model.charging={value:'直流充电中',confirmed:true,mode:'dc',remaining_time:'25 分钟',connection_state:'未知',detail:'匹配充电证据；数据来自车辆云端缓存。'};
    await refresh();
    assert.match(await page.locator('.energy-charge').innerText(),/直流充电中.*25 分钟.*缺少会话起点时不推测充电开始时间/s);
    data.model.charging={value:'充电已停止',confirmed:true,mode:null,remaining_time:'未知',connection_state:'未知',detail:'匹配本车已观察的直流停止组合；不能仅据此判断停止原因或是否已拔枪。'};
    await refresh();
    assert.match(await page.locator('.energy-charge').innerText(),/充电已停止/);
    assert.doesNotMatch(await page.locator('.energy-charge').innerText(),/已充满/);
    data.model.charging={value:'未知',confirmed:false};
    await refresh();
    assert.match(await page.locator('.energy-charge').innerText(),/充电状态未知/);
    assert.doesNotMatch(await page.locator('.energy-charge').innerText(),/未插枪/);
    assert.deepEqual(errors,[]);
    console.log('Energy UI passed: charging history/detail/states, selection, errors, trip attainment, keyboard, refresh, target widths.');
  } finally { if(browser) await browser.close(); server.kill('SIGTERM'); }
})().catch(error=>{console.error(error);process.exitCode=1;});
