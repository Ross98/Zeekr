// Synthetic fixture only; never opens an owner session or calls a real vehicle.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const root=require('node:path').resolve(__dirname,'..');
const output='/tmp/zeekr-tyre-display-qa';
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const server=spawn('python3',[root+'/tests/web_fixture.py'],{cwd:root});
 let browser;
 try {
 const port=await new Promise((resolve,reject)=>{server.stdout.once('data',d=>resolve(Number(String(d).trim())));server.once('error',reject);});
 browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1200},deviceScaleFactor:2});
 await page.goto('http://127.0.0.1:'+port);
 await page.getByRole('button',{name:'刷新状态',exact:true}).click();
 await page.getByText('64%',{exact:true}).first().waitFor();
 await page.locator('.sidebar [data-page="car"]').click();
 await page.locator('#vehicle-overview').click();
 await page.locator('.car-tyres').waitFor();
 await page.evaluate(()=>{state.profile.image='/car.svg';render();});
 await page.locator('.car-tyre-art img').evaluate(img=>img.decode());
 const assert=require('node:assert/strict');
 assert.equal(await page.locator('.car-tyre-reading').count(),4);
 assert.equal(await page.locator('.car-tyre-diagram svg').count(),0);
 assert.equal(await page.locator('.car-tyre-time,.car-tyre-note').count(),0);
 const asset=await page.request.get('http://127.0.0.1:'+port+'/car-001-top.png');assert.equal(asset.status(),200);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.evaluate(()=>{const p=['右前','右后','左前','左后'];state.model.tyres=p.map((name,i)=>({name,pressure:["251.123 kPa","262.456 kPa","273.789 kPa","未知"][i],temperature:'27 °C'}));render();});
 for(const [cls,value] of [['rf','251.123'],['rr','262.456'],['lf','273.789'],['lr','未知']])assert.equal(await page.locator('.car-tyre-'+cls+' strong').innerText(),value);
 assert.equal(await page.locator('.car-tyre-lr .car-tyre-unit').count(),0);
 await page.evaluate(()=>{state.model.tyres.forEach(t=>t.pressure='265.125 kPa');render();});
 await page.locator('.car-tyre-art img').evaluate(img=>img.decode());
 await page.locator('.car-tyres').screenshot({path:output+'/after.png'});
 await page.locator('.car-main-grid').screenshot({path:output+'/in-page.png'});
 for(const width of [1440,390])for(const theme of ['light','dark']) {
 await page.setViewportSize({width,height:1200});
 await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 const box=await page.locator('.car-tyre-diagram').boundingBox();
 for(const reading of await page.locator('.car-tyre-reading').all()){const r=await reading.boundingBox();assert.ok(r.y+r.height<=box.y+box.height+1,'All readings fit');}
 await page.locator('.car-tyres').screenshot({path:output+'/'+width+'-'+theme+'.png'});
 }
 await page.setViewportSize({width:1440,height:1200});
 await page.locator('.sidebar [data-page="overview"]').click();
 assert.equal(await page.locator('.overview-health .car-tyre-reading').count(),4);
 await page.locator('.overview-health .car-tyre-art img').evaluate(img=>img.decode());
 await page.locator('.overview-health').screenshot({path:output+'/homepage.png'});
 assert.deepEqual(errors,[]);
 console.log('TYRE_UI_PASS: wheel mapping, unknowns, image route, 4 viewport/theme checks');
 console.log(JSON.stringify({output,cardWidth:await page.locator('.overview-health .car-tyre-diagram').evaluate(el=>el.clientWidth),overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)}));
 } finally {if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
