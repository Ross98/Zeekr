const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const readline=require('node:readline');
const path=require('node:path'),fs=require('node:fs');
const {chromium}=require('playwright');
const {contrast}=require('./ui_insight_helpers.cjs');
const {startEvidence}=require('../scripts/browser-failure-evidence.cjs');

(async()=>{
 const server=spawn('python3',[path.join(__dirname,'remembered_auth_fixture.py')]);
 const lines=readline.createInterface({input:server.stdout});
 const nextLine=()=>new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>{lines.off('line',ready);reject(Error('Fixture timeout'));},10000);
  const ready=line=>{clearTimeout(timer);resolve(line);};lines.once('line',ready);
 });
 server.stderr.on('data',data=>process.stderr.write(data));
 let browser,evidence;
 try{
  const port=Number(await nextLine()),origin=`http://127.0.0.1:${port}`;
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
  const context=await browser.newContext(),page=await context.newPage(),errors=[];
  evidence=await startEvidence(page,{testId:'ui_remembered_auth',synthetic:true});
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(origin);
  assert.equal(await page.locator('#remember').inputValue(),'0');
  assert.equal(await page.locator('#remember option').count(),3);
  const directory='/tmp/zeekr-remembered-auth-qa';fs.mkdirSync(directory,{recursive:true});
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1440,1100]){
    await page.setViewportSize({width,height:900});
    for(const days of ['0','7','30']){
     await page.getByLabel('下次免输密码').selectOption(days);
     assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
     assert.match(await page.locator('#remember-help').textContent(),days==='0'?/每次登录/:/同一 IP/);
    }
    await contrast(page,'main');
    if(width!==320)await page.screenshot({path:`${directory}/login-${theme}-${width}.png`,fullPage:true});
   }
  }
  await page.getByLabel('访问密码').fill('wrong');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#error').textContent.includes('密码错误'));
  assert.equal(await page.getByRole('button',{name:'登录',exact:true}).isEnabled(),true);
  for(const days of ['7','30']){
   const isolated=await browser.newContext(),login=await isolated.newPage();
   login.on('pageerror',error=>errors.push(error.message));
   await login.goto(origin);
   await login.getByLabel('下次免输密码').selectOption(days);
   await login.getByLabel('访问密码').fill('synthetic browser password');
   const issued=login.waitForResponse(response=>response.url()===`${origin}/auth/login`);
   await login.getByRole('button',{name:'登录',exact:true}).click();
   assert.equal((await issued).status(),200);
   await login.waitForSelector('#logout');
   const cookie=(await isolated.cookies()).find(cookie=>cookie.name==='zeekr_session');
   assert.equal(cookie.httpOnly,true);assert.equal(cookie.sameSite,'Strict');
   assert.ok(Math.abs(cookie.expires-Date.now()/1000-Number(days)*86400)<10);
   assert.equal(await login.evaluate(()=>localStorage.getItem('password')),null);
   assert.ok(!(await login.evaluate(()=>document.cookie)).includes('zeekr_session'));
   const restarted=nextLine();server.stdin.write('restart\n');assert.equal(await restarted,'restarted');
   await login.reload();await login.waitForSelector('#logout');
   const anonymous=await browser.newContext(),stranger=await anonymous.newPage();
   await stranger.goto(origin);assert.equal(await stranger.locator('#password').count(),1);
   await anonymous.close();
   // Same IP with another browser identifier must still require the password.
   await isolated.setExtraHTTPHeaders({'User-Agent':'Different Synthetic Browser'});
   assert.equal((await isolated.request.get(`${origin}/api/state`)).status(),401);
   await isolated.setExtraHTTPHeaders({});
   if(days==='7'){
    let release,attempts=0;
    const pending=new Promise(resolve=>{release=resolve;});
    await login.route('**/auth/logout',async route=>{
     attempts++;await pending;
     await route.fulfill({status:503,json:{error:'合成撤销故障，请稍后重试。'}});
    });
    try{
     await login.locator('#logout').click();
     assert.equal(await login.locator('#logout').isDisabled(),true,'pending logout blocks duplicate submissions');
     await login.locator('#logout').evaluate(button=>button.click());
    }finally{release();}
    await login.waitForFunction(()=>!document.querySelector('#toast').hidden&&document.querySelector('#toast').textContent.includes('合成撤销故障'));
    assert.equal(attempts,1);
    assert.equal(await login.locator('#logout').isEnabled(),true);
    assert.equal((await isolated.request.get(`${origin}/api/state`)).status(),200,'a rejected logout keeps the existing session');
    await login.unroute('**/auth/logout');
    await login.route('**/auth/logout',route=>route.abort());
    await login.locator('#logout').click();
    await login.waitForFunction(()=>!document.querySelector('#toast').hidden&&document.querySelector('#toast').textContent.includes('连接失败'));
    assert.equal(await login.locator('#logout').isEnabled(),true);
    assert.ok((await isolated.cookies()).some(value=>value.name==='zeekr_session'));
    await login.unroute('**/auth/logout');
   }
   if(days==='30'){
    let release,heldRequest;
    const pending=new Promise(resolve=>{release=resolve;});
    await login.route('**/auth/logout',async route=>{
     heldRequest=route.request();await pending;
     if(!heldRequest.failure())await route.abort();
    });
    try{
     const aborted=login.waitForEvent('requestfailed',{predicate:request=>new URL(request.url()).pathname==='/auth/logout',timeout:12000});
     await login.locator('#logout').click();
     await login.waitForFunction(()=>!document.querySelector('#toast').hidden&&document.querySelector('#toast').textContent.includes('响应超时'),{},{timeout:12000});
     assert.equal(await login.locator('#logout').isEnabled(),true);
     await aborted;
     assert.ok(heldRequest.failure(),'timeout aborts the held request');
     assert.ok((await isolated.cookies()).some(value=>value.name==='zeekr_session'));
    }finally{release();}
    await login.unroute('**/auth/logout');
   }
   await login.getByRole('button',{name:'退出登录',exact:true}).click();
   await login.waitForSelector('#password');
   assert.ok(!(await isolated.cookies()).some(cookie=>cookie.name==='zeekr_session'));
   await isolated.addCookies([cookie]);
   assert.equal((await isolated.request.get(`${origin}/api/state`)).status(),401,'logout revokes copied cookie');
   await isolated.close();
  }
  // A normal twelve-hour session must disappear when the server restarts.
  await page.reload();await page.getByLabel('访问密码').fill('synthetic browser password');
  await page.getByRole('button',{name:'登录',exact:true}).click();await page.waitForSelector('#logout');
  const restarted=nextLine();server.stdin.write('restart\n');assert.equal(await restarted,'restarted');
  await page.reload();await page.waitForSelector('#password');
  let releaseLogin;
  const pendingLogin=new Promise(resolve=>{releaseLogin=resolve;});
  await page.route('**/auth/login',async route=>{
   await pendingLogin;
   if(!route.request().failure())await route.abort().catch(error=>{if(!error.message.includes('already handled'))throw error;});
  });
  await page.getByLabel('访问密码').fill('synthetic browser password');
  await page.evaluate(()=>{
   window.__originalLoginFetch=window.fetch;window.__loginRequests=0;
   window.fetch=(url,options)=>{if(String(url).endsWith('/auth/login'))window.__loginRequests++;return window.__originalLoginFetch(url,options);};
  });
  try{
   const aborted=page.waitForEvent('requestfailed',{predicate:request=>new URL(request.url()).pathname==='/auth/login',timeout:12000});
   aborted.catch(()=>{});
   await page.getByRole('button',{name:'登录',exact:true}).click();
   const pending=await page.evaluate(()=>{
    document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
    return {requests:window.__loginRequests,passwordDisabled:document.querySelector('#password').disabled,rememberDisabled:document.querySelector('#remember').disabled};
   });
   assert.deepEqual(pending,{requests:1,passwordDisabled:true,rememberDisabled:true},'pending credentials stay frozen and duplicate submissions cannot create another session');
   await page.waitForFunction(()=>document.querySelector('#error').textContent.includes('响应超时'),{},{timeout:12000});
   await aborted;
   assert.match(await page.locator('#error').innerText(),/结果尚未确认/);
   assert.equal(await page.getByRole('button',{name:'登录',exact:true}).isEnabled(),true);
   assert.equal(await page.getByLabel('访问密码').isEnabled(),true);
   assert.equal(await page.getByLabel('下次免输密码').isEnabled(),true);
  }finally{
   releaseLogin();await page.unroute('**/auth/login');
   await page.evaluate(()=>{window.fetch=window.__originalLoginFetch;delete window.__originalLoginFetch;});
  }
  await page.route('**/auth/login',route=>route.abort());
  await page.getByLabel('访问密码').fill('synthetic browser password');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#error').textContent.includes('连接失败'));
  assert.match(await page.locator('#error').innerText(),/结果尚未确认/);
  assert.equal(await page.getByRole('button',{name:'登录',exact:true}).isEnabled(),true);
  await page.unroute('**/auth/login');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.waitForSelector('#logout');
  assert.deepEqual(errors,[]);
  console.log('Remembered login: real cookies, restart, logout, browser isolation, default expiry, error recovery and layouts PASS');
 }catch(error){if(evidence)await evidence.fail(error);throw error;}finally{if(evidence)await evidence.finish();if(browser)await browser.close();lines.close();server.stdin.end();server.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
