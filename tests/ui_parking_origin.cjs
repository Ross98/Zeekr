const assert=require('node:assert/strict');
const {fixture}=require('./ui_insight_helpers.cjs');
(async()=>{
  const f=await fixture({initialResearch:false}),{page}=f;
  try{
    let inferred=true;
    await page.route('**/api/insights/trip-tags*',async route=>{
      if(route.request().method()!=='GET')return route.continue();
      const response=await route.fetch(),data=await response.json();
      const row=data.events[0];
      if(!row)return route.fulfill({json:data});
      if(inferred){
        row.start_place='synthetic-parking';
        row.start_place_evidence={source:'parking_inferred',sample_time:row.start_time-34000};
        data.place_statistics.places.push({id:'synthetic-parking',label:'合成停车地点',latitude:31.2,longitude:121.4,departures:1,arrivals:0});
      }
      await route.fulfill({json:data});
    });
    await page.getByRole('button',{name:'行程与轨迹',exact:true}).click();
    await page.getByRole('button',{name:'行程标签',exact:true}).click();
    await page.getByLabel('标签月份',{exact:true}).fill('2026-09');
    await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
    const note=page.locator('#tag-events').getByText('起点由出发前停车位置推定，非可信 GPS 定位。',{exact:true});
    await note.waitFor();
    const card=note.locator('xpath=..');
    assert.match(await card.innerText(),/参考地点：合成停车地点/);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    inferred=false;
    await page.getByRole('button',{name:'读取行程标签',exact:true}).click();
    await page.locator('[data-tag="load"]:not(:disabled)').waitFor();
    assert.equal(await note.count(),0);
    assert.deepEqual(f.errors,[]);
    console.log('UI_PARKING_ORIGIN_DESKTOP_PASS');
  }finally{await f.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
