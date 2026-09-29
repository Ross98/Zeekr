const assert=require('node:assert/strict');
const fs=require('node:fs');
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
function pngWithMetadata(png){
  const body=Buffer.from('Comment\0SYNTHETIC-PHOTO-SECRET'),type=Buffer.from('tEXt');
  const data=Buffer.concat([type,body]);let crc=0xffffffff;
  for(const byte of data){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^(crc&1?0xedb88320:0);}
  const chunk=Buffer.alloc(body.length+12);chunk.writeUInt32BE(body.length);data.copy(chunk,4);chunk.writeUInt32BE((crc^0xffffffff)>>>0,chunk.length-4);
  return Buffer.concat([png.subarray(0,png.length-12),chunk,png.subarray(png.length-12)]);
}
(async()=>{
  const f=await fixture(),{page}=f;
  try{
    await page.getByRole('button',{name:'行程与轨迹',exact:true}).first().click();
    await page.getByRole('button',{name:'行程卡片',exact:true}).click();
    await page.getByLabel('卡片记录月份',{exact:true}).fill('2026-09');
    await page.getByRole('button',{name:'读取卡片素材',exact:true}).click();
    await page.getByLabel('卡片行程',{exact:true}).selectOption('report-trip');
    await page.getByLabel('卡片标题',{exact:true}).fill('合成周末出行 <img src=x onerror=alert(1)>');
    await page.getByLabel('卡片备注',{exact:true}).fill(('沿途记录，保留当时心情。\n').repeat(20));
    assert.equal(await page.getByLabel('显示手填地点',{exact:true}).isChecked(),false);
    await page.getByLabel('显示手填地点',{exact:true}).check();
    await page.getByLabel('手填地点',{exact:true}).fill('合成地点，不是车辆定位');
    await page.getByLabel('附带一条充电记录',{exact:true}).check();
    await page.getByLabel('附带的充电记录',{exact:true}).selectOption('report-charge');
    const png=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=800;c.height=400;const x=c.getContext('2d');x.fillStyle='#226e61';x.fillRect(0,0,800,400);x.fillStyle='#e4f7df';x.fillRect(110,90,580,220);return c.toDataURL('image/png').split(',')[1];}),'base64');
    const photo=pngWithMetadata(png);assert.ok(photo.includes(Buffer.from('SYNTHETIC-PHOTO-SECRET')));
    await page.getByLabel('选择本机照片',{exact:true}).setInputFiles({name:'synthetic.png',mimeType:'image/png',buffer:photo});
    await page.getByText('照片已在浏览器内载入。',{exact:true}).waitFor();
    await page.evaluate(()=>render());
    assert.equal(await page.getByLabel('手填地点',{exact:true}).inputValue(),'合成地点，不是车辆定位');
    assert.equal(await page.locator('#trip-card-preview img').count(),0);
    await layouts(page,'trip-cards');
    assert.ok(await page.evaluate(()=>{const c=document.querySelector('#trip-card-canvas');return c.width===1440&&c.height<7000;}));
    let downloadPromise=page.waitForEvent('download');
    await page.getByRole('button',{name:'导出 PNG 图片',exact:true}).click();
    let download=await downloadPromise;const darkPath='/tmp/zeekr-insights-qa/trip-card-export-dark.png';await download.saveAs(darkPath);
    let exported=fs.readFileSync(darkPath);
    assert.equal(exported.subarray(1,4).toString(),'PNG');assert.equal(exported.readUInt32BE(16),1440);
    for(const secret of ['SYNTHETIC-PHOTO-SECRET','NEVER-EXPORT-IDENTITY','PRIVATE-ADDRESS','accessToken'])assert.ok(!exported.includes(Buffer.from(secret)));
    await page.getByLabel('显示手填地点',{exact:true}).uncheck();
    await page.getByLabel('显示时间与时长',{exact:true}).uncheck();
    assert.ok(!(await page.locator('#trip-card-description').innerText()).includes('合成地点'));
    assert.ok(!(await page.locator('#trip-card-description').innerText()).includes('2026/09'));
    await page.getByLabel('卡片外观',{exact:true}).selectOption('light');
    downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'导出 PNG 图片',exact:true}).click();
    download=await downloadPromise;await download.saveAs('/tmp/zeekr-insights-qa/trip-card-export-light.png');
    await page.getByLabel('选择本机照片',{exact:true}).setInputFiles({name:'fake.png',mimeType:'image/png',buffer:Buffer.from('<svg onload="alert(1)">')});
    await page.getByRole('alert').filter({hasText:'PNG'}).waitFor();
    await page.getByRole('button',{name:'移除照片',exact:true}).click();
    await page.getByLabel('卡片行程',{exact:true}).selectOption('report-partial');
    assert.match(await page.locator('#trip-card-description').innerText(),/观测片段/);
    assert.equal(await page.getByLabel('显示手填地点',{exact:true}).isChecked(),false);
    assert.deepEqual(f.posts,[]);assert.ok(f.external.every(url=>url.startsWith('blob:'+f.origin)));assert.deepEqual(f.errors,[]);
    console.log('UI_TRIP_CARDS_PASS: safe trip/charge choices, optional fields/location, local photo+metadata stripping, long text, light/dark PNG download, unsupported-image rejection, partial labels, mobile/zoom/contrast, no POST or external network');
  }finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
