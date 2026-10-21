// Dense-route correctness runs in CI; hardware timing gates stay in the benchmark.
const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
  const begin=Date.parse('2026-09-20T08:00:00+08:00');
  const points=Array.from({length:4001},(_,i)=>({latitude:31.2+i/1000000,longitude:121.4+i/1000000,
    state_time:begin+i*1000+(i>=2000?300000:0),trusted:true,plottable:true,time_label:'合成采样 '+i,time_source:'合成源时间'}));
  const gap={start_time:points[1999].state_time,end_time:points[2000].state_time,duration_seconds:301,reason:'合成采样缺口'};
  let tiles=0,evidenceCase='both';
  const coordinateRequests=[];
  const f=await fixture({demo:true,initialResearch:false,beforeGoto:async page=>{
    page.on('request',request=>{
      const url=new URL(request.url());
      if(url.pathname==='/api/tracks'||(url.pathname==='/api/timeline'&&url.searchParams.get('positions')==='1'))coordinateRequests.push(request.url());
    });
    await page.addInitScript(()=>history.replaceState(null,'','/?p=tracks&s=local&date=2026-09-20'));
    await page.route('https://wprd0*.is.autonavi.com/**',route=>{
      tiles++;return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e5ece6"/></svg>'});
    });
    // Decorate a real synthetic timeline response; the backend evidence contract
    // is independent of the name's manual/automatic interpretation.
    await page.route('**/api/timeline?*',async route=>{
      const headers={...route.request().headers()};delete headers.prefer;
      const response=await route.fetch({headers}),data=await response.json();
      const row=data.records.find(row=>row.id==='report-trip-night');
      row.partial=true;
      row.start_place={...row.start_place,key:'place_name_'+'a'.repeat(64),label:'合成家',source:'manual',decision:'confirmed',issues:[]};
      row.end_place={...row.end_place,key:'place_name_'+'b'.repeat(64),label:'合成公司',source:'manual',decision:'confirmed',issues:[]};
      if(evidenceCase==='both'){
        row.start_place_evidence={source:'parking_inferred',sampling_gap_seconds:33.57};
        row.end_place_evidence={source:'parking_inferred',sampling_gap_seconds:1190.103,reviewed:true};
      }else if(evidenceCase==='long'){
        row.start_place_evidence={source:'parking_inferred',sampling_gap_seconds:16437.121,reviewed:true};
        row.end_place_evidence={source:'parking_inferred',sampling_gap_seconds:null};
      }else if(evidenceCase==='invalid-gaps'){
        row.start_place_evidence={source:'parking_inferred',sampling_gap_seconds:-1};
        row.end_place_evidence={source:'parking_inferred',sampling_gap_seconds:0};
      }else{
        row.start_place={key:null,label:'位置未知',source:'unknown',decision:'unresolved',issues:['missing_position']};
        row.start_place_evidence={source:'unknown',sampling_gap_seconds:99};
        delete row.end_place_evidence;
      }
      data.revision='evidence-'+evidenceCase;await route.fulfill({json:data});
    });
    await page.route('**/api/tracks?*',route=>route.fulfill({json:{observations:points,
      segments:[points.slice(0,2000),points.slice(2000)],gaps:[gap],count:points.length}}));
  }}),{page}=f;
  try{
    await page.getByRole('button',{name:'查询行程',exact:true}).click();
    await page.waitForFunction(()=>localTrips.queried&&!localTrips.listBusy&&localTrips.timeline);
    await page.locator('#local-trip-details-disclosure>summary').click();
    await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).waitFor();
    assert.deepEqual(coordinateRequests,[],'querying trips before location consent must not request coordinates');
    assert.equal(await page.locator('#map').count(),0,'location stays hidden before consent');
    assert.equal(tiles,0,'no map tiles load before location consent');
    await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();
    const ready=()=>page.waitForFunction(()=>localTrips.route?.count===4001&&!localTrips.routeBusy&&map?.getContainer()===document.querySelector('#map'));
    await ready();
    async function check(){
      const drawn=await page.evaluate(()=>{
        const layers=localTrips.layers.getLayers(),at=layer=>[layer.getLatLng().lat,layer.getLatLng().lng];
        return {samples:layers.filter(layer=>layer instanceof L.CircleMarker&&layer.options.radius===4).map(at),
          endpoints:layers.filter(layer=>layer instanceof L.CircleMarker&&layer.options.radius===7).map(layer=>({at:at(layer),label:layer.getTooltip()?.getContent()})),
          gaps:layers.filter(layer=>layer instanceof L.CircleMarker&&layer.options.radius===10).map(layer=>({at:at(layer),label:layer.getTooltip()?.getContent(),dash:layer.options.dashArray})),
          vector_nodes:document.querySelectorAll('#map path,#map canvas').length};
      });
      assert.deepEqual(drawn.samples,points.map(point=>[point.latitude,point.longitude]),'every original sample coordinate is drawn');
      assert.deepEqual(drawn.endpoints,[{at:drawn.samples[0],label:'首个采样点'},{at:drawn.samples.at(-1),label:'末个采样点'}]);
      const label=await page.evaluate(()=>`采样间断 · ${tripDuration(301)}`);
      assert.deepEqual(drawn.gaps,[1999,2000].map(i=>({at:drawn.samples[i],label,dash:'3 3'})),'gap rings only mark the two observed boundaries');
      assert.ok(drawn.vector_nodes<100,'dense route has bounded vector DOM');
      assert.match(await page.locator('.local-gap-details>summary').innerText(),/1 处采样间断/);
    }
    await check();await page.evaluate(()=>{window.checkedMap=map;});
    await page.getByRole('button',{name:'下一点',exact:true}).focus();await page.keyboard.press('Enter');
    assert.equal(await page.locator('#playback').inputValue(),'1');
    assert.deepEqual(await page.evaluate(()=>[mapMarker.getLatLng().lat,mapMarker.getLatLng().lng]),[points[1].latitude,points[1].longitude]);
    await page.locator('[data-local-trip="report-trip-night"]').click();await ready();
    const facts=page.locator('#local-trip-facts');
    async function bothNotices(){
      const text=await facts.innerText();
      assert.match(text,/起点 合成家 · 人工确认/);assert.match(text,/终点 合成公司 · 人工确认/);
      assert.match(text,/起点由出发前停车位置推定，非可信 GPS 定位/);
      assert.match(text,/终点由到达后停车位置推定，非可信 GPS 定位/);
      assert.match(text,/起点定位采样缺口约 33\.57 秒，间隔内移动情况未知/);
      assert.match(text,/终点定位采样缺口约 19\.84 分钟，间隔内移动情况未知/);
      assert.match(text,/部分记录；缺失范围不推断/);
      assert.doesNotMatch(text,/0\.56 分钟/);
    }
    await bothNotices();
    assert.equal(await page.evaluate(()=>map===checkedMap),true,'selection retains map');await check();
    await page.getByLabel('外观',{exact:true}).selectOption('dark');await ready();await check();await bothNotices();
    await page.getByRole('button',{name:'隐藏位置',exact:true}).click();assert.equal(await page.locator('#map').count(),0);
    await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();await ready();await check();await bothNotices();
    for(const width of [1280,1024]){
      await page.setViewportSize({width,height:1000});await ready();await bothNotices();
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'desktop '+width+' has no horizontal overflow');
    }
    await page.setViewportSize({width:1440,height:1000});
    for(const variant of ['long','invalid-gaps','unknown']){
      evidenceCase=variant;await page.getByRole('button',{name:'查询行程',exact:true}).click();
      await page.waitForFunction(revision=>localTrips.timeline?.revision===revision&&!localTrips.listBusy,'evidence-'+variant);
      await ready();const text=await facts.innerText();
      assert.match(text,/部分记录；缺失范围不推断/);
      if(variant==='long'){
        assert.match(text,/起点定位采样缺口约 4 小时 34 分钟，间隔内移动情况未知/);
        assert.match(text,/终点由到达后停车位置推定/);
        assert.doesNotMatch(text,/终点定位采样缺口/);
      }else if(variant==='invalid-gaps'){
        assert.match(text,/起点由出发前停车位置推定/);assert.match(text,/终点由到达后停车位置推定/);
        assert.doesNotMatch(text,/定位采样缺口/);
      }else{
        assert.match(text,/起点 位置未知/);assert.doesNotMatch(text,/停车位置推定|定位采样缺口/);
      }
      await check();
    }
    assert.ok(tiles>0);assert.deepEqual(f.errors,[]);assert.deepEqual(f.posts,[]);
    assert.ok(f.external.every(url=>/^https:\/\/wprd0[1-4]\.is\.autonavi\.com\//.test(url)));
    console.log('LOCAL_ROUTE_CANVAS_PASS: 4001 exact samples, endpoints, 301s gap, keyboard playback, selection, theme, privacy, parking inference and sampling gaps');
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
