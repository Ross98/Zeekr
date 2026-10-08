const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
async function fixture({demo=false,partialCharge=false,automatic=false}={}){
  const server=spawn('python3',[path.join(__dirname,'insights_fixture.py'),...(demo?['--demo']:[]),...(partialCharge?['--partial-charge']:[]),...(automatic?['--automatic']:[])]);
  let browser;
  try{
    const port=await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('Fixture startup timeout')),10000);
      const fail=error=>{clearTimeout(timer);reject(error);};
      server.once('error',fail);server.once('exit',code=>fail(Error(`Fixture exited ${code}`)));
      server.stdout.once('data',data=>{clearTimeout(timer);resolve(Number(String(data).trim()));});
      server.stderr.on('data',data=>process.stderr.write(data));
    });
    browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),origin=`http://127.0.0.1:${port}`;
    const errors=[],posts=[],external=[];
    page.on('pageerror',e=>{errors.push(e.message);console.error('Browser script error:',e.message);});
    page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());if(!r.url().startsWith(origin)&&!r.url().startsWith('data:'))external.push(r.url());});
    page.on('requestfailed',r=>console.error('Browser request failed:',new URL(r.url()).pathname,r.failure()?.errorText));
    await page.goto(origin);
    try{await page.getByRole('button',{name:'用车研究',exact:true}).click();}
    catch(error){console.error('Fixture startup diagnostic:',await page.evaluate(()=>({ready:document.readyState,scripts:[...document.scripts].map(s=>s.src),text:document.body.innerText.slice(0,700),timing:performance.getEntriesByType('resource').map(r=>({name:new URL(r.name).pathname,duration:r.duration}))})));throw error;}
    return {page,browser,origin,errors,posts,external,close:async()=>{await browser.close();server.kill();}};
  }catch(error){if(browser)await browser.close();server.kill();throw error;}
}
async function contrast(page,scope='#insights-workspace'){
  const bad=await page.evaluate(scope=>{
    const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
    const blend=(a,b)=>a.slice(0,3).map((v,i)=>v*(a[3]??1)+b[i]*(1-(a[3]??1)));
    const lum=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
    const failures=[];
    for(const el of document.querySelectorAll(`${scope} *`)){
      if(!el.checkVisibility({checkVisibilityCSS:true})||el.closest('svg,option,button:disabled')||!Array.from(el.childNodes).some(n=>n.nodeType===3&&n.textContent.trim()))continue;
      const style=getComputedStyle(el),chain=[];let p=el;
      while(p){chain.unshift(p);p=p.parentElement;}
      let bg=[255,255,255];for(const parent of chain)bg=blend(rgb(getComputedStyle(parent).backgroundColor),bg);
      const fg=blend(rgb(style.color),bg),ratio=(Math.max(lum(fg),lum(bg))+.05)/(Math.min(lum(fg),lum(bg))+.05);
      if(ratio<4.5)failures.push({text:el.textContent.slice(0,30),ratio:ratio.toFixed(2)});
    }return failures;
  },scope);
  assert.deepEqual(bad,[],'Visible non-disabled text contrast >=4.5:1');
}
async function layouts(page,name){
  const directory='/tmp/zeekr-insights-qa';fs.mkdirSync(directory,{recursive:true});
  for(const theme of ['light','dark']){
    await page.getByLabel('外观',{exact:true}).selectOption(theme);
    for(const width of (process.env.DESKTOP_ONLY? [1440,1280,1024] : [1440,390,320])){
      await page.setViewportSize({width,height:1000});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${name} ${theme} ${width} overflow`);
      if(width!==320){
        await contrast(page);await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});
        await page.screenshot({path:`${directory}/${name}-${theme}-${width}.png`,fullPage:true});
        await page.screenshot({path:`${directory}/${name}-${theme}-${width}-viewport.png`});
      }
    }
  }
  await page.setViewportSize({width:process.env.DESKTOP_ONLY?2560:1440,height:1000});await page.evaluate(()=>{document.documentElement.style.zoom='2';});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${name} 200% zoom overflow`);
  await page.evaluate(()=>{document.documentElement.style.zoom='';});
}
module.exports={fixture,layouts,contrast};
