(function(root){
  'use strict';
  const num=v=>Number.isFinite(v)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(v):'未知';
  const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  function create({kind,getState,request,escape:esc,active,time,navigate}){
    let node=null,owner='',date=today(),month=date.slice(0,7),data=null,error='',loading=false,serial=0,selection='',index=0,revision='';
    const button=(text,action,disabled=false,extra='')=>`<button class="button secondary" data-travel="${action}" ${disabled?'disabled':''} ${extra}>${text}</button>`;
    const id=r=>r.start_place+'>'+r.end_place;
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint)||!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const route=kind==='routes';
      node.innerHTML=`<section class="insight-hero"><div><h2>${route?'常走路线对比':'轻量用车回顾'}</h2><p>${route?'同一方向逐次比较，每个指标各算有效样本。':'按需查看已有本地记录，缺失不当作没有发生。'}</p></div><span class="insight-source">本地观测 · 按需读取</span></section><section class="card insight-panel"><div class="insight-toolbar"><label>${route?'路线月份':'回顾日期'}<input id="${kind}-${route?'month':'date'}" type="${route?'month':'date'}" value="${esc(route?month:date)}"></label>${button(route?'读取路线':'查看这一周','load',!owner||loading)}</div>${loading?'<p role="status">正在读取已有记录…</p>':''}${error?`<p role="alert" class="notice error">${esc(error)}</p>`:''}</section>${data?(route?routeView():reviewView()):''}`;
      if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function routeView(){
      const rows=data.routes;if(!rows.some(r=>id(r)===selection))selection=rows[0]?id(rows[0]):'';
      const current=rows.find(r=>id(r)===selection),pages=Math.max(1,Math.ceil((current?.events.length||0)/10));index=Math.min(index,pages-1);
      return `<section class="card insight-panel" id="routes-results"><p class="insight-note">${data.window.start_date} 至 ${data.window.end_date} · ${data.trip_count} 条行程，${data.unknown_route_count} 条缺少可归类的起点或终点。使用起止三分钟可信观测；地点是参考位置，命名范围缩小会分开相邻地点。正反方向分别统计。</p>${rows.length?`<label>对比方向<select id="routes-direction" aria-label="对比方向">${rows.map(r=>`<option value="${esc(id(r))}" ${selection===id(r)?'selected':''}>${esc(r.start_label)} → ${esc(r.end_label)} · ${r.count} 趟</option>`).join('')}</select></label>`:'<p class="insight-empty">本月尚无两端都有可信定位的行程。</p>'}</section>${current?`<section class="card insight-panel" id="route-comparison"><h3>${esc(current.start_label)} → ${esc(current.end_label)}</h3><p>${current.count} 条样本 · ${current.complete_count} 条完整 · ${current.partial_count} 条片段</p><div class="report-comparison">${[['观测用时','duration_seconds',60,'分钟'],['观测里程','distance_km',1,'km'],['有效耗电估算','estimated_kwh',1,'kWh']].map(([label,key,scale,unit])=>`<article><strong>${label}</strong><span>均值 ${num(current[key].mean===null?null:current[key].mean/scale)} ${unit}</span><span>中位数 ${num(current[key].median===null?null:current[key].median/scale)} ${unit}</span><small>${current[key].samples} / ${current.count} 条有效样本</small></article>`).join('')}</div><p class="insight-note">耗电按有效 SOC 变化与该事件保存容量估算，非桩端计量。片段只代表观测时段；未知不补零，不拿当前容量补历史。</p><div class="report-event-list">${current.events.slice(index*10,index*10+10).map(r=>`<article><strong>${esc(time(r.end_time))} · ${r.partial?'观测片段':'完整记录'}</strong><p>${num(r.duration_seconds===null?null:r.duration_seconds/60)} 分钟 · ${num(r.distance_km)} km · ${num(r.estimated_kwh)} kWh</p></article>`).join('')}</div><div class="insight-pagination">${button('上一页路线样本','previous',index===0)}<span>${index+1} / ${pages}</span>${button('下一页路线样本','next',index+1===pages)}</div></section>`:''}`;
    }
    function reviewView(){
      const c=data.costs;
      return `<section class="card insight-panel" id="usage-review"><h3>${data.window.start_date} 至 ${data.window.end_date}</h3><p>${data.trip_count} 条行程，含 ${data.partial_trip_count} 条片段 · 有效观测里程 ${num(data.distance_km)} km（${data.distance_samples} 条样本）</p><h4>记录里去了哪里</h4><div class="report-event-list">${data.places.map(p=>`<article><strong>${esc(p.label)}</strong><span>出发 ${p.departures} 次 · 到达 ${p.arrivals} 次</span></article>`).join('')||'<p>暂无可信地点记录。</p>'}</div><p class="insight-note">起点未知 ${data.unknown_departures} 次，终点未知 ${data.unknown_arrivals} 次。参考地点不保证真实目的地；没有记录不代表没去过。</p><h4>已记实际费用</h4><p class="review-cost">${num(c.actual_cents===null?null:c.actual_cents/100)} 元</p><p>充电 ${num(c.charge_cents===null?null:c.charge_cents/100)} 元 · 充电停车费 ${num(c.parking_cents===null?null:c.parking_cents/100)} 元 · 生活账本 ${num(c.life_cents===null?null:c.life_cents/100)} 元</p><p class="insight-note">按账单日期合计已填金额，估算不并入。${c.bill_count} 笔充电账单，${c.life_count} 笔生活费用；两本账若重复记了同一费用，请人工核对。</p><h4>还有什么待补</h4><p>${data.pending_count} 次充电未关联账单 · ${c.unknown_charge_count} 笔已录充电账单金额未知</p><div class="report-event-list">${data.pending.slice(0,20).map(r=>`<article><span>${esc(time(r.end_time))}${r.partial?' · 片段':''}</span>${button('去充电账本','ledger',false,`data-event-id="${esc(r.id)}" data-date="${new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(r.end_time))}"`)}</article>`).join('')}</div>${data.pending_count>20?'<p>仅列最近 20 次；更多记录在充电账本。</p>':''}</section>`;
    }
    async function load(preserveSelection=false){
      if(!owner)return;const token=++serial,identity=owner;loading=true;error='';paint();
      try{const result=await request(`/api/insights/${kind}?date=${encodeURIComponent(kind==='routes'?month+'-01':date)}`);
        if(token!==serial||identity!==getState()?.insights_context)return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');data=result;if(!preserveSelection)index=0;
      }catch(e){if(token===serial&&identity===getState()?.insights_context)error=e.message;}
      finally{if(token===serial&&identity===getState()?.insights_context){loading=false;paint();}}
    }
    function mount(container){
      const next=getState()?.insights_context||'',rev=JSON.stringify([getState()?.trip_records_revision,getState()?.charge_records_revision]);
      const changed=next!==owner,recordsChanged=revision!==rev,remount=node!==container;node=container;
      revision=rev;
      if(changed){owner=next;serial++;data=null;loading=false;error='';selection='';index=0;}
      else if(recordsChanged&&(data||loading))load(true);
      if(changed||remount)paint();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;
      if(event.type==='input'&&[`${kind}-month`,`${kind}-date`].includes(event.target.id)){
        if(kind==='routes')month=event.target.value;else date=event.target.value;serial++;data=null;loading=false;error='';paint();return true;
      }
      if(event.type==='change'&&event.target.id==='routes-direction'){selection=event.target.value;index=0;paint();return true;}
      const target=event.type==='click'&&event.target.closest('[data-travel]');if(!target||target.disabled)return false;
      if(target.dataset.travel==='load')load();
      else if(target.dataset.travel==='ledger')navigate('books','ledger',target.dataset.date,target.dataset.eventId);
      else{index+=target.dataset.travel==='next'?1:-1;paint();}return true;
    }
    return {mount,handle};
  }
  root.TravelInsightsPage={create};
})(window);
