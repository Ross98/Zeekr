// Offline appearance verification; synthetic fixture only, no owner data or vehicle requests.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const server=spawn('python3',[path.join(__dirname,'web_fixture.py')]);let browser;
 try{
  const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('fixture timeout')),10000);server.stdout.once('data',d=>{clearTimeout(timer);resolve(Number(String(d).trim()))});server.once('error',reject)});
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
  const context=await browser.newContext({colorScheme:'dark',viewport:{width:1440,height:1000}});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const origin=`http://127.0.0.1:${port}`;
  await page.goto(origin);await page.getByRole('heading',{name:'总览',exact:true}).waitFor();
  assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
  await page.getByLabel('外观',{exact:true}).selectOption('light');
  await page.emulateMedia({colorScheme:'dark'});assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  await page.reload();assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  const other=await context.newPage();await other.goto(origin);
  await other.getByLabel('外观',{exact:true}).selectOption('dark');await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');
  await other.getByLabel('外观',{exact:true}).selectOption('system');await page.emulateMedia({colorScheme:'light'});await page.waitForFunction(()=>document.documentElement.dataset.theme==='light');
  await page.emulateMedia({colorScheme:'dark'});await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');await other.close();
  await page.getByRole('button',{name:'刷新状态',exact:true}).click();await page.getByText('64%',{exact:true}).first().waitFor();
  await page.evaluate(()=>{window.__originalMain=document.querySelector('main');window.__renderCount=generation;});
  await page.getByLabel('外观',{exact:true}).selectOption('light');await page.getByLabel('外观',{exact:true}).selectOption('dark');
  assert.equal(await page.evaluate(()=>window.__originalMain===document.querySelector('main')&&window.__renderCount===generation),true,'theme must not re-render or fetch vehicle state');
  fs.mkdirSync('/tmp/zeekr-night-qa',{recursive:true});
  const pages=['overview','car','energy','map','tracks','fields','settings','more'];
  for(const width of [1440,1280,1024,390,320]){
   await page.setViewportSize({width,height:1000});
   for(const name of pages){
    await page.evaluate(name=>{page=name;render()},name);
    await page.waitForTimeout(80);
    // The fixture has no external map consent and the theme never grants it.
    const overflow=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    if(overflow.scroll>overflow.width)console.log(await page.evaluate(()=>[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>({class:e.className,w:e.getBoundingClientRect().width,text:e.innerText?.slice(0,50)})).slice(0,20)));
    assert.ok(overflow.scroll<=overflow.width,`${name} overflow at ${width}: ${JSON.stringify(overflow)}`);
    if(width===1440||width===390)await page.screenshot({path:`/tmp/zeekr-night-qa/${name}-${width}.png`,fullPage:true});
    const failures=await page.evaluate(()=>{
     const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
     const blend=(a,b)=>a.slice(0,3).map((v,i)=>v*(a[3]??1)+b[i]*(1-(a[3]??1)));
     const lum=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
     const bad=[];
     for(const el of document.querySelectorAll('main *,header *,nav *,footer')){
      if(!el.checkVisibility({checkVisibilityCSS:true})||el.closest('svg,option')||!Array.from(el.childNodes).some(n=>n.nodeType===3&&n.textContent.trim()))continue;
      const style=getComputedStyle(el),chain=[];let node=el;
      while(node){chain.unshift(node);node=node.parentElement}
      let bg=[17,25,29];for(const n of chain)bg=blend(rgb(getComputedStyle(n).backgroundColor),bg);
      const fg=blend(rgb(style.color),bg),ratio=(Math.max(lum(fg),lum(bg))+.05)/(Math.min(lum(fg),lum(bg))+.05);
      if(ratio<4.5)bad.push({tag:el.tagName,cls:el.className,text:el.textContent.trim().slice(0,30),ratio:ratio.toFixed(2)});
     }return bad.slice(0,15);
    });
    assert.deepEqual(failures,[],`${name} contrast at ${width}`);
   }
  }
  // A 1440px display at 200% browser zoom has a 720px CSS viewport.
  // CSS zoom is not equivalent: it does not change media-query breakpoints.
  await page.setViewportSize({width:720,height:500});
  for(const name of pages){await page.evaluate(name=>{page=name;render()},name);await page.waitForTimeout(50);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'200% viewport reflow '+name)}
  // Preserve field search through appearance changes.
  await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>{page='fields';render()});
  await page.getByLabel('搜索参数').fill('sunroof');await page.getByLabel('外观',{exact:true}).selectOption('light');
  assert.equal(await page.getByLabel('搜索参数').inputValue(),'sunroof');
  // Same-origin login preview exercises actual shipped login markup and CSP-compatible resources.
  await page.route('**/__login',route=>route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'../zeekr_control/static/login.html'),'utf8')}));
  await page.goto(origin+'/__login');await page.getByLabel('访问密码').fill('synthetic-input');
  await page.getByLabel('外观',{exact:true}).selectOption('dark');assert.equal(await page.getByLabel('访问密码').inputValue(),'synthetic-input');
  await page.setViewportSize({width:320,height:800});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:'/tmp/zeekr-night-qa/login-320.png',fullPage:true});
  // Storage disabled must not block first load or manual appearance selection.
  const blocked=await browser.newContext({colorScheme:'dark'});await blocked.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw new DOMException('blocked','SecurityError')}}));
  const blockedPage=await blocked.newPage();await blockedPage.goto(origin);await blockedPage.getByLabel('外观',{exact:true}).selectOption('light');
  assert.equal(await blockedPage.locator('html').getAttribute('data-theme'),'light');await blocked.close();
  assert.deepEqual(errors,[]);console.log('UI_THEME_PASS: system/override/reload/multitab/storage fallback; login; 8 pages x 5 widths; dark text contrast; input preservation');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
