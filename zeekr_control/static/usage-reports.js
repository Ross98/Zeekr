(function(root){
  'use strict';
  const num=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'—';
  const currentDate=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const statusText={closed:'周期已结束',ongoing:'本期进行中',upcoming:'未来周期'};
  const reasons={period_open:'本期未结束，不计算全期涨跌',missing_samples:'有效样本不足',zero_base:'上期基数为零',incomplete_bills:'账单待补，仅展示已录实付'};
  function analyze(current){
    const distance=value=>Number.isFinite(value)&&value>=0?value:null;
    const days=current.days.map(day=>{
      const value=day.coverage==='future'?null:distance(day.distance_km);
      return {...day,distance:value,state:day.coverage==='future'?'future':value===null?'missing':'value'};
    });
    const values=days.filter(day=>day.state==='value');
    const peakDistance=values.length?Math.max(...values.map(day=>day.distance)):null;
    const totalDistance=distance(current.totals.distance_km),samples=current.samples.distance;
    return {
      averageDistance:totalDistance!==null&&Number.isInteger(samples)&&samples>0?totalDistance/samples:null,
      peakDistance,peakDates:values.filter(day=>day.distance===peakDistance).map(day=>day.date),
      elapsedDays:days.filter(day=>day.state!=='future').length,
      coveredDays:days.filter(day=>day.coverage==='observed').length,
      days:days.map(day=>({...day,ratio:day.distance===null?null:peakDistance>0?day.distance/peakDistance:0}))
    };
  }
  function compareValues(previous,current,closed){
    const valid=v=>Number.isFinite(v)&&v>=0;
    const a=valid(previous)?previous:null,b=valid(current)?current:null;
    const reason=!closed?'period_open':a===null||b===null?'missing_samples':a===0?'zero_base':null;
    return {previous:a,current:b,difference:a===null||b===null?null:Math.round((b-a)*1e6)/1e6,
      percent:reason?null:Math.round((b-a)/a*10000)/100,reason};
  }
  function pairedDays(current,previous){
    const now=analyze(current).days,before=analyze(previous).days;
    const max=Math.max(0,...now.concat(before).filter(d=>d.distance!==null).map(d=>d.distance));
    const scale=d=>d?{...d,ratio:d.distance===null?null:max>0?d.distance/max:0}:null;
    return now.map((day,i)=>({current:scale(day),previous:scale(before[i])}));
  }
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',period='week',date=currentDate(),data=null,error='',loading=false,attempted=false,serial=0;
    let dayFilter='',kind='all',quality='all',page=0;
    const context=()=>getState()?.insights_context||'';
    let places=null,placesError='',placesLoading=false,placesSerial=0;
    const automatic=root.AutomaticInsightsPage?.create({getState,request,escape:esc,active,time,compact:true,navigate:()=>{}});
    function placesView(){
      if(data?.period!=='week')return '';
      return `<section class="card insight-panel"><div class="insight-heading"><h3>本周地点回顾</h3><button class="button secondary" data-report="places" ${placesLoading?'disabled':''}>读取本周地点</button></div><div id="report-places">${placesLoading?'<p role="status">正在读取地点…</p>':placesError?`<p role="alert">${esc(placesError)}</p>`:places?`<p class="insight-note">${esc(places.window.start_date)} 至 ${esc(places.window.end_date)} · 参考地点不保证真实目的地；没有记录不代表没去过。</p><div class="report-event-list">${places.places.map(p=>`<article><strong>${esc(p.label)}</strong><span>出发 ${p.departures} 次 · 到达 ${p.arrivals} 次</span></article>`).join('')||'<p>暂无可信地点记录。</p>'}</div><p class="insight-note">起点未知 ${places.unknown_departures} 次 · 终点未知 ${places.unknown_arrivals} 次。</p>`:'<p class="insight-note">按需读取本周行程的参考地点。费用与待补账单在费用总览。</p>'}</div></section>`;
    }
    async function loadPlaces(){
      if(!data||data.period!=='week'||placesLoading)return;
      const token=++placesSerial,identity=owner,selected=data.current.window.start_date;placesLoading=true;placesError='';paint();
      try{
        const result=await request(`/api/insights/review?date=${encodeURIComponent(selected)}`);
        if(token!==placesSerial||identity!==context())return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        places=result;
      }catch(e){if(token===placesSerial&&identity===context())placesError=e.message;}
      finally{if(token===placesSerial){placesLoading=false;paint();}}
    }
    const valid=(token,identity)=>token===serial&&identity===owner&&identity===context();
    const button=(text,action,disabled=false,extra='')=>`<button class="button secondary" data-report="${action}" ${disabled?'disabled':''} ${extra}>${text}</button>`;
    function events(){return (data?.current.events||[]).filter(row=>(!dayFilter||new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(row.end_time))===dayFilter)&&(kind==='all'||row.kind===kind)&&(quality==='all'||(quality==='partial')===row.partial));}
    function metric(label,value,unit,note,id){return `<div ${id?`id="${id}"`:''}><span>${label}</span><strong>${num(value)}${unit?` <small>${unit}</small>`:''}</strong><small>${esc(note)}</small></div>`;}
    function observations(analysis){
      const c=data.current,dates=analysis.peakDates;
      const peakNote=dates.length?`${dates.slice(0,3).map(date=>date.slice(5)).join('、')}${dates.length>3?` 等 ${dates.length} 天`:dates.length>1?' 并列':''} · 按行程结束日计`:'没有有效已观测里程样本';
      return `<section class="card insight-panel" id="report-observations" aria-labelledby="report-observations-title"><div class="insight-heading"><h3 id="report-observations-title">本期观察</h3><span class="insight-badge">基于已记录样本</span></div><div class="report-observation-grid">
        <article><span>每条记录平均里程</span><strong>${num(analysis.averageDistance)} <small>km / 条</small></strong><p>${c.samples.distance} 条有效里程记录，含 ${c.samples.partial_distance} 条片段；表示每条记录的已观测里程。</p></article>
        <article><span>单日记录最高</span><strong>${num(analysis.peakDistance)} <small>km</small></strong><p>${esc(peakNote)}</p></article>
        <article><span>已过日期的归档覆盖</span><strong>${analysis.elapsedDays?`${analysis.coveredDays} / ${analysis.elapsedDays}`:'—'} <small>天</small></strong><p>${analysis.elapsedDays?'有读取的日期 / 截至统计时间的日期。当天可能尚未结束；不是车辆在线率。':'所选周期尚未开始。未来日期不参与覆盖计算。'}</p></article>
      </div></section>`;
    }
    const periodName=()=>data.period==='week'?['上周','本周']:['上期','本期'];
    function comparisonCard(key,label,unit,scale=1,note='',id=''){
      const [before,now]=periodName(),previous=data.previous.totals[key],current=data.current.totals[key];
      const r=compareValues(previous,current,data.comparison.comparable);
      const amount=v=>key==='charging_paid_cents'&&Number.isFinite(v)?(v/scale).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}):num(v===null?null:v/scale);
      const max=Math.max(1,r.previous||0,r.current||0);
      const paymentPartial=key==='charging_paid_cents'&&[data.current,data.previous].some(p=>p.payments?.unpriced_bill_count||p.payments?.pending_charge_bill_count);
      const reason=paymentPartial?'incomplete_bills':r.reason;
      const difference=r.difference===null?'—':(r.difference>0?'+':'')+amount(r.difference);
      return `<article class="report-graph-card" ${id?`id="${id}"`:''} data-report-metric="${key}"><span>${label}</span><strong>${amount(r.current)} <small>${unit}</small></strong><p class="report-change">较${before} ${difference} ${unit} · ${reason?esc(reasons[reason]):`${r.percent>0?'+':''}${num(r.percent)}%`}</p>
        <div class="report-pair">${[[before,r.previous,'previous'],[now,r.current,'current']].map(([name,value,cl])=>`<div class="${cl}"><span>${name}</span><i aria-hidden="true"><b style="width:${value===null?0:value/max*100}%" ${value===0?'class="zero"':''}></b></i><span>${amount(value)}</span></div>`).join('')}</div>${note?`<p class="insight-note">${esc(note)}</p>`:''}</article>`;
    }
    function comparisonSummary(){
      const s=data.current.samples,t=data.current.totals;
      return `<div class="report-comparison report-graph-grid" id="report-graph-summary">${comparisonCard('distance_km','已观测行程里程','km',1,`${s.distance} 条有效里程样本，含 ${s.partial_distance} 条片段`,'report-distance')}${comparisonCard('trip_count','结束行程','次',1,`完整 ${t.complete_trip_count} 次 · 片段 ${t.partial_trip_count} 次`)}${comparisonCard('duration_seconds','行程观测时段','小时',3600,`${s.duration} 条有效时段；非全程驾驶时长`)}${comparisonCard('estimated_kwh_per_100km','百公里电量估算','kWh/100km',1,`${s.efficiency} 条至少 10 km 且耗电至少 3 个百分点的样本`)}</div>`;
    }
    function energyComparison(){
      const [before,now]=periodName();
      return `<section class="card insight-panel" id="report-energy-comparison"><div class="insight-heading"><h3>耗电、充电与实付，${data.period==='week'?'两周':'两期'}对照</h3><span class="insight-note">${before} ${esc(data.previous.window.start_date)} — ${esc(data.previous.window.end_date)}</span></div><div class="report-energy-grid">${comparisonCard('trip_estimated_kwh','行程电量估算','kWh')}${comparisonCard('charge_count','结束充电','次')}${comparisonCard('charge_estimated_kwh','补入电量估算','kWh')}${comparisonCard('charging_paid_cents','充电实付','元',100)}</div><p class="insight-note report-chart-legend">各指标独立刻度，从 0 起算。电量按事件容量 × SOC 变化估算，非桩端计量；实付按账单日期汇总，不是${now}行驶成本。无有效值为“—”，已录免费账单为 0；费用待补时不算实付环比。</p></section>`;
    }
    function dailyChart(analysis){
      const [before,now]=periodName(),days=pairedDays(data.current,data.previous);
      const value=d=>!d?'无对应日':d.state==='future'?'未到':num(d.distance);
      const bar=(d,cl)=>`<i class="${cl}${d?.partial_trip_count?' partial':''}${d?.distance===0?' report-zero':''}" style="height:${(d?.ratio||0)*100}%"></i>`;
      return `<section class="card insight-panel" id="report-daily-comparison"><div class="insight-heading"><div><h3>每日里程趋势</h3><p class="insight-note">${data.period==='week'?'按星期':'按月内日期'}对齐 · 完整与片段均计入 · 按结束日期归属 · km</p></div><div class="report-series-legend"><span class="previous">${before}</span><span class="current">${now}</span><span class="partial">含片段</span>${dayFilter?button('显示整个周期','clear-day'):''}</div></div>
        <p class="insight-note">点击${now}日期看下方事件。两期使用同一刻度，柱高从 0 起算${analysis.peakDistance===null?'；本期暂无有效里程':`，本期最高 ${num(analysis.peakDistance)} km`}。</p>
        <div class="report-chart-scroll" tabindex="0" role="region" aria-label="每日里程两期对比图，可横向滚动"><div class="report-daily-chart report-paired-days" style="--day-count:${days.length}">${days.map(({current:day,previous})=>{
          const coverage={observed:'有归档观测',missing:'无归档观测',future:'未来日期'}[day.coverage];
          const label=`${day.date}，${day.state==='future'?'未来日期':day.distance===null?'无有效已观测里程':`已观测 ${num(day.distance)} km`}，行程 ${day.trip_count}，充电 ${day.charge_count}，${coverage}；${before} ${previous?previous.date:''} ${value(previous)}${previous?.distance!==null&&previous?' km':''}${day.partial_trip_count?'；本期含片段':''}`;
          return `<button data-report="day" data-date="${esc(day.date)}" data-distance-state="${day.state}" aria-label="${esc(label)}" title="${esc(label)}" aria-pressed="${dayFilter===day.date}" ${day.state==='future'?'disabled':''}><span class="report-day-value"><span class="previous">${value(previous)}</span><span>${value(day)}</span></span><span class="report-day-track" aria-hidden="true">${bar(previous,'previous')}${bar(day,'current')}</span><span class="report-day-date">${data.period==='week'?['日','一','二','三','四','五','六'][new Date(day.date+'T12:00:00+08:00').getUTCDay()]+' · ':''}${day.date.slice(8)}</span><span class="report-day-coverage" aria-hidden="true">${day.charge_count?'充电 '+day.charge_count+' 次':day.coverage==='observed'?'●':day.coverage==='missing'?'○':''}</span></button>`;
        }).join('')}</div></div><p class="insight-note report-chart-legend">— 无有效里程 · 0 已记录零里程 · 未到 未来日期 · 无对应日 上期没有该日期<br>● 有归档读取 · ○ 无归档读取。归档与行程事件来源不同；无归档日期仍可能有里程。缺记录不代表未用车；两期覆盖不同，不代表真实用车必然增减。</p></section>`;
    }
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const c=data?.current,t=c?.totals,s=c?.samples,w=c?.window,analysis=c?analyze(c):null;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">用车周报 · 月报</span><h2>把两期放在一起，看清变化</h2><p>先看与上一周期的差异，再看每天的用车变化。</p></div><span class="insight-source">本地结束事件</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>报告周期<select id="report-period" aria-label="报告周期"><option value="week" ${period==='week'?'selected':''}>自然周</option><option value="month" ${period==='month'?'selected':''}>自然月</option></select></label><label>周期内日期<input id="report-date" type="date" value="${esc(date)}"></label>${button('查看报告','load',!owner||!date,'id="report-load"')}</div>${!data&&!loading&&owner?'<p class="insight-note">选择查询条件后，点击查询按钮显示结果。</p>':''}${loading?button('停止分析','stop')+'<p role="status">正在汇总本地记录…</p>':''}${error?`<div class="notice error" role="alert">${esc(error)}${data?' · 保留上次报告和原周期。':''}</div>`:''}${!owner?'<p>连接车辆账号并取得当前车辆绑定后，可查看报告。</p>':''}
        ${data?`<div class="report-period-head"><div><h3 id="report-title">${esc(w.start_date)} — ${esc(w.end_date)}</h3><p class="insight-note">北京时间 · ${data.period==='week'?'周一至周日':'自然月'} · ${statusText[c.status]} · 统计截至 ${esc(time(data.as_of))}</p></div><div class="insight-actions">${button('上一周期','previous')}${button('下一周期','next')}</div></div>`:''}</section>
        ${data?`${comparisonSummary()}${energyComparison()}${dailyChart(analysis)}${observations(analysis)}
        <p class="insight-note">其中：片段已观测里程 ${num(t.partial_distance_km)} km，已计入总里程，不重复相加。电量估算需起止时间与 SOC 端点可核对、容量有效、没有充电混入或解码口径变化。未观测部分不补算。</p>
        <section class="card insight-panel"><h3>归档覆盖</h3><div class="parking-row-values">${metric('本期有归档读取的日期',c.coverage.days_with_reads,'天',`周期共 ${w.days} 天；有读取不等于全天覆盖`)}${metric('有效不同车辆时间',c.coverage.new_states,'个',`${c.coverage.reads} 次读取 · 重复 ${c.coverage.repeats} 次 · 修订 ${c.coverage.revisions} 次`)}${metric('旧值或异常观测',c.coverage.invalid_or_stale,'次','不算有效新状态')}${metric('上期有归档读取的日期',data.previous.coverage.days_with_reads,'天',`上期共 ${data.previous.window.days} 天`)}</div><p class="insight-note">本期首次读取 ${esc(time(c.coverage.first_read))}，最后读取 ${esc(time(c.coverage.last_read))}。归档覆盖按当前账号统计；事件保留当前车辆已有历史。没有归档不等于没有行程。${data.history_quality.unreadable_or_undated?`另有 ${data.history_quality.unreadable_or_undated} 条车辆历史记录格式或结束时间无效，无法归期（非仅本期）。`:''}</p></section>
        <section class="card insight-panel"><h3>常见出发时段</h3><p class="insight-note">按本期结束行程的已知开始时间统计，含片段。跨午夜行程仍按自身出发时刻计数。</p><div class="report-hours">${Array.from({length:6},(_,i)=>{const count=c.departure_hours.slice(i*4,i*4+4).reduce((a,b)=>a+b,0),max=Math.max(1,...Array.from({length:6},(_,j)=>c.departure_hours.slice(j*4,j*4+4).reduce((a,b)=>a+b,0)));return `<div><span>${String(i*4).padStart(2,'0')}—${String(i*4+3).padStart(2,'0')} 时</span><i aria-hidden="true" style="--bar:${count/max*100}%"></i><strong>${count} 次</strong></div>`;}).join('')}</div></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>本期结束事件${dayFilter?' · '+esc(dayFilter):''}</h3><div class="insight-toolbar"><label>事件类型<select id="report-kind" aria-label="事件类型">${[['all','全部事件'],['trip_end','行程'],['charge_end','充电']].map(([k,v])=>`<option value="${k}" ${kind===k?'selected':''}>${v}</option>`).join('')}</select></label><label>事件完整性<select id="report-quality" aria-label="事件完整性">${[['all','全部记录'],['complete','完整记录'],['partial','片段记录']].map(([k,v])=>`<option value="${k}" ${quality===k?'selected':''}>${v}</option>`).join('')}</select></label></div></div><div id="report-events"></div></section>`:''}`;
      if(data){const extra=document.createElement('div');extra.innerHTML=placesView()+'<section class="card insight-panel" id="report-automatic"></section>';node.querySelector('#report-observations')?.after(extra);automatic?.mount(node.querySelector('#report-automatic'));}
      paintEvents();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintEvents(){
      const el=node?.querySelector('#report-events');if(!el||!data)return;
      const rows=events(),pages=Math.max(1,Math.ceil(rows.length/12));page=Math.min(page,pages-1);
      el.innerHTML=`<p class="insight-note">匹配 ${rows.length} 条</p><div class="report-event-list">${rows.slice(page*12,page*12+12).map(row=>`<article data-report-event="${esc(row.id)}"><div class="insight-heading"><h4>${row.kind==='trip_end'?'行程':'充电'}</h4><span class="insight-badge ${row.partial?'insight-warning':''}">${row.partial?'片段记录':'完整记录'}</span></div><p>${esc(time(row.start_time))} → ${esc(time(row.end_time))}</p><div class="parking-row-values"><span>${row.kind==='trip_end'?'里程':'观测时长'}<strong>${row.kind==='trip_end'?num(row.distance_km)+' km':num(row.duration_seconds===null?null:row.duration_seconds/60)+' 分钟'}</strong></span><span>SOC 端点<strong>${num(row.start_soc)}% → ${num(row.end_soc)}%</strong></span><span>电量估算<strong>${num(row.estimated_kwh)} kWh</strong></span><span>事件记录容量<strong>${num(row.battery_capacity_kwh)} kWh</strong></span></div></article>`).join('')||'<p class="insight-empty">没有符合筛选的结束事件。没有记录不表示车辆未使用。</p>'}</div><div class="insight-pagination">${button('上一页事件','events-previous',page===0)}<span>${page+1} / ${pages}</span>${button('下一页事件','events-next',page+1===pages)}</div>`;
    }
    let analysisController=null;
    function invalidate(){analysisController?.abort();serial++;placesSerial++;places=null;placesError='';placesLoading=false;data=null;attempted=loading=false;error=dayFilter='';page=0;paint();}
    async function load(preserveSelection=false){
      if(!owner||!date||loading)return;analysisController=new AbortController();
      const token=++serial,identity=owner;
      attempted=true;loading=true;error='';paint();
      try{
        const result=await request(`/api/insights/report?period=${period}&date=${encodeURIComponent(date)}`,undefined,50000,{signal:analysisController.signal,active});
        if(!valid(token,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=result;placesSerial++;places=null;placesError='';placesLoading=false;if(!preserveSelection){dayFilter='';page=0;}
      }catch(failure){if(valid(token,identity))error=failure.message;}
      finally{if(valid(token,identity)){loading=false;paint();}}
    }
    let tripRevision,chargeRevision;
    function mount(container){
      const changed=owner!==context(),recordsChanged=tripRevision!==getState()?.trip_records_revision||chargeRevision!==getState()?.charge_records_revision,remount=node!==container;node=container;
      tripRevision=getState()?.trip_records_revision;chargeRevision=getState()?.charge_records_revision;
      if(changed){analysisController?.abort();owner=context();data=null;error='';loading=false;attempted=false;serial++;placesSerial++;places=null;placesError='';placesLoading=false;dayFilter='';page=0;}
      else if(recordsChanged&&attempted){analysisController?.abort();serial++;loading=false;load(true);}
      if(changed||remount)paint();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;
      if(automatic?.handle(event))return true;
      const el=event.target;
      if(event.type==='input'&&el.id==='report-date'){if(date!==el.value){date=el.value;invalidate();}return true;}
      if(event.type==='change'){
        if(el.id==='report-period'){if(period!==el.value){period=el.value;invalidate();}return true;}
        if(el.id==='report-kind')kind=el.value;
        else if(el.id==='report-quality')quality=el.value;
        else return false;
        page=0;paintEvents();return true;
      }
      if(event.type!=='click')return false;
      const target=el.closest('[data-report]');if(!target||target.disabled)return false;
      switch(target.dataset.report){
        case 'places':loadPlaces();break;
        case 'load':load();break;
        case 'stop':analysisController?.abort();serial++;loading=false;error='分析已取消。';paint();break;
        case 'previous':date=data.current.window.previous_date;period=data.period;invalidate();break;
        case 'next':date=data.current.window.next_date;period=data.period;invalidate();break;
        case 'day':dayFilter=target.dataset.date;page=0;paint();node.querySelector('#report-events').scrollIntoView({block:'start'});break;
        case 'clear-day':dayFilter='';page=0;paint();break;
        case 'events-previous':page--;paintEvents();break;
        case 'events-next':page++;paintEvents();break;
      }
      return true;
    }
    return {mount,handle};
  }
  root.UsageReportPage={create,analyze,compareValues,pairedDays};
})(window);
