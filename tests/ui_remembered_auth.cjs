const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const readline=require('node:readline');
const path=require('node:path'),fs=require('node:fs');
const {chromium}=require('playwright');
const {contrast}=require('./ui_insight_helpers.cjs');

(async()=>{
 const server=spawn('python3',[path.join(__dirname,'remembered_auth_fixture.py')]);
 const lines=readline.createInterface({input:server.stdout});
 const nextLine=()=>new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>{lines.off('line',ready);reject(Error('Fixture timeout'));},10000);
  const ready=line=>{clearTimeout(timer);resolve(line);};lines.once('line',ready);
 });
 server.stderr.on('data',data=>process.stderr.write(data));
 let browser;
 try{
  const port=Number(await nextLine()),origin=`http://127.0.0.1:${port}`;
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{channel:'chrome'})});
  const context=await browser.newContext(),page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(origin);
  assert.equal(await page.locator('#remember').inputValue(),'0');
  assert.equal(await page.locator('#remember option').count(),3);
  const directory='/tmp/zeekr-remembered-auth-qa';fs.mkdirSync(directory,{recursive:true});
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1440,390,320]){
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
  await page.route('**/auth/login',route=>route.abort());
  await page.getByLabel('访问密码').fill('synthetic browser password');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#error').textContent==='连接失败，请重试。');
  assert.equal(await page.getByRole('button',{name:'登录',exact:true}).isEnabled(),true);
  assert.deepEqual(errors,[]);
  console.log('Remembered login: real cookies, restart, logout, browser isolation, default expiry, error recovery and layouts PASS');
 }finally{if(browser)await browser.close();lines.close();server.stdin.end();server.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
