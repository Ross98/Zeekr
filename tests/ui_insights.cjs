// Real API and browser with synthetic archive only.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const path = require('node:path'), fs = require('node:fs');
(async () => {
  const server = spawn('python3', [path.join(__dirname, 'insights_fixture.py')]);
  let browser;
  try {
    const port = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('Fixture startup timeout')), 10000);
      server.once('error', reject);
      server.stdout.once('data', data => {clearTimeout(timer);resolve(Number(String(data).trim()));});
      server.stderr.on('data', data => process.stderr.write(data));
    });
    browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath:process.env.CHROMIUM_EXECUTABLE} : {})});
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    async function checkContrast(){
      const failures=await page.evaluate(()=>{
        const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
        const blend=(a,b)=>a.slice(0,3).map((v,i)=>v*(a[3]??1)+b[i]*(1-(a[3]??1)));
        const lum=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
        const bad=[];
        for(const el of document.querySelectorAll('#insights-workspace *')){
          if(!el.checkVisibility({checkVisibilityCSS:true}) || el.closest('svg,option,button:disabled') || !Array.from(el.childNodes).some(n=>n.nodeType===3&&n.textContent.trim()))continue;
          const style=getComputedStyle(el),chain=[];let parent=el;
          while(parent){chain.unshift(parent);parent=parent.parentElement;}
          let bg=[255,255,255];for(const ancestor of chain)bg=blend(rgb(getComputedStyle(ancestor).backgroundColor),bg);
          const fg=blend(rgb(style.color),bg),ratio=(Math.max(lum(fg),lum(bg))+.05)/(Math.min(lum(fg),lum(bg))+.05);
          if(ratio<4.5)bad.push({text:el.textContent.slice(0,35),ratio:ratio.toFixed(2)});
        }
        return bad;
      });
      assert.deepEqual(failures,[],'Research text contrast >= 4.5:1');
    }
    const origin = `http://127.0.0.1:${port}`, errors = [], posts = [], external = [];
    page.on('pageerror', e => {errors.push(e.message);console.error('Browser script error:',e.message);});
    page.on('request', r => {if(r.method()==='POST')posts.push(r.url());if(!r.url().startsWith(origin))external.push(r.url());});
    await page.goto(origin);
    await page.getByRole('button', {name:'用车研究',exact:true}).click();
    await page.getByLabel('归档日期', {exact:true}).fill('2026-09-20');
    await page.getByRole('button', {name:'查看归档',exact:true}).click();
    await page.locator('#insight-snapshot').getByText('70%', {exact:true}).waitFor();
    assert.match(await page.locator('#insight-count').innerText(), /120/);
    await page.getByRole('button', {name:'设为对比起点',exact:true}).click();
    await page.getByRole('button', {name:'下一条观测',exact:true}).click();
    await page.locator('#insight-snapshot').getByText('69.99%', {exact:true}).waitFor();
    await page.getByRole('button', {name:'与起点比较',exact:true}).click();
    await page.locator('#insight-comparison [data-change]').first().waitFor();
    assert.match(await page.locator('#insight-comparison').innerText(), /70|69.99/);
    await page.getByRole('button', {name:'加载更多观测',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('#insight-count')?.textContent.includes('126'));
    const slider = page.getByLabel('观测时间轴', {exact:true});
    await slider.focus(); await page.keyboard.press('End');
    await page.locator('#insight-snapshot').getByText('重复缓存', {exact:true}).waitFor();
    await page.getByLabel('搜索历史参数', {exact:true}).fill('swVersion');
    assert.equal(await page.locator('#insight-fields [data-field]').count(), 1);
    assert.equal(await page.locator('#insight-fields img').count(), 0, 'Field text is escaped');
    await page.evaluate(() => render());
    assert.equal(await page.getByLabel('搜索历史参数', {exact:true}).inputValue(), 'swVersion');
    assert.equal(await slider.inputValue(), '125', 'Polling preserves playback selection');
    fs.mkdirSync('/tmp/zeekr-insights-qa', {recursive:true});
    for (const theme of ['light','dark']) {
      await page.getByLabel('外观', {exact:true}).selectOption(theme);
      for (const width of [1440,390,320]) {
        await page.setViewportSize({width,height:1000});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${theme} ${width} overflow`);
        if(width!==320){await checkContrast();await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0)});await page.screenshot({path:`/tmp/zeekr-insights-qa/time-machine-${theme}-${width}.png`,fullPage:true});await page.screenshot({path:`/tmp/zeekr-insights-qa/time-machine-${theme}-${width}-viewport.png`});}
      }
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.evaluate(() => {document.documentElement.style.zoom='2';});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, '200% zoom overflow');
    await page.evaluate(() => {document.documentElement.style.zoom='';});
    await page.getByLabel('归档日期', {exact:true}).fill('2026-09-21');
    await page.getByRole('button', {name:'查看归档',exact:true}).click();
    await page.getByText('这一天还没有归档观测', {exact:true}).waitFor();
    // An older request must not replace a newly selected day.
    let release;
    await page.route('**/api/insights/timeline?date=2026-09-19', async route => {
      await new Promise(resolve => {release=resolve;});
      await route.fulfill({json:{date:'2026-09-19',items:[],next_cursor:null,context:await page.evaluate(()=>state.insights_context)}});
    });
    await page.getByLabel('归档日期', {exact:true}).fill('2026-09-19');
    const oldRequest=page.waitForRequest('**/api/insights/timeline?date=2026-09-19');
    await page.getByRole('button', {name:'查看归档',exact:true}).click();
    await oldRequest;
    await page.getByLabel('归档日期', {exact:true}).fill('2026-09-20');
    await page.getByRole('button', {name:'查看归档',exact:true}).click();
    await page.locator('#insight-snapshot').getByText('70%', {exact:true}).waitFor();
    const oldResponse=page.waitForResponse('**/api/insights/timeline?date=2026-09-19');
    release();
    await oldResponse;
    assert.match(await page.locator('#insight-count').innerText(), /120/);
    const response = await page.request.get(origin+'/api/insights/snapshot?id=202609.1');
    const raw = await response.text();
    for(const secret of ['NEVER-EXPORT','latitude','longitude','111600000'])assert.ok(!raw.includes(secret));
    await page.getByRole('button', {name:'停车耗电',exact:true}).click();
    await page.getByLabel('开始日期', {exact:true}).fill('2026-09-18');
    await page.getByLabel('结束日期', {exact:true}).fill('2026-09-19');
    await page.getByRole('button', {name:'分析停车观测',exact:true}).click();
    await page.locator('[data-parking-session]').first().waitFor();
    assert.equal(await page.locator('[data-parking-session]').count(), 1);
    assert.match(await page.locator('[data-parking-session]').innerText(), /可比较|跨夜/);
    await page.getByRole('button', {name:'查看区间详情',exact:true}).click();
    assert.match(await page.locator('#parking-detail').innerText(), /108|5 分钟|300 秒/);
    await page.getByRole('button', {name:'比较停车端点参数',exact:true}).click();
    await page.locator('#parking-compare [data-parking-change]').first().waitFor();
    await page.getByLabel('停车时段', {exact:true}).selectOption('multi_day');
    await page.getByText('没有符合筛选的停车区间', {exact:true}).waitFor();
    await page.getByLabel('停车时段', {exact:true}).selectOption('overnight');
    assert.equal(await page.locator('[data-parking-session]').count(), 1);
    await page.evaluate(() => render());
    assert.equal(await page.getByLabel('停车时段', {exact:true}).inputValue(), 'overnight');
    for(const theme of ['light','dark']){
      await page.getByLabel('外观', {exact:true}).selectOption(theme);
      for(const width of [1440,390,320]){
        await page.setViewportSize({width,height:1000});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`parking ${theme} ${width}`);
        if(width!==320){await checkContrast();await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0)});await page.screenshot({path:`/tmp/zeekr-insights-qa/parking-${theme}-${width}.png`,fullPage:true});await page.screenshot({path:`/tmp/zeekr-insights-qa/parking-${theme}-${width}-viewport.png`});}
      }
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.evaluate(()=>{document.documentElement.style.zoom='2'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'parking 200% zoom');
    await page.evaluate(()=>{document.documentElement.style.zoom=''});
    await page.route('**/api/insights/parking?*',route=>route.fulfill({status:500,json:{error:'合成读取失败'}}));
    await page.getByRole('button', {name:'分析停车观测',exact:true}).click();
    await page.getByText(/合成读取失败/).waitFor();
    assert.equal(await page.locator('[data-parking-session]').count(),1,'Failure retains prior range and result');
    assert.deepEqual(posts, []);assert.deepEqual(external, []);assert.deepEqual(errors, []);
    console.log('UI_INSIGHTS_PASS: time machine paging/slider/comparison/stale replies; parking range/filter/details/endpoint comparison/error preservation; privacy/themes/mobile/zoom; no cloud requests');
  } finally {if(browser)await browser.close();server.kill();}
})().catch(e => {console.error(e);process.exitCode=1;});
