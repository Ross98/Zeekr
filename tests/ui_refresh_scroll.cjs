// Synthetic pages: background updates must not move the user's reading position.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture({demo:true,partialCharge:true,automatic:true});
  const {page}=f;
  try{
    let revision=0,recordsRevision=0;
    await page.route('**/api/state',async route=>{
      const response=await route.fetch(),data=await response.json();
      data.read_time=++revision;
      data.trip_records_revision=(data.trip_records_revision||0)+recordsRevision;
      data.charge_records_revision=(data.charge_records_revision||0)+recordsRevision;
      await route.fulfill({json:data});
    });
    const sections=['overview','calendar','report','car','energy','tracks','books','insights','settings'];
    const failures=[];
    async function navigate(selector){
      await page.evaluate(()=>document.activeElement?.blur());
      await page.waitForFunction(selector=>{
        const control=document.querySelector(selector);
        return control&&!control.disabled&&!window.booksWritePending?.();
      },selector);
      // Some retained research controls are hidden; exercise their existing handler.
      await page.locator(selector).first().evaluate(el=>el.click());
    }
    async function loadResults(section,tool){
      const view=tool?.replace('source:','')||section;
      if(view==='calendar'){
        await page.getByLabel('日历月份',{exact:true}).fill('2026-09');
        await page.getByRole('button',{name:'读取用车日历',exact:true}).click();
        await page.waitForSelector('#calendar-result-month');
        await page.locator('[data-calendar-day="2026-09-19"]').click();
        await page.locator('[data-calendar-event="report-trip-night"]').click();
      }else if(view==='report'){
        await page.getByLabel('报告周期',{exact:true}).selectOption('month');
        await page.getByLabel('周期内日期',{exact:true}).fill('2026-09-20');
        await page.getByRole('button',{name:'查看报告',exact:true}).click();
        await page.waitForSelector('#report-title');
      }else if(view==='ledger'){
        await page.locator('#ledger-month').fill('2026-09');
        await page.getByRole('button',{name:'读取账本',exact:true}).click();
        await page.waitForSelector('#ledger-range');
      }else if(view==='insights'){
        await page.waitForSelector('#field-results');
      }else if(view==='research'){
        await page.getByLabel('研究开始日期',{exact:true}).fill('2026-09-20');
        await page.getByLabel('研究结束日期',{exact:true}).fill('2026-09-20');
        await page.getByRole('button',{name:'分析本地数据',exact:true}).click();
        await page.waitForSelector('#research-fields');
      }else if(view==='time'){
        await page.locator('#insight-date').fill('2026-09-20');
        await page.getByRole('button',{name:'查看归档',exact:true}).click();
        await page.waitForSelector('#insight-select');
      }else if(view==='automatic'){
        await page.getByRole('button',{name:'读取最新结论',exact:true}).click();
        await page.waitForSelector('#auto-energy');
      }else if(view==='parameters'){
        await page.waitForSelector(section==='car'?'.vehicle-table':'#field-results');
      }else if(view==='car'){
        await page.locator('[data-vehicle="overview"]').click();
      }else if(view==='energy'){
        await page.locator('[data-action="charging-tab"][data-tab="process"]').click();
      }else if(view==='statistics'){
        await page.waitForFunction(()=>!chargingAnalyticsBusy);
      }else if(view==='life'){
        await page.getByRole('button',{name:'查询生活账本',exact:true}).click();
      }else if(view==='quality'){
        await page.getByLabel('质量分析开始日期',{exact:true}).fill('2026-09-18');
        await page.getByLabel('质量分析结束日期',{exact:true}).fill('2026-09-20');
        await page.getByRole('button',{name:'分析数据质量',exact:true}).click();
        await page.waitForSelector('#quality-range');
        await page.waitForFunction(()=>![...document.querySelectorAll('#insights-workspace [role="status"]')].some(el=>el.checkVisibility()&&el.textContent.includes('正在读取时间元数据')));
      }else if(view==='rules'){
        await page.getByRole('button',{name:'读取规则与历史',exact:true}).click();
      }else if(view==='lab'){
        await page.getByRole('button',{name:'读取实验记录',exact:true}).click();
      }else if(view==='tags'){
        await page.locator('#tag-month').fill('2026-09');
        await page.locator('#tag-month').evaluate(el=>el.blur());
        await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
        await page.waitForSelector('[data-tag-event]');
      }else if(view==='routes'){
        await page.locator('#routes-month').fill('2026-09');
        await page.evaluate(()=>document.activeElement?.blur());
        await page.locator('[data-travel="load"]').click();
        await page.waitForSelector('#routes-results');
      }else if(view==='review'){
        await page.locator('#review-date').fill('2026-09-20');
        await page.evaluate(()=>document.activeElement?.blur());
        await page.locator('[data-travel="load"]').click();
        await page.waitForSelector('#usage-review');
      }else if(view==='tracks'||view==='local'){
        await page.locator('[data-source="local"]').first().evaluate(el=>el.click());
        await page.locator('#track-date').fill('2026-09-20');
        await page.locator('[data-action="local-reload"]').click();
        await page.waitForFunction(()=>localTrips?.queried&&!localTrips?.listBusy);
      }
      await page.waitForTimeout(100);
    }
    let checks=0;
    for(const width of [1440,1280]){
      await page.setViewportSize({width,height:600});
      for(const section of sections){
        await navigate(`[data-page="${section}"]`);
        const selector=section==='insights'?'#insights-workspace [data-insight-view]':'.task-navigation [data-section-task]';
        const tools=await page.locator(selector).evaluateAll(els=>els.map(el=>el.dataset.insightView||el.dataset.sectionTask).filter(Boolean));
        const variants=section==='car'?['parameters']:section==='energy'?['statistics']:section==='tracks'?['source:cloud','source:tags']:[];
        for(const tool of [null,...variants,...tools]){
          if(tool){
            const selector=tool==='parameters'&&section==='car'?'[data-vehicle="parameters"]':tool==='statistics'?'[data-action="charging-tab"][data-tab="statistics"]':
              tool.startsWith('source:')?`[data-source="${tool.slice(7)}"]`:section==='insights'?`[data-insight-view="${tool}"]`:`[data-section-task="${tool}"]`;
            await navigate(selector);
          }
          console.log(`CHECK ${width} ${section}/${tool||'main'}`);
          await loadResults(section,tool);
          await page.waitForTimeout(250);
          await page.waitForFunction(()=>!polling&&!busy);
          await page.evaluate(()=>{
            document.querySelectorAll('main details').forEach(el=>el.open=true);
            const control=[...document.querySelectorAll('main input,main select,main summary,main button')].find(el=>!el.disabled&&!el.matches('input[type="date"],input[type="month"]')&&el.checkVisibility());
            control?.focus({preventScroll:true});
            window.scrollTo(0,document.documentElement.scrollHeight-innerHeight);
          });
          const before=await page.evaluate(()=>({scroll:scrollY,details:[...document.querySelectorAll('main details')].filter(el=>el.checkVisibility()).map(el=>({label:el.querySelector('summary')?.textContent,open:el.open}))}));
          await page.evaluate(()=>pollState(true));
          await page.waitForTimeout(200);
          const after=await page.evaluate(()=>({scroll:scrollY,maxScroll:Math.max(0,document.documentElement.scrollHeight-innerHeight),details:[...document.querySelectorAll('main details')].filter(el=>el.checkVisibility()).map(el=>({label:el.querySelector('summary')?.textContent,open:el.open}))}));
          // At the document bottom, a shorter result necessarily clamps scrollY.
          const expectedAfter=Math.min(before.scroll,after.maxScroll);
          if(Math.abs(after.scroll-expectedAfter)>=2)failures.push(`${section}/${tool||'main'} ${width}: refresh scrolled ${before.scroll} -> ${after.scroll}, expected ${expectedAfter}`);
          if(JSON.stringify(after.details)!==JSON.stringify(before.details))failures.push(`${section}/${tool||'main'} ${width}: disclosure state changed`);
          checks++;
          recordsRevision++;
          await page.evaluate(()=>pollState(true));
          await page.waitForTimeout(250);
          const updated=await page.evaluate(()=>({scroll:scrollY,maxScroll:Math.max(0,document.documentElement.scrollHeight-innerHeight),details:[...document.querySelectorAll('main details')].filter(el=>el.checkVisibility()).map(el=>({label:el.querySelector('summary')?.textContent,open:el.open}))}));
          // The next update preserves the reading position after the first refresh.
          const expectedUpdated=Math.min(after.scroll,updated.maxScroll);
          if(Math.abs(updated.scroll-expectedUpdated)>=2)failures.push(`${section}/${tool||'main'} ${width}: record update scrolled ${after.scroll} -> ${updated.scroll}, expected ${expectedUpdated}`);
          if(JSON.stringify(updated.details)!==JSON.stringify(before.details))failures.push(`${section}/${tool||'main'} ${width}: record update lost disclosures`);
          checks++;
        }
      }
    }
    assert.deepEqual(f.errors,[]);
    assert.deepEqual(failures,[],failures.join('\n'));
    console.log(`UI_REFRESH_SCROLL_PASS: ${checks} desktop page and tool refresh checks`);
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
