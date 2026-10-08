const assert=require('node:assert/strict');
process.env.DESKTOP_ONLY='1';
const {fixture,layouts}=require('./ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture(),{page}=f;let saved=null,previous=null,revision=0,conflict=false;const writes=[],previews=[];
 try{
  await page.route(/https:\/\/wprd0\d\.is\.autonavi\.com\//,route=>route.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg==','base64')}));
  await page.route('**/api/insights/trip-tags*',async route=>{
   if(route.request().method()==='POST'){
    const body=route.request().postDataJSON();
    if(body.action==='place-name-preview'){
     previews.push(body);await route.fulfill({json:{context:body.context,preview_token:'preview-'+previews.length,affected_count:2,affected:[{id:'report-trip',sides:['start'],within_range:true}],shape:body.shape,vertex_count:body.vertices.length,conflicts:conflict?[{name:'相邻车库',shape:conflict}]:[]}});return;
    }
    writes.push(body);previous=saved;
    if(body.action==='place-name-save')saved={id:body.region_id||'synthetic-region',name:body.name,shape:body.shape,vertices:body.vertices,latitude:body.vertices[0][0],longitude:body.vertices[0][1]};
    else if(body.action==='place-name-clear')saved=null;
    else if(body.action==='place-name-undo'){saved=previousUndo;}
    revision++;await route.fulfill({json:{context:body.context,name_revision:revision,name_can_undo:true}});return;
   }
   const response=await route.fetch(),data=await response.json();
   const empty=new URL(route.request().url()).searchParams.get('date')==='2026-08-01';
   data.place_statistics={radius_m:150,name_revision:revision,name_can_undo:revision>0,name_regions:saved?[saved]:[],observed_points:empty?[]:[{latitude:31.2,longitude:121.4,side:'start'},{latitude:31.201,longitude:121.401,side:'end'}],unknown_departures:0,unknown_arrivals:0,places:empty?[]:[{id:'place_1',name_key:'synthetic-anchor',label:saved?.name||'参考地点 1',name_source:saved?'manual':'reference',manual_name_id:saved?.id||null,name_shape:saved?.shape,name_vertices:saved?.vertices,latitude:31.2,longitude:121.4,departures:3,arrivals:2}],routes:[]};
   await route.fulfill({json:data});
  });
  let previousUndo=null;
  await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();await page.getByRole('button',{name:'行程标签',exact:true}).click();
  await page.getByLabel('标签月份',{exact:true}).fill('2026-09');await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  assert.equal(await page.locator('#tag-name-map').count(),0);
  await page.getByRole('button',{name:'新建多边形地点',exact:true}).click();
  await page.getByLabel('地点名称',{exact:true}).fill('园区停车场');
  assert.equal(await page.getByRole('button',{name:'预览影响行程',exact:true}).isDisabled(),true);
  const freehand=process.env.FREEHAND_ONLY==='1';
  if(freehand){
   assert.equal(await page.getByLabel('绘制方式',{exact:true}).inputValue(),'freehand');
   await page.locator('#tag-name-map').scrollIntoViewIfNeeded();const box=await page.locator('#tag-name-map').boundingBox();
   await page.mouse.move(box.x+160,box.y+120);await page.mouse.down();
   for(const [x,y] of [[320,120],[320,280],[160,280],[160,120]])await page.mouse.move(box.x+x,box.y+y,{steps:30});
   await page.mouse.up();
   assert.equal(await page.getByRole('button',{name:'预览影响行程',exact:true}).isDisabled(),false,'Mouse release closes freehand area');
   await page.getByRole('button',{name:'重新圈画',exact:true}).click();
   await page.locator('#tag-name-map').scrollIntoViewIfNeeded();const cancelBox=await page.locator('#tag-name-map').boundingBox();
   await page.mouse.move(cancelBox.x+200,cancelBox.y+150);await page.mouse.down();await page.mouse.move(cancelBox.x+250,cancelBox.y+190,{steps:5});
   await page.keyboard.press('Escape');await page.mouse.up();
   assert.equal(await page.locator('#tag-name-map .leaflet-marker-icon').count(),4,'Cancelling a stroke preserves prior area');
   await page.getByRole('button',{name:'浏览地图',exact:true}).click();
  }else{
   await page.getByLabel('绘制方式',{exact:true}).selectOption('points');
   for(const point of [{x:160,y:120},{x:320,y:120},{x:320,y:280},{x:160,y:280}])await page.locator('#tag-name-map').click({position:point});
  }
  assert.equal(await page.locator('#tag-name-map .leaflet-marker-icon').count(),4);
  await page.evaluate(()=>render());assert.equal(await page.locator('#tag-name-map .leaflet-marker-icon').count(),4);
  assert.equal(await page.getByLabel('地点名称',{exact:true}).inputValue(),'园区停车场');
  if(!freehand)await page.getByRole('button',{name:'闭合区域',exact:true}).click();
  await page.getByRole('button',{name:'预览影响行程',exact:true}).click();await page.getByText(/本月可能影响 2 趟行程/).waitFor();
  assert.equal(previews[0].shape,'polygon');assert.equal(previews[0].vertices.length,4);
  await page.getByLabel('选择顶点',{exact:true}).selectOption('1');await page.getByRole('button',{name:'删除选中顶点',exact:true}).click();
  assert.equal(await page.locator('#tag-name-map .leaflet-marker-icon').count(),3);
  assert.equal(await page.getByRole('button',{name:'保存地点名称',exact:true}).isDisabled(),true,'Geometry edits invalidate preview');
  const marker=page.locator('#tag-name-map .leaflet-marker-icon').first();await marker.scrollIntoViewIfNeeded();const rect=await marker.boundingBox();
  await page.mouse.move(rect.x+16,rect.y+16);await page.mouse.down();await page.mouse.move(rect.x+76,rect.y+50,{steps:6});await page.mouse.up();
  await page.getByRole('button',{name:'预览影响行程',exact:true}).click();await page.getByText(/多边形 3 个顶点/).waitFor();
  assert.notDeepEqual(previews[1].vertices[0],previews[0].vertices[0],'Dragging updates saved WGS84 geometry');
  await layouts(page,'place-region-editor');
  await page.getByRole('button',{name:'保存地点名称',exact:true}).click();await page.getByRole('button',{name:'编辑区域 园区停车场',exact:true}).waitFor();
  assert.equal(writes.length,1);assert.equal(writes[0].vertices.length,3);
  await page.getByLabel('标签月份',{exact:true}).fill('2026-08');await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
  await page.getByRole('button',{name:'编辑区域 园区停车场',exact:true}).click();assert.equal(await page.getByLabel('地点名称',{exact:true}).inputValue(),'园区停车场');
  assert.equal(await page.locator('#tag-name-map .leaflet-marker-icon').count(),3);
  conflict='circle';await page.getByRole('button',{name:'预览影响行程',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'保存地点名称',exact:true}).isDisabled(),false,'Circle overlap allows precise polygon edits');
  conflict='polygon';await page.getByRole('button',{name:'预览影响行程',exact:true}).click();await page.getByText(/与 相邻车库 的命名范围重叠/).waitFor();
  assert.equal(await page.getByRole('button',{name:'保存地点名称',exact:true}).isDisabled(),true,'Overlapping polygons cannot save');
  previousUndo=saved;await page.getByRole('button',{name:'恢复自动名称',exact:true}).click();await page.getByText('暂无已保存区域。',{exact:true}).waitFor();
  await page.getByRole('button',{name:'撤销地点操作',exact:true}).click();await page.getByRole('button',{name:'编辑区域 园区停车场',exact:true}).waitFor();
  assert.deepEqual(f.errors,[]);assert.ok(f.external.every(url=>/^https:\/\/wprd0\d\.is\.autonavi\.com\//.test(url)));
  console.log(freehand?'UI_FREEHAND_REGIONS_DESKTOP_PASS':'UI_PLACE_REGIONS_DESKTOP_PASS');
 }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
