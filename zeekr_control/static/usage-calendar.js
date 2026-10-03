(function(root){
  'use strict';
  const dateAt=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'未知';
  const money=value=>Number.isFinite(value)?(value/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}):'未知';
  const modes={distance:'里程',cost:'花费',pending:'待补账'};
  const coverage={future:'未来日期',missing:'无归档观测',limited:'仅重复或异常时间观测',observed:'有有效车辆时刻'};
  const marks={future:'未来',missing:'无归档',limited:'观测受限',observed:''};
  const eventTime=value=>Number.isFinite(value)?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value)):'未知';
  function create({getState,request,escape:esc,active,time,navigate}){
    let node=null,owner='',month=dateAt(Date.now()).slice(0,7),data=null,selected='',eventId='',eventPage=0;
    let mode='distance',billEvent='',billAmount='',saving=false,writeSerial=0,billError='',billStatus='';
    let attempted=false,loading=false,error='',serial=0;
    const context=()=>getState()?.insights_context||'';
    const valid=(token,identity)=>serial===token&&owner===identity&&context()===identity;
    const button=(label,action,disabled=false)=>`<button type="button" class="button secondary" data-calendar="${action}" ${disabled||saving?'disabled':''}>${label}</button>`;
    const eventsForDay=()=>(data?.events.filter(e=>e.first_date<=selected&&selected<=e.last_date)||[]).sort((a,b)=>(a.start_time??a.end_time)-(b.start_time??b.end_time));
    function paint(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const today=dateAt(Date.now());
      node.innerHTML=`<header class="calendar-header"><div><h2>用车日历</h2><p>看整月规律，选一天回顾、补账。</p></div><span>北京时间</span></header>
        <section class="card calendar-controls"><div class="insight-toolbar">${button('上一个月','previous',!month)}<label>日历月份<input id="calendar-month" type="month" value="${esc(month)}" ${saving?'disabled':''}></label>${button('下一个月','next',!month)}${button('读取用车日历','load',!owner||!month)}<label class="calendar-selected-control">回顾日期<input id="calendar-selected" ${saving?'disabled':''} type="date" value="${esc(selected)}" min="${esc(month)}-01" max="${data?.window.end_date||''}"></label></div>${!data?`<label class="calendar-mode-control">显示<select id="calendar-view" ${saving?'disabled':''} aria-label="日历显示内容">${Object.entries(modes).map(([key,label])=>`<option value="${key}" ${mode===key?'selected':''}>${label}</option>`).join('')}</select></label>`:''}${!data&&!loading&&owner?'<p class="insight-note">选择月份，点击“读取用车日历”。</p>':''}${loading?'<p role="status">正在读取本月观测…</p>':''}${error?`<p role="alert" class="notice error">${esc(error)}${data?' · 保留上次结果与原月份。':''}</p>`:''}${!owner?'<p>等待当前账号的车辆缓存后，可查看日历。</p>':''}</section>
        ${data?`${monthSummary()}<div class="calendar-layout"><section class="card insight-panel calendar-panel"><div class="calendar-month-heading"><h3 id="calendar-result-month">${esc(data.window.start_date.slice(0,7))} · 月历</h3><label class="calendar-mode-control">显示<select id="calendar-view" ${saving?'disabled':''} aria-label="日历显示内容">${Object.entries(modes).map(([key,label])=>`<option value="${key}" ${mode===key?'selected':''}>${label}</option>`).join('')}</select></label></div><div class="calendar-week" aria-hidden="true">${['一','二','三','四','五','六','日'].map(day=>`<span>周${day}</span>`).join('')}</div><div class="calendar-grid" role="group" aria-label="按日期查看用车记录">${Array.from({length:data.weekday_offset},()=>'<span aria-hidden="true"></span>').join('')}${data.days.map(day=>{
          const label=`${day.date}${day.date===today?'，今天':''}，行程 ${day.trip_count} 趟，充电 ${day.charge_count} 次，停车观测 ${day.parked_samples} 条，待补账 ${day.pending_count} 次，${coverage[day.coverage]}`;
          return `<button id="calendar-day-${day.date}" data-calendar-day="${day.date}" aria-label="${label}" aria-pressed="${selected===day.date}" ${day.date===today?'aria-current="date"':''} class="calendar-day ${day.coverage} ${dayLevel(day)} ${mode==='pending'&&!day.pending_count?'calendar-muted':''} ${day.pending_count?'calendar-needs-bill':''}"><span class="calendar-date"><strong>${Number(day.date.slice(-2))}</strong>${day.date===today?'<small>今天</small>':''}</span>${dayValue(day)}<span class="calendar-flags">${day.trip_count?`<span class="calendar-trip"><span>行程</span><span class="calendar-count">${day.trip_count} 趟</span></span>`:''}${day.charge_count?`<span class="calendar-charge"><span>充电</span><span class="calendar-count">${day.charge_count} 次</span></span>`:''}</span>${day.pending_count?`<span class="calendar-pending">待补 ${day.pending_count}</span>`:''}${marks[day.coverage]?`<span class="calendar-coverage">${marks[day.coverage]}</span>`:!day.trip_count&&!day.charge_count&&!day.parked_samples?'<span class="calendar-coverage">有观测</span>':''}</button>`;
        }).join('')}</div><p class="insight-note calendar-legend">深色表示本月数值较高。里程按结束日、花费按账单日；无归档不代表没有用车。</p><p class="insight-note calendar-as-of">数据截至 ${esc(time(data.as_of))}</p></section><aside class="calendar-detail-column" aria-label="选中日期的记录"><div id="calendar-day-detail"></div><div id="calendar-event-detail"></div></aside></div>
        <details class="card calendar-data-notes"><summary>数据说明 · 跨午夜、观测与估算口径</summary><p>跨午夜的已结束记录，在涉及日期都显示；各日数量不能直接相加。日格与月摘要按结束日期统计里程，不按天拆分；花费按账单日期统计实际充电费用，不含估算和停车费。尚未结束的记录不计入本页。</p><p>“停车观测”仅表示采到明确下电、有效零速且未充电的状态；不代表全天停放。无归档也不代表没有用车。“观测受限”表示仅有重复或异常时间观测。</p>${data.history_quality.unreadable_or_undated?`<p>事件库另有 ${data.history_quality.unreadable_or_undated} 条格式无效或无法归期的历史记录，未纳入日历。</p>`:''}</details>`:''}`;
      paintDay();paintEvent();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function monthSummary(){
      const t=data.totals;
      return `<section class="calendar-summary" aria-label="本月用车摘要"><button data-calendar-mode="distance" ${saving?'disabled':''}><span>有效里程</span><strong>${number(t.distance_km)} <small>km</small></strong><span>${t.distance_samples} / ${t.trip_count} 趟有里程</span></button><div><span>用车天数</span><strong>${t.usage_days} <small>天</small></strong><span>有行程涉及的日期</span></div><button data-calendar-mode="cost" ${saving?'disabled':''}><span>已记账充电费</span><strong>${money(t.actual_cents)} <small>元</small></strong><span>${t.actual_count} 笔已填金额${t.unpriced_count?' · '+t.unpriced_count+' 笔未填':''}</span></button><button data-calendar-mode="pending" ${saving?'disabled':''} id="calendar-pending-total"><span>充电待补账</span><strong>${t.pending_count} <small>次</small></strong><span>${t.pending_count?'点击找待补日期':'本月没有待补记录'}</span></button></section>`;
    }
    function dayLevel(day){
      const field=mode==='cost'?'actual_cents':mode==='pending'?'pending_count':'distance_km';
      const maximum=Math.max(0,...data.days.map(d=>d[field]||0)),value=day[field];
      return value>0?'calendar-level-'+Math.min(3,Math.ceil(value/maximum*3)):'';
    }
    function dayValue(day){
      if(day.coverage==='future'&&mode!=='cost')return '';
      if(mode==='cost')return day.actual_count?`<span class="calendar-primary">${money(day.actual_cents)}<small>元</small></span>`:day.unpriced_count?'<span class="calendar-primary calendar-unknown">金额未填</span>':'';
      if(mode==='pending')return day.pending_count?`<span class="calendar-primary">${day.pending_count}<small>次待补</small></span>`:'';
      return day.distance_km!==null?`<span class="calendar-primary">${number(day.distance_km)}<small>km</small></span>`:day.ended_trip_count?'<span class="calendar-primary calendar-unknown">里程未知</span>':'';
    }
    function paintDay(){
      const el=node?.querySelector('#calendar-day-detail'),day=data?.days.find(d=>d.date===selected);if(!el||!day)return;
      const rows=eventsForDay(),pages=Math.max(1,Math.ceil(rows.length/10));eventPage=Math.min(eventPage,pages-1);
      el.innerHTML=`<section class="card insight-panel calendar-day-panel"><div class="calendar-detail-heading"><h3>${day.date}</h3><span class="insight-badge">${coverage[day.coverage]}</span></div><p class="calendar-day-summary">行程 ${day.trip_count} 趟 · 充电 ${day.charge_count} 次${day.partial_count?` · 部分记录 ${day.partial_count} 条`:''}</p><p class="calendar-day-reading">${day.ended_trip_count?`结束行程里程 <strong>${number(day.distance_km)} km</strong>`:day.trip_count?'跨日行程里程归结束日':'本日没有结束行程'}<br>${day.actual_count?`当日账单已填 <strong>${money(day.actual_cents)} 元</strong>`:day.unpriced_count?`${day.unpriced_count} 笔账单金额未填`:'当天没有已填金额的充电账单'}${day.pending_count?` · <strong>${day.pending_count} 次待补</strong>`:''}</p><div class="insight-actions">${button('查看当日快照','snapshots',day.coverage==='future')}${button('打开充电账本','ledger')}</div>
        ${billError?`<p class="notice error" role="alert">${esc(billError)}</p>`:''}${billStatus?`<p role="status">${esc(billStatus)}</p>`:''}
        <div class="calendar-events"><h4>当天时间线</h4>${rows.slice(eventPage*10,eventPage*10+10).map(event=>{
          const trip=event.kind==='trip_end';
          return `<article class="calendar-event ${trip?'calendar-event-trip':'calendar-event-charge'}"><div class="calendar-event-heading"><strong>${trip?'行程':'充电'}</strong>${event.cross_midnight?'<span class="insight-badge">跨午夜</span>':''}${event.partial?'<span class="insight-badge insight-warning">部分记录</span>':''}${!trip&&event.needs_bill?'<span class="insight-badge insight-warning">待补账</span>':''}</div><p class="calendar-event-time">${esc(eventTime(event.start_time))} — ${esc(eventTime(event.end_time))}</p>${trip?`<p class="calendar-route">${esc(event.start_label||'起点未知')} → ${esc(event.end_label||'终点未知')}</p><p class="calendar-event-value">整趟里程 <strong>${number(event.distance_km)} km</strong> · ${number(event.duration_seconds===null?null:event.duration_seconds/60)} 分钟<br>有效 SOC 耗电估算 <strong>${number(event.estimated_kwh)} kWh</strong></p>`:`<p class="calendar-event-value">起止 SOC <strong>${number(event.start_soc)}% → ${number(event.end_soc)}%</strong><br>${event.bill?`已记账 <strong>${money(event.bill.actual_cents)} 元</strong> · 账单日期 ${esc(event.bill.date)}`:'金额未记录'}</p>`}<div class="insight-actions"><button class="button secondary" data-calendar-event="${esc(event.id)}" aria-expanded="${eventId===event.id}">查看${trip?'行程':'充电'}详情</button>${!trip&&event.needs_bill?`<button class="button" data-calendar-bill="${esc(event.id)}" ${saving?'disabled':''}>${event.bill?'补充金额':'补金额'}</button>`:''}</div>
          ${billEvent===event.id?`<form id="calendar-bill-form" class="calendar-bill-form"><p>关联本次充电 · 账单日期 ${esc(event.bill?.date||event.end_date)}</p><label>实际充电金额（元）<input id="calendar-bill-amount" type="number" inputmode="decimal" min="0" max="1000000" step="0.01" required value="${esc(billAmount)}" ${saving?'disabled':''}></label><p class="insight-note">明确免费填 0；不会推算费用。更多账单字段在充电账本编辑。</p><div class="insight-actions">${button(saving?'正在保存…':'保存金额','bill-save',loading)}${button('取消补账','bill-cancel')}</div></form>`:''}</article>`;
        }).join('')||`<p class="insight-empty">${day.coverage==='future'?'未来日期，尚无历史记录。':'没有涉及本日的已结束事件；不代表没有用车。'}</p>`}</div>${rows.length>10?`<div class="insight-pagination">${button('上一页当日记录','events-previous',eventPage===0)}<span>${eventPage+1} / ${pages}</span>${button('下一页当日记录','events-next',eventPage+1===pages)}</div>`:''}<details class="calendar-observation-notes"><summary>当日采集说明${day.partial_count?' · 存在部分记录':''}</summary><p>归档读取 ${day.reads} 次，去重后有效车辆时刻 ${day.effective_states} 个。${day.reads?`采集范围 ${esc(time(day.first_read))} — ${esc(time(day.last_read))}`:''}</p>${day.parked_samples?`<p>有停车观测 ${day.parked_samples} 个车辆时刻；首末 ${esc(time(day.parking_first))} — ${esc(time(day.parking_last))}；中间未必连续，不估算全天停车。</p>`:''}${day.partial_count?`<p>部分记录 ${day.partial_count} 条，起止或过程存在缺失。</p>`:''}</details></section>`;
      node.querySelector('#calendar-bill-form')?.addEventListener('submit',event=>{event.preventDefault();saveBill();});
    }
    async function saveBill(){
      const event=eventsForDay().find(e=>e.id===billEvent);
      if(!event||saving||loading||!data||!node.querySelector('#calendar-bill-form')?.reportValidity())return;
      const identity=owner,token=++writeSerial,bill=event.bill;
      const payload={action:'save',context:identity,revision:data.ledger_revision,event_id:event.id,id:bill?.id||'',date:bill?.date||event.end_date,source:bill?.source||'unknown',amount:billAmount,note:bill?.note||'',metered_kwh:bill?.metered_kwh??null,unit_price:bill?.unit_price??null,service_fee:bill?.service_fee_cents===null||!bill?null:bill.service_fee_cents/100,parking_fee:bill?.parking_fee_cents===null||!bill?null:bill.parking_fee_cents/100,charge_mode_override:bill?.charge_mode_override||''};
      saving=true;billError=billStatus='';paint();
      try{
        const result=await request('/api/insights/ledger',payload);
        if(token!==writeSerial||owner!==identity||context()!==identity)return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data.ledger_revision=result.revision;billEvent='';billAmount='';billStatus='金额已保存。';
        await load();
        if(error)billStatus+=' 日历尚未刷新，请重新读取核对。';
      }catch(failure){if(token===writeSerial&&owner===identity&&context()===identity)billError=failure.message+' 填写内容保留；请重新读取核对。';}
      finally{if(token===writeSerial&&owner===identity&&context()===identity){saving=false;paint();}}
    }
    function paintEvent(){
      const el=node?.querySelector('#calendar-event-detail'),event=eventsForDay().find(e=>e.id===eventId);if(!el)return;
      if(!event){el.innerHTML='';return;}
      const trip=event.kind==='trip_end';
      el.innerHTML=`<section class="card insight-panel"><div class="insight-heading"><h3>${trip?'行程':'充电'}详情${event.cross_midnight?' · 跨午夜':''}</h3><span class="insight-badge">${event.partial?'部分记录':'完整记录'}</span></div><p>起点 ${esc(time(event.start_time))}<br>终点 ${esc(time(event.end_time))}</p><div class="insight-metrics"><div><span>${trip?'整趟里程':'充电类型'}</span><strong>${trip?number(event.distance_km)+' km':({ac:'交流',dc:'直流'}[event.charge_mode]||'未知')}</strong></div><div><span>整段观测时长</span><strong>${number(event.duration_seconds===null?null:event.duration_seconds/60)} 分钟</strong></div><div><span>起止 SOC</span><strong>${number(event.start_soc)}% → ${number(event.end_soc)}%</strong></div><div><span>SOC 电量估算</span><strong>${number(event.estimated_kwh)} kWh</strong></div></div><p class="insight-note">${event.partial?'起止或过程存在缺失，不能按完整记录理解。':'记录未标记为部分，不表示位置轨迹完整。'} 以上为整条事件摘要，不按本日时长分摊里程或电量。SOC 电量仅为容量与 SOC 变化换算，不是电表计量；无有效证据时显示未知。</p></section>`;
    }
    function invalidate(){serial++;data=null;attempted=loading=false;billEvent=billError=billStatus='';error=selected=eventId='';eventPage=0;paint();}
    async function load(){
      if(!owner||!month)return;const identity=owner,token=++serial,target=month;loading=attempted=true;error='';paint();
      try{const result=await request('/api/insights/calendar?date='+encodeURIComponent(target+'-01'));
        if(!valid(token,identity))return;if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=result;
        if(!data.days.some(d=>d.date===selected))selected=data.days.find(d=>d.date===dateAt(data.as_of))?.date||data.days.find(d=>d.trip_count||d.charge_count||d.reads)?.date||data.days[0].date;
        eventId='';eventPage=0;
      }catch(failure){if(valid(token,identity))error=failure.message;}
      finally{if(valid(token,identity)){loading=false;paint();}}
    }
    let tripRevision,chargeRevision;
    function mount(container){
      const changed=owner!==context()||tripRevision!==getState()?.trip_records_revision||chargeRevision!==getState()?.charge_records_revision,remount=node!==container;node=container;
      tripRevision=getState()?.trip_records_revision;chargeRevision=getState()?.charge_records_revision;
      if(changed){writeSerial++;saving=false;billEvent=billAmount=billError=billStatus='';owner=context();data=null;selected=eventId='';eventPage=0;attempted=loading=false;error='';serial++;}
      if(changed||remount)paint();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if(event.type==='input'&&el.id==='calendar-bill-amount'){billAmount=el.value;return true;}
      if(saving)return true;
      if(event.type==='change'&&el.id==='calendar-view'){mode=el.value;paint();return true;}
      if(event.type==='input'&&el.id==='calendar-selected'){if(!el.value||!el.value.startsWith(month))return true;selected=el.value;eventId=billEvent=billError=billStatus='';eventPage=0;paint();return true;}
      if(event.type==='input'&&el.id==='calendar-month'){if(month!==el.value){month=el.value;invalidate();}return true;}
      if(event.type!=='click')return false;
      const summary=el.closest('[data-calendar-mode]'),billButton=el.closest('[data-calendar-bill]');
      if(summary){mode=summary.dataset.calendarMode;if(mode==='pending'){const first=data.days.find(d=>d.pending_count);if(first)selected=first.date;}eventId=billEvent=billError=billStatus='';eventPage=0;paint();return true;}
      if(billButton){billEvent=billButton.dataset.calendarBill;billAmount='';billError=billStatus='';paintDay();node.querySelector('#calendar-bill-amount')?.focus({preventScroll:true});return true;}
      const day=el.closest('[data-calendar-day]'),item=el.closest('[data-calendar-event]');
      if(day){selected=day.dataset.calendarDay;eventId=billEvent=billError=billStatus='';eventPage=0;paint();if(innerWidth<1200)node.querySelector('#calendar-day-detail')?.scrollIntoView({block:'start'});return true;}
      if(item){eventId=item.dataset.calendarEvent;paintDay();paintEvent();node.querySelector('#calendar-event-detail').scrollIntoView({block:'start'});return true;}
      const target=el.closest('[data-calendar]');if(!target||target.disabled)return false;
      const action=target.dataset.calendar;
      if(action==='load'){billError=billStatus='';load();}
      else if(action==='bill-save')saveBill();
      else if(action==='bill-cancel'){billEvent='';paint();}
      else if(action==='ledger')navigate('ledger',selected);
      else if(action==='previous'||action==='next'){
        const [year,index]=month.split('-').map(Number),date=new Date(Date.UTC(year,index-1+(action==='next'?1:-1),1));
        month=date.toISOString().slice(0,7);invalidate();
      }else if(action==='snapshots')navigate('time',selected);
      else if(action==='events-previous'){eventPage--;paintDay();}else if(action==='events-next'){eventPage++;paintDay();}
      return true;
    }
    return {mount,handle};
  }
  root.UsageCalendarPage={create};
})(window);
