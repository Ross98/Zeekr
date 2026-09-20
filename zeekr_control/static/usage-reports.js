(function(root){
  'use strict';
  const num=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'—';
  const currentDate=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const statusText={closed:'周期已结束',ongoing:'本期进行中',upcoming:'未来周期'};
  const reasons={period_open:'本期未结束，不计算全期涨跌',missing_samples:'有效样本不足',zero_base:'上期基数为零'};
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',period='week',date=currentDate(),data=null,error='',loading=false,attempted=false,serial=0;
    let dayFilter='',kind='all',quality='all',page=0;
    const context=()=>getState()?.insights_context||'';
    const valid=(token,identity)=>token===serial&&identity===owner&&identity===context();
    const button=(text,action,disabled=false,extra='')=>`<button class="button secondary" data-report="${action}" ${disabled?'disabled':''} ${extra}>${text}</button>`;
    function events(){return (data?.current.events||[]).filter(row=>(!dayFilter||new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(row.end_time))===dayFilter)&&(kind==='all'||row.kind===kind)&&(quality==='all'||(quality==='partial')===row.partial));}
    function metric(label,value,unit,note,id){return `<div ${id?`id="${id}"`:''}><span>${label}</span><strong>${num(value)}${unit?` <small>${unit}</small>`:''}</strong><small>${esc(note)}</small></div>`;}
    function paint(){
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const c=data?.current,t=c?.totals,s=c?.samples,w=c?.window;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">用车周报 · 月报</span><h2>把一段用车生活，放在一起看</h2><p>里程、行程、充电与记录覆盖，各有依据。</p></div><span class="insight-source">本地结束事件</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>报告周期<select id="report-period" aria-label="报告周期"><option value="week" ${period==='week'?'selected':''}>自然周</option><option value="month" ${period==='month'?'selected':''}>自然月</option></select></label><label>周期内日期<input id="report-date" type="date" value="${esc(date)}"></label>${button('查看报告','load',!owner||!date,'id="report-load"')}</div>${loading?'<p role="status">正在汇总本地记录…</p>':''}${error?`<div class="notice error" role="alert">${esc(error)}${data?' · 保留上次报告和原周期。':''}</div>`:''}${!owner?'<p>连接车辆账号并取得当前车辆绑定后，可查看报告。</p>':''}
        ${data?`<div class="report-period-head"><div><h3 id="report-title">${esc(w.start_date)} — ${esc(w.end_date)}</h3><p class="insight-note">北京时间 · ${data.period==='week'?'周一至周日':'自然月'} · ${statusText[c.status]} · 统计截至 ${esc(time(data.as_of))}</p></div><div class="insight-actions">${button('上一周期','previous')}${button('下一周期','next')}</div></div>`:''}</section>
        ${data?`<div class="insight-metrics report-totals">${metric('完整行程已记录里程',t.distance_km,'km',`${s.distance} 条有效里程样本`,'report-distance')}${metric('结束行程',t.trip_count,'次',`完整 ${t.complete_trip_count} 次 · 片段 ${t.partial_trip_count} 次`)}${metric('结束充电',t.charge_count,'次',`完整 ${t.complete_charge_count} 次 · 片段 ${t.partial_charge_count} 次`)}${metric('完整行程观测时长',t.duration_seconds===null?null:t.duration_seconds/3600,'小时',`${s.duration} 条有效时长样本`)}</div>
        <section class="card insight-panel"><h3>电量估算与片段</h3><div class="parking-row-values">${metric('驾驶电量估算',t.trip_estimated_kwh,'kWh',`${s.trip_energy} 条有效样本；事件记录容量 × SOC 变化`)}${metric('补入电量估算',t.charge_estimated_kwh,'kWh',`${s.charge_energy} 条有效样本；不是桩端计量电量`)}${metric('百公里电量估算',t.estimated_kwh_per_100km,'kWh/100km',`${s.efficiency} 条至少 10 km 且耗电至少 3 个百分点的样本`)}${metric('片段单列已记录里程',t.partial_distance_km,'km',`${t.partial_trip_count} 条片段；未并入完整行程里程`)}</div><p class="insight-note">未结束事件不计入。估算只用端点一致、容量有效且没有充电混入的完整事件。无有效样本显示“—”，不当成零。</p></section>
        <section class="card insight-panel"><h3>与上一周期比较</h3><p class="insight-note">上期 ${esc(data.previous.window.start_date)} — ${esc(data.previous.window.end_date)}。比较的是已记录数据；覆盖不同不代表真实用车必然增减。</p><div class="report-comparison">${[['distance_km','完整记录里程','km'],['trip_count','结束行程','次'],['charge_count','结束充电','次'],['duration_seconds','观测时长','小时']].map(([key,label,unit])=>{const r=data.comparison.metrics[key],scale=key==='duration_seconds'?3600:1;return `<article><strong>${label}</strong><span>上期 ${num(r.previous===null?null:r.previous/scale)} ${unit}</span><span>本期 ${num(r.current===null?null:r.current/scale)} ${unit}</span><b>${r.percent===null?esc(reasons[r.reason]):`${r.percent>0?'+':''}${num(r.percent)}%`}</b></article>`;}).join('')}</div></section>
        <section class="card insight-panel"><h3>归档覆盖</h3><div class="parking-row-values">${metric('本期有归档读取的日期',c.coverage.days_with_reads,'天',`周期共 ${w.days} 天；有读取不等于全天覆盖`)}${metric('有效不同车辆时间',c.coverage.new_states,'个',`${c.coverage.reads} 次读取 · 重复 ${c.coverage.repeats} 次 · 修订 ${c.coverage.revisions} 次`)}${metric('旧值或异常观测',c.coverage.invalid_or_stale,'次','不算有效新状态')}${metric('上期有归档读取的日期',data.previous.coverage.days_with_reads,'天',`上期共 ${data.previous.window.days} 天`)}</div><p class="insight-note">本期首次读取 ${esc(time(c.coverage.first_read))}，最后读取 ${esc(time(c.coverage.last_read))}。归档覆盖按当前账号统计；事件保留当前车辆已有历史。没有归档不等于没有行程。${data.history_quality.unreadable_or_undated?`另有 ${data.history_quality.unreadable_or_undated} 条车辆历史记录格式或结束时间无效，无法归期（非仅本期）。`:''}</p></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>每日结束记录</h3>${dayFilter?button('显示整个周期','clear-day'):''}</div><p class="insight-note">点击日期筛选下方事件。里程仅含完整行程。无归档、没有结束事件与未来日期分别标记。</p><div class="report-days">${c.days.map(day=>`<button data-report="day" data-date="${day.date}" aria-pressed="${dayFilter===day.date}" ${day.coverage==='future'?'disabled':''}><span>${day.date.slice(5)}</span><strong>${num(day.distance_km)} km</strong><span>行程 ${day.trip_count} · 充电 ${day.charge_count}</span><small>${{observed:'有归档观测',missing:'无归档观测',future:'未来日期'}[day.coverage]}</small></button>`).join('')}</div></section>
        <section class="card insight-panel"><h3>常见出发时段</h3><p class="insight-note">按本期结束行程的已知开始时间统计，含片段。跨午夜行程仍按自身出发时刻计数。</p><div class="report-hours">${Array.from({length:6},(_,i)=>{const count=c.departure_hours.slice(i*4,i*4+4).reduce((a,b)=>a+b,0),max=Math.max(1,...Array.from({length:6},(_,j)=>c.departure_hours.slice(j*4,j*4+4).reduce((a,b)=>a+b,0)));return `<div><span>${String(i*4).padStart(2,'0')}—${String(i*4+3).padStart(2,'0')} 时</span><i aria-hidden="true" style="--bar:${count/max*100}%"></i><strong>${count} 次</strong></div>`;}).join('')}</div></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>本期结束事件${dayFilter?' · '+esc(dayFilter):''}</h3><div class="insight-toolbar"><label>事件类型<select id="report-kind" aria-label="事件类型">${[['all','全部事件'],['trip_end','行程'],['charge_end','充电']].map(([k,v])=>`<option value="${k}" ${kind===k?'selected':''}>${v}</option>`).join('')}</select></label><label>事件完整性<select id="report-quality" aria-label="事件完整性">${[['all','全部记录'],['complete','完整记录'],['partial','片段记录']].map(([k,v])=>`<option value="${k}" ${quality===k?'selected':''}>${v}</option>`).join('')}</select></label></div></div><div id="report-events"></div></section>`:''}`;
      paintEvents();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintEvents(){
      const el=node?.querySelector('#report-events');if(!el||!data)return;
      const rows=events(),pages=Math.max(1,Math.ceil(rows.length/12));page=Math.min(page,pages-1);
      el.innerHTML=`<p class="insight-note">匹配 ${rows.length} 条</p><div class="report-event-list">${rows.slice(page*12,page*12+12).map(row=>`<article data-report-event="${esc(row.id)}"><div class="insight-heading"><h4>${row.kind==='trip_end'?'行程':'充电'}</h4><span class="insight-badge ${row.partial?'insight-warning':''}">${row.partial?'片段记录':'完整记录'}</span></div><p>${esc(time(row.start_time))} → ${esc(time(row.end_time))}</p><div class="parking-row-values"><span>${row.kind==='trip_end'?'里程':'观测时长'}<strong>${row.kind==='trip_end'?num(row.distance_km)+' km':num(row.duration_seconds===null?null:row.duration_seconds/60)+' 分钟'}</strong></span><span>SOC 端点<strong>${num(row.start_soc)}% → ${num(row.end_soc)}%</strong></span><span>电量估算<strong>${num(row.estimated_kwh)} kWh</strong></span><span>事件记录容量<strong>${num(row.battery_capacity_kwh)} kWh</strong></span></div></article>`).join('')||'<p class="insight-empty">没有符合筛选的结束事件。没有记录不表示车辆未使用。</p>'}</div><div class="insight-pagination">${button('上一页事件','events-previous',page===0)}<span>${page+1} / ${pages}</span>${button('下一页事件','events-next',page+1===pages)}</div>`;
    }
    async function load(){
      if(!owner||!date)return;
      const token=++serial,identity=owner;
      attempted=true;loading=true;error='';paint();
      try{
        const result=await request(`/api/insights/report?period=${period}&date=${encodeURIComponent(date)}`);
        if(!valid(token,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=result;dayFilter='';page=0;
      }catch(failure){if(valid(token,identity))error=failure.message;}
      finally{if(valid(token,identity)){loading=false;paint();}}
    }
    function mount(container){
      const changed=owner!==context(),remount=node!==container;node=container;
      if(changed){owner=context();data=null;error='';loading=false;attempted=false;serial++;dayFilter='';page=0;}
      if(changed||remount)paint();
      if(owner&&!attempted&&!loading)load();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;
      const el=event.target;
      if(event.type==='input'&&el.id==='report-date'){date=el.value;node.querySelector('#report-load').disabled=!date||!owner;return true;}
      if(event.type==='change'){
        if(el.id==='report-period'){period=el.value;return true;}
        if(el.id==='report-kind')kind=el.value;
        else if(el.id==='report-quality')quality=el.value;
        else return false;
        page=0;paintEvents();return true;
      }
      if(event.type!=='click')return false;
      const target=el.closest('[data-report]');if(!target||target.disabled)return false;
      switch(target.dataset.report){
        case 'load':load();break;
        case 'previous':date=data.current.window.previous_date;period=data.period;load();break;
        case 'next':date=data.current.window.next_date;period=data.period;load();break;
        case 'day':dayFilter=target.dataset.date;page=0;paint();node.querySelector('#report-events').scrollIntoView({block:'start'});break;
        case 'clear-day':dayFilter='';page=0;paint();break;
        case 'events-previous':page--;paintEvents();break;
        case 'events-next':page++;paintEvents();break;
      }
      return true;
    }
    return {mount,handle};
  }
  root.UsageReportPage={create};
})(window);
