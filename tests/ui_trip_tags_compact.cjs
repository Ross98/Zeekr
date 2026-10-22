const assert=require('node:assert/strict');
const fs=require('node:fs');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture({initialResearch:false}),{page}=f;
 try{
  page.setDefaultTimeout(10000);
  await page.route('**/api/insights/trip-tags?*',async route=>{
   const response=await route.fetch(),data=await response.json(),sample=data.events[0];
   data.events=Array.from({length:30},(_,i)=>({...sample,id:'compact-trip-'+i,tags:['通勤'],manual_tags:['通勤'],note:i===0?'保留的行程备注':''}));
   await route.fulfill({json:data});
  });
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();
  await page.getByRole('button',{name:'行程标签',exact:true}).click();
  await page.getByLabel('标签月份',{exact:true}).fill('2026-09');
  await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  await page.locator('[data-tag-event]').first().waitFor();
  assert.equal(await page.getByLabel('家范围半径',{exact:true}).isVisible(),false,'Settings must not lengthen default page');
  assert.equal(await page.locator('#tag-comparison').isVisible(),false,'Comparison must not lengthen default page');
  assert.ok((await page.locator('#trip-tags-workspace').boundingBox()).height<1500,'Default page stays bounded with many trips');
  const rows=page.locator('.tag-event-list');
  assert.ok(await rows.evaluate(el=>el.scrollHeight>el.clientHeight),'Trip records scroll inside bounded list');
  await page.getByRole('button',{name:'通勤设置',exact:true}).click();
  const panel=page.locator('#tag-tools-panel');await panel.waitFor();
  await page.getByLabel('家范围半径',{exact:true}).fill('450');
  await page.evaluate(()=>render());
  assert.equal(await panel.isVisible(),true);
  assert.equal(await page.getByLabel('家范围半径',{exact:true}).inputValue(),'450','Refresh keeps settings draft');
  await page.keyboard.press('Escape');
  await panel.waitFor({state:'hidden'});
  assert.equal(await panel.isVisible(),false);
  assert.equal(await page.getByRole('button',{name:'通勤设置',exact:true}).evaluate(el=>el===document.activeElement),true);
  await page.getByRole('button',{name:'通勤设置',exact:true}).click();
  assert.equal(await page.getByLabel('家范围半径',{exact:true}).inputValue(),'450','Closing keeps unsaved settings');
  await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();
  await page.getByRole('button',{name:'打开同类比较',exact:true}).click();
  assert.equal(await page.getByRole('heading',{name:'标签比较',exact:true}).isVisible(),true);
  assert.equal(await page.getByText('从下方选择行程添加标签，即可比较。',{exact:true}).isVisible(),true);
  await page.evaluate(()=>render());assert.equal(await panel.isVisible(),true);
  await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();
  await page.locator('[data-tag-event="compact-trip-0"] [data-tag="edit"]').click();
  await page.getByLabel('行程备注',{exact:true}).fill('尚未保存的备注草稿');
  await page.evaluate(()=>render());
  assert.equal(await page.getByLabel('行程备注',{exact:true}).inputValue(),'尚未保存的备注草稿');
  await page.keyboard.press('Escape');
  await panel.waitFor({state:'hidden'});
  await page.locator('[data-tag-event="compact-trip-0"] [data-tag="edit"]').click();
  assert.equal(await page.getByLabel('行程备注',{exact:true}).inputValue(),'尚未保存的备注草稿','Closing keeps annotation draft');
  await page.getByRole('button',{name:'取消标注',exact:true}).click();assert.equal(await panel.isVisible(),false);
  await rows.evaluate(el=>el.scrollTop=el.scrollHeight);
  assert.equal(await page.locator('[data-tag-event]').last().getAttribute('data-tag-event'),'compact-trip-29');
  assert.ok(await rows.evaluate(el=>el.scrollTop>0),'All monthly trips remain reachable inside fixed list');
  for(const theme of ['light','dark']){
   await page.getByLabel('外观',{exact:true}).selectOption(theme);
   for(const width of [1440,1280,1024]){
    await page.setViewportSize({width,height:1000});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.getByRole('button',{name:'打开同类比较',exact:true}).click();
    const box=await panel.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width&&box.height<=1000);
    await page.getByRole('button',{name:'关闭工具面板',exact:true}).click();
   }
  }
  await page.getByLabel('外观',{exact:true}).selectOption('light');await page.setViewportSize({width:1440,height:1000});
  fs.mkdirSync('/tmp/zeekr-insights-qa',{recursive:true});
  await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});
  await page.screenshot({path:'/tmp/zeekr-insights-qa/trip-tags-compact-desktop.png'});
  assert.deepEqual(f.errors,[]);
  assert.deepEqual(f.posts.filter(url=>!/\/api\/analysis\/[^/]+\/cancel$/.test(url)),[]);
  console.log('UI_TRIP_TAGS_COMPACT_PASS: bounded default, tool panels, pagination, drafts, refresh, Escape, desktop themes');
 }catch(error){await f.fail(error);throw error;}finally{await f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
