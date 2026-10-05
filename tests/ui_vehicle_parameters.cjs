// Real local projection and UI, synthetic fixture only; no owner session or cloud.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const server=spawn('python3',[path.join(__dirname,'web_fixture.py')]);let browser;
 try{
  const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture timeout')),10000);server.stdout.once('data',d=>{clearTimeout(timer);resolve(Number(String(d).trim()))});server.once('error',reject)});
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],external=[],posts=[];
  const origin=`http://127.0.0.1:${port}`;
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith(origin))external.push(r.url());if(r.method()==='POST')posts.push(r.url())});
  await page.goto(origin);await page.getByRole('button',{name:'车辆',exact:true}).first().click();
  await page.locator('.vehicle-table').waitFor();assert.match(await page.locator('.vehicle-intro').innerText(),/目录 217 项 · 本次返回 0 项/);
  assert.equal(posts.length,0,'Opening full directory never refreshes the cloud');
  await page.getByRole('button',{name:'刷新状态',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.vehicle-intro')?.textContent.includes('本次返回 0 项'));
  const catalog=await page.evaluate(()=>fetch('/api/vehicle/parameters').then(r=>r.json()));
  assert.equal(catalog.fields.length,217);assert.equal(catalog.groups.length,14);
  const seen=[];
  do {
   seen.push(...await page.locator('[data-parameter]').evaluateAll(nodes=>nodes.map(n=>n.dataset.parameter)));
   if(await page.locator('#vehicle-next').isDisabled())break;
   await page.locator('#vehicle-next').click();
  }while(true);
  assert.equal(seen.length,217);assert.equal(new Set(seen).size,217);
  assert.deepEqual(new Set(seen),new Set(catalog.fields.map(f=>f.path)));
  assert.ok(!seen.some(p=>/(?:^|\.)(?:vin|longitude|latitude|token|password)$/i.test(p)),'No private fields in full directory');
  await page.locator('#vehicle-reset').click();
  await page.getByLabel('搜索参数',{exact:true}).fill('engineHood');
  assert.equal(await page.locator('[data-parameter]').count(),1);
  assert.match(await page.locator('.vehicle-table').innerText(),/关闭/);assert.doesNotMatch(await page.locator('.vehicle-table').innerText(),/人工确认/);
  assert.equal(await page.locator('[data-label="原始值"]').innerText(),'0');
  await page.locator('summary').filter({hasText:'字段说明'}).focus();await page.keyboard.press('Enter');
  await page.evaluate(()=>render());assert.equal(await page.locator('details[data-detail][open]').count(),1);
  await page.locator('#vehicle-search').focus();await page.locator('#vehicle-search').evaluate(el=>el.setSelectionRange(el.value.length,el.value.length));await page.keyboard.type('Open');
  assert.equal(await page.locator('#vehicle-search').inputValue(),'engineHoodOpen');assert.equal(await page.locator('#vehicle-search').evaluate(el=>el===document.activeElement),true);
  await page.getByLabel('外观',{exact:true}).selectOption('dark');assert.equal(await page.locator('#vehicle-search').inputValue(),'engineHoodOpen');
  await page.locator('#vehicle-group').selectOption('轮胎与保养');assert.equal(await page.locator('[data-parameter]').count(),0);assert.match(await page.locator('.vehicle-empty').innerText(),/没有匹配/);
  await page.locator('#vehicle-reset').click();
  for(const group of catalog.groups){await page.locator('#vehicle-group').selectOption(group.name);assert.match(await page.locator('.vehicle-results').innerText(),new RegExp(`匹配 ${group.count} 项`))}
  await page.locator('#vehicle-reset').click();
  for(const status of ['known','pending','missing','empty','invalid']){await page.locator('#vehicle-status').selectOption(status);assert.equal(await page.locator('[data-parameter]').count(),Math.min(20,catalog.counts[status]))}
  await page.locator('#vehicle-reset').click();
  fs.mkdirSync('/tmp/zeekr-vehicle-qa',{recursive:true});
  async function contrast(){const failures=await page.evaluate(()=>{
     const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
     const blend=(a,b)=>a.slice(0,3).map((v,i)=>v*(a[3]??1)+b[i]*(1-(a[3]??1)));
     const lum=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
     const bad=[];
     for(const el of document.querySelectorAll('.vehicle-catalog *, .vehicle-tabs *, .car-summary *, .car-main-grid *, .car-data *')){
      if(!el.checkVisibility({checkVisibilityCSS:true})||el.closest('svg,option')||!Array.from(el.childNodes).some(n=>n.nodeType===3&&n.textContent.trim()))continue;
      const style=getComputedStyle(el),chain=[];let node=el;
      while(node){chain.unshift(node);node=node.parentElement}
      let bg=getComputedStyle(document.documentElement).colorScheme==='dark'?[17,25,29]:[255,255,255];for(const n of chain)bg=blend(rgb(getComputedStyle(n).backgroundColor),bg);
      const fg=blend(rgb(style.color),bg),ratio=(Math.max(lum(fg),lum(bg))+.05)/(Math.min(lum(fg),lum(bg))+.05);
      if(ratio<4.5)bad.push({tag:el.tagName,cls:el.className,text:el.textContent.trim().slice(0,30),ratio:ratio.toFixed(2)});
     }return bad.slice(0,15);
    });
    assert.deepEqual(failures,[],'Vehicle text contrast');}

  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1440,1280,1024,720,390,320]){
    await page.setViewportSize({width,height:1000});
    if(width===1440||width===390)await contrast();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${theme} catalog overflow at ${width}`);
    const small=await page.locator('.vehicle-filters input,.vehicle-filters select,.vehicle-pagination button,.vehicle-tabs button').evaluateAll(nodes=>nodes.filter(n=>n.getBoundingClientRect().height<44).map(n=>n.id));assert.deepEqual(small,[]);
    if(width===1440||width===390){await page.evaluate(()=>{document.querySelector('#toast').hidden=true;document.activeElement?.blur();window.scrollTo(0,0)});await page.screenshot({path:`/tmp/zeekr-vehicle-qa/parameters-${theme}-${width}.png`,fullPage:true});await page.screenshot({path:`/tmp/zeekr-vehicle-qa/parameters-${theme}-${width}-viewport.png`});}
    await page.locator('#vehicle-overview').click();
    if(width===1440||width===390)await contrast();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${theme} overview overflow at ${width}`);
    if(width<621){const boxes=await page.locator('.car-door').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().x));assert.equal(new Set(boxes).size,1,'Mobile doors in one column')}
    if(width===1440||width===390)await page.screenshot({path:`/tmp/zeekr-vehicle-qa/overview-${theme}-${width}.png`,fullPage:true});
    await page.locator('#vehicle-parameters').click();
   }
  }
  await page.locator('#vehicle-overview').click();
  assert.match(await page.locator('#car-hood').innerText(),/关闭/);
  await page.evaluate(()=>{state.model.hood='未知';render();});
  await page.locator('.car-pending summary').click();await page.getByRole('button',{name:'前舱盖 · 未知',exact:true}).click();
  assert.equal(await page.evaluate(()=>document.activeElement.id),'car-hood');
  await page.locator('#vehicle-parameters').click();
  // Refresh failure retains exact readings and times; filters survive application renders.
  await page.locator('#vehicle-search').fill('engineHood');
  const before=await page.locator('.vehicle-table').innerText();
  await page.route('**/api/refresh',route=>route.fulfill({status:502,json:{error:'合成刷新失败'}}));
  await page.getByRole('button',{name:'刷新状态',exact:true}).click();await page.getByText(/合成刷新失败/).first().waitFor();
  assert.equal(await page.locator('.vehicle-table').innerText(),before);assert.equal(await page.locator('#vehicle-search').inputValue(),'engineHood');
  assert.equal(posts.length,2,'Only the two explicit refresh clicks post');assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  console.log('UI_VEHICLE_PARAMETERS_PASS: all 217 rows, 14 groups, filters, paging, focus/details, 24 theme/view/width layouts, source semantics, failed refresh, no unsolicited cloud requests');
 }finally{if(browser)await browser.close();server.kill()}
})().catch(e=>{console.error(e);process.exitCode=1});
