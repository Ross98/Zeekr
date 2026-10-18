// Fixed synthetic sizes, real local APIs, and intercepted basemap tiles.
// Optional argument: artifact parent directory. Each invocation creates its own child.
const {chromium}=require('playwright'),{spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const os=require('node:os'),path=require('node:path'),fs=require('node:fs');
(async()=>{
  const parent=process.argv[2]?path.resolve(process.argv[2]):os.tmpdir();
  fs.mkdirSync(parent,{recursive:true});
  const directory=fs.mkdtempSync(path.join(parent,'zeekr-recall-benchmark-'));
  const server=spawn('python3',[path.join(__dirname,'recall_fixture.py'),'--performance']);let browser;
  try{
    const port=await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('fixture timeout')),60000);
      const fail=error=>{clearTimeout(timer);reject(error);};
      server.once('error',fail);server.once('exit',code=>fail(Error('fixture exit '+code)));
      server.stdout.once('data',data=>{clearTimeout(timer);resolve(Number(String(data).trim()));});
      server.stderr.on('data',data=>process.stderr.write(data));
    });
    assert.ok(Number.isInteger(port)&&port>0,'fixture publishes a valid port');
    const origin='http://127.0.0.1:'+port;
    browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_EXECUTABLE});
    const page=await browser.newPage({viewport:{width:1440,height:1080}});page.setDefaultTimeout(15000);
    const errors=[],posts=[],unexpected=[],counts=new Map();let syntheticTiles=0;
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>{
      const url=new URL(request.url());
      if(request.method()==='POST')posts.push(url.pathname);
      if(url.origin===origin)counts.set(url.pathname+url.search,(counts.get(url.pathname+url.search)||0)+1);
    });
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.origin===origin){
        if(/^\/api\/insights\/(report|costs)$/.test(url.pathname)||route.request().method()==='POST'){
          unexpected.push(route.request().method()+' '+url.pathname);await route.abort();
        }else await route.continue();
      }else if(url.protocol==='https:'&&/^wprd0[1-4]\.is\.autonavi\.com$/.test(url.hostname)&&url.pathname==='/appmaptile'){
        syntheticTiles++;
        await route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e5ece6"/></svg>'});
      }else{unexpected.push(route.request().method()+' '+url.href);await route.abort();}
    });
    // Enter the target view directly: no overview report/cost job or cancellation.
    await page.goto(origin+'/?p=tracks&s=local&date=2026-09-20');
    await page.getByRole('button',{name:'隐藏位置',exact:true}).click();
    await page.waitForFunction(()=>page==='tracks'&&trackSource==='local'&&!showPosition&&!localTrips.listBusy);
    assert.equal(await page.getByLabel('轨迹日期').inputValue(),'2026-09-20');
    const baseline=new Map(counts);
    const data=await page.evaluate(async()=>{
      const measure=async url=>{
        const milliseconds=[];let bytes,result;
        for(let i=0;i<3;i++){
          const start=performance.now(),response=await fetch(url),text=await response.text();
          milliseconds.push(performance.now()-start);
          if(!response.ok)throw Error(text);
          bytes=new TextEncoder().encode(text).length;result=JSON.parse(text);
        }
        return {milliseconds,bytes,result};
      };
      const timelineUrl='/api/timeline?date=2026-09-20',referenceUrl='/api/timeline?date=2026-09-01';
      const day=await measure(timelineUrl),reference=await measure(referenceUrl);
      const place=reference.result.records.find(record=>record.type==='trip'&&record.id.startsWith('history-')).end_place;
      const historyUrl='/api/place-history?start=2026-08-21&end=2026-09-20&key='+encodeURIComponent(place.key);
      const yearUrl='/api/year-review?year=2024',history=await measure(historyUrl),year=await measure(yearUrl);
      return {
        urls:{timeline:timelineUrl,reference:referenceUrl,history:historyUrl,year:yearUrl},
        timeline:{milliseconds:day.milliseconds,bytes:day.bytes,records:day.result.records.length,
          trips:day.result.records.filter(record=>record.type==='trip').length,
          charges:day.result.records.filter(record=>record.type==='charge').length},
        history:{milliseconds:history.milliseconds,bytes:history.bytes,records:history.result.count,
          page_records:history.result.records.length,has_next_page:!!history.result.next_cursor},
        year:{milliseconds:year.milliseconds,bytes:year.bytes,days:year.result.days.length,trips:year.result.totals.trip_count}
      };
    });
    data.requests={measured:Object.fromEntries(Object.entries(data.urls).map(([name,url])=>[name,(counts.get(url)||0)-(baseline.get(url)||0)]))};
    delete data.urls;
    assert.deepEqual(data.requests.measured,{timeline:3,reference:3,history:3,year:3},'count actual requests per measured URL');
    assert.equal(data.timeline.trips,122);assert.equal(data.timeline.charges,1);
    assert.equal(data.history.records,64,'60 history trips plus 4 matching daily records');assert.equal(data.history.page_records,30);assert.equal(data.history.has_next_page,true);
    assert.equal(data.year.days,366);assert.equal(data.year.trips,366);
    await page.getByRole('button',{name:'查询行程',exact:true}).click();
    await page.locator('[data-local-trip="recall-drive"]').waitFor();
    await page.waitForFunction(()=>!localTrips.listBusy&&!localTrips.listTask);
    assert.equal(await page.locator('#map').count(),0,'cold map measurement starts without map DOM');
    assert.equal(await page.evaluate(()=>localTrips.route),null,'no preloaded route');
    const routeUrl='/api/tracks?date=2026-09-20',beforeRoute=counts.get(routeUrl)||0;
    const start=()=>page.evaluate(()=>{
      window.recallLongTasks=[];
      window.recallPerfObserver=new PerformanceObserver(list=>recallLongTasks.push(...list.getEntries().map(entry=>entry.duration)));
      recallPerfObserver.observe({type:'longtask',buffered:false});window.recallBenchStart=performance.now();
    });
    const finish=()=>page.evaluate(async()=>{
      // Let the completed route reach paint; drain observer records, without a fixed sleep.
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      recallLongTasks.push(...recallPerfObserver.takeRecords().map(entry=>entry.duration));recallPerfObserver.disconnect();
      return {elapsed_ms:performance.now()-recallBenchStart,long_tasks_ms:recallLongTasks,
        max_long_task_ms:Math.max(0,...recallLongTasks),observations:localTrips.route.count,
        connected:map.getContainer()===document.querySelector('#map')};
    });
    await start();
    await page.getByRole('button',{name:'显示位置并加载地图',exact:true}).click();
    await page.waitForFunction(()=>map&&localTrips.route?.count===4181&&!localTrips.routeBusy&&
      localTrips.layers?.getLayers().length>4181&&document.querySelector('#map canvas,#map path')&&
      map.getContainer()===document.querySelector('#map')&&
      Object.values(map._layers).filter(layer=>layer instanceof L.TileLayer).every(layer=>!layer.isLoading()));
    data.map=await finish();
    assert.equal((counts.get(routeUrl)||0)-beforeRoute,1,'cold map issues exactly one day-route request');
    assert.ok(syntheticTiles>0,'actual basemap requests were intercepted');
    assert.equal(data.map.connected,true);assert.equal(data.map.observations,4181);
    data.map.drawing=await page.evaluate(()=>{
      const samples=localTrips.layers.getLayers().filter(layer=>layer instanceof L.CircleMarker&&layer.options.radius===4);
      const expected=localTrips.route.observations.filter(point=>point.plottable);
      const endpoints=localTrips.layers.getLayers().filter(layer=>layer instanceof L.CircleMarker&&layer.options.radius===7);
      const gaps=localTrips.layers.getLayers().filter(layer=>layer instanceof L.CircleMarker&&layer.options.radius===10);
      const trusted=new Map(expected.filter(point=>point.trusted&&Number.isFinite(point.state_time)).map(point=>[point.state_time,point]));
      const expectedGaps=(localTrips.route.gaps||[]).flatMap(gap=>
        [...new Set([trusted.get(gap.start_time),trusted.get(gap.end_time)].filter(Boolean))].map(point=>
          ({point,label:`采样间断 · ${tripDuration(gap.duration_seconds)}`})));
      const at=(layer,point)=>layer.getLatLng().lat===point.latitude&&layer.getLatLng().lng===point.longitude;
      return {samples:samples.length,positions_preserved:samples.length===expected.length&&samples.every((layer,i)=>at(layer,expected[i])),
        endpoints_preserved:endpoints.length===2&&at(endpoints[0],expected[0])&&at(endpoints[1],expected.at(-1))&&
          endpoints[0].getTooltip()?.getContent()==='首个采样点'&&endpoints[1].getTooltip()?.getContent()==='末个采样点',
        gap_markers:gaps.length,gaps_preserved:gaps.length===expectedGaps.length&&gaps.every((layer,i)=>at(layer,expectedGaps[i].point)&&layer.getTooltip()?.getContent()===expectedGaps[i].label),
        vector_dom_nodes:document.querySelectorAll('#map path,#map canvas').length};
    });
    assert.equal(data.map.drawing.samples,4181,'all sample markers remain');
    assert.equal(data.map.drawing.positions_preserved,true,'every sample coordinate remains');
    assert.equal(data.map.drawing.endpoints_preserved,true,'observed endpoint markers and labels remain');
    assert.ok(data.map.drawing.gap_markers>0,'fixture exercises actual gap boundary markers');
    assert.equal(data.map.drawing.gaps_preserved,true,'gap markers use only observed boundary coordinates');
    assert.ok(data.map.drawing.vector_dom_nodes<100,'dense route avoids thousands of vector DOM nodes');
    // Keyboard playback still selects the original observed coordinate.
    await page.getByRole('button',{name:'下一点',exact:true}).focus();await page.keyboard.press('Enter');
    assert.equal(await page.locator('#playback').inputValue(),'1');
    assert.equal(await page.evaluate(()=>mapMarker.getLatLng().lat===playback[1].latitude&&mapMarker.getLatLng().lng===playback[1].longitude),true);
    await page.evaluate(()=>{window.recallMeasuredMap=map;});
    await start();await page.locator('[data-local-trip="recall-charge"]').click();
    await page.waitForFunction(()=>localTrips.selection==='recall-charge'&&localTrips.route?.count===1&&
      !localTrips.routeBusy&&!localTrips.listBusy&&document.querySelector('#map-status')?.textContent.startsWith('1 条观测'));
    data.selection=await finish();
    data.selection.retains_map=await page.evaluate(()=>map===recallMeasuredMap);
    assert.equal(data.selection.retains_map,true);assert.equal(data.selection.connected,true);
    assert.equal(data.selection.observations,1);
    assert.equal((counts.get(routeUrl)||0)-beforeRoute,1,'selection does not reload the day route');
    for(const key of ['timeline','history','year']){
      assert.equal(data[key].milliseconds.length,3);
      assert.ok(data[key].milliseconds.every(ms=>Number.isFinite(ms)&&ms>=0&&ms<2000),key+' each read <2s');
      assert.ok(data[key].bytes>0);
    }
    assert.ok(data.map.elapsed_ms<2000,'map <2s');
    assert.ok(data.map.max_long_task_ms<=200,'map no >200ms task: '+data.map.max_long_task_ms+'ms');
    assert.ok(data.selection.max_long_task_ms<=200,'selection no >200ms task: '+data.selection.max_long_task_ms+'ms');
    data.environment={platform:os.platform(),arch:os.arch(),cpu:os.cpus()[0].model,browser:await browser.version(),
      viewport:'1440x1080',tiles:'local synthetic intercepted (Amap)',
      sizes:'4000 dense points plus 181 minute samples; 120 extra daily trips; 366 yearly trips; 19 observed parking days; 60 place-history trips'};
    data.measured_at=new Date().toISOString();
    await browser.close();browser=null;
    data.requests.synthetic_tiles=syntheticTiles;data.requests.unexpected=unexpected;data.requests.posts=posts;
    assert.deepEqual(errors,[],'no browser script errors');assert.deepEqual(unexpected,[],'no unmocked external or overview initialization requests');
    assert.deepEqual(posts,[],'no writes or background cancellation POSTs');
    data.output_file=path.join(directory,'performance.json');
    const json=JSON.stringify(data,null,2);fs.writeFileSync(data.output_file,json);console.log(json);
  }finally{if(browser)await browser.close();server.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
