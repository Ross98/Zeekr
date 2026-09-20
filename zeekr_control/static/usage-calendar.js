(function(root){
  'use strict';
  const dateAt=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'未知';
  const coverage={future:'未来日期',missing:'无归档观测',limited:'仅重复或异常时间观测',observed:'有有效车辆时刻'};
  const marks={future:'未',missing:'缺',limited:'限',observed:'观'};
  function create({getState,request,escape:esc,active,time,navigate}){
    let node=null,owner='',month=dateAt(Date.now()).slice(0,7),data=null,selected='',eventId='',eventPage=0;
    let attempted=false,loading=false,error='',serial=0;
    const context=()=>getState()?.insights_context||'';
    const valid=(token,identity)=>serial===token&&owner===identity&&context()===identity;
    const button=(label,action,disabled=false)=>`<button class="button secondary" data-calendar="${action}" ${disabled?'disabled':''}>${label}</button>`;
    const eventsForDay=()=>data?.events.filter(e=>e.first_date<=selected&&selected<=e.last_date)||[];
    function paint(){
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">用车日历</span><h2>一个月，逐日回看</h2><p>行程、充电、停车观测，放回各自发生的日子。</p></div><span class="insight-source">本地记录 · 北京时间</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>日历月份<input id="calendar-month" type="month" value="${esc(month)}"></label>${button('读取用车日历','load',!owner||!month)}${button('上一个月','previous',!month)}${button('下一个月','next',!month)}</div>${loading?'<p role="status">正在读取本月观测…</p>':''}${error?`<p role="alert" class="notice error">${esc(error)}${data?' · 保留上次结果与原月份。':''}</p>`:''}${!owner?'<p>等待当前账号的车辆缓存后，可查看日历。</p>':''}<p class="insight-note">跨午夜的已结束记录，在涉及日期都显示；各日数量不能直接相加。行程里程和电量仍是整趟数值，不按天拆分。尚未结束的记录不计入本页。</p></section>
        ${data?`<section class="card insight-panel calendar-panel"><div class="insight-heading"><h3 id="calendar-result-month">${esc(data.window.start_date.slice(0,7))} · 月历</h3><span class="insight-note">截至 ${esc(time(data.as_of))}</span></div><div class="calendar-week" aria-hidden="true">${['一','二','三','四','五','六','日'].map(day=>`<span>${day}</span>`).join('')}</div><div class="calendar-grid" role="group" aria-label="按日期查看用车记录">${Array.from({length:data.weekday_offset},()=>'<span aria-hidden="true"></span>').join('')}${data.days.map(day=>{
          const label=`${day.date}，行程 ${day.trip_count}，充电 ${day.charge_count}，停车观测 ${day.parked_samples} 条，${coverage[day.coverage]}`;
          return `<button id="calendar-day-${day.date}" data-calendar-day="${day.date}" aria-label="${label}" aria-pressed="${selected===day.date}" class="calendar-day ${day.coverage}"><strong>${Number(day.date.slice(-2))}</strong><span class="calendar-flags">${day.trip_count?`<span class="calendar-trip">行<span class="calendar-count"> ${day.trip_count}</span></span>`:''}${day.charge_count?`<span class="calendar-charge">充<span class="calendar-count"> ${day.charge_count}</span></span>`:''}${day.parked_samples?'<span class="calendar-parked">停</span>':''}</span><span class="calendar-coverage">${marks[day.coverage]}</span></button>`;
        }).join('')}</div><p class="insight-note calendar-legend">行：行程 · 充：充电 · 停：有停车观测<br>观：有有效车辆时刻 · 限：仅重复或异常时间 · 缺：无归档 · 未：未来日期。点日期看数量与详情。</p><p class="insight-note">“有停车观测”仅表示采到明确下电、有效零速且未充电的状态；不代表全天停放。无归档也不代表没有用车。</p>${data.history_quality.unreadable_or_undated?`<p class="insight-note">事件库另有 ${data.history_quality.unreadable_or_undated} 条格式无效或无法归期的历史记录，未纳入日历。</p>`:''}</section><div id="calendar-day-detail"></div><div id="calendar-event-detail"></div>`:''}`;
      paintDay();paintEvent();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintDay(){
      const el=node?.querySelector('#calendar-day-detail'),day=data?.days.find(d=>d.date===selected);if(!el||!day)return;
      const rows=eventsForDay(),pages=Math.max(1,Math.ceil(rows.length/10));eventPage=Math.min(eventPage,pages-1);
      el.innerHTML=`<section class="card insight-panel"><div class="insight-heading"><h3>${day.date} · 当日记录</h3><span class="insight-badge">${coverage[day.coverage]}</span></div><p>行程 ${day.trip_count} 趟 · 充电 ${day.charge_count} 次 · 其中部分记录 ${day.partial_count} 条</p><p class="insight-note">归档读取 ${day.reads} 次，去重后有效车辆时刻 ${day.effective_states} 个。${day.reads?`采集范围 ${esc(time(day.first_read))} → ${esc(time(day.last_read))}`:''}</p>${day.parked_samples?`<p>有停车观测：${day.parked_samples} 个车辆时刻</p><p class="insight-note">车辆时间首末 ${esc(time(day.parking_first))} → ${esc(time(day.parking_last))}；中间未必连续，不按两端差值计算停车时长。按采集日期归入本日。</p>`:''}<div class="insight-actions">${button('查看当日快照','snapshots',day.coverage==='future')}${button('查看当日停车片段','parking',!day.parked_samples)}</div><div class="calendar-events">${rows.slice(eventPage*10,eventPage*10+10).map(event=>`<article class="rule-record"><div class="insight-heading"><h4>${event.kind==='trip_end'?'行程':'充电'}${event.cross_midnight?' · 跨午夜':''}</h4><span class="insight-badge">${event.partial?'部分记录':'完整记录'}</span></div><p>${esc(time(event.start_time))} → ${esc(time(event.end_time))}</p><p>${event.kind==='trip_end'?'整趟里程 '+number(event.distance_km)+' km':'起止 SOC '+number(event.start_soc)+'% → '+number(event.end_soc)+'%'}</p><button class="button secondary" data-calendar-event="${esc(event.id)}">查看${event.kind==='trip_end'?'行程':'充电'}详情</button></article>`).join('')||`<p class="insight-empty">${day.coverage==='future'?'未来日期，尚无历史记录。':'没有涉及本日的已结束事件；不代表没有用车。'}</p>`}</div>${rows.length?`<div class="insight-pagination">${button('上一页当日记录','events-previous',eventPage===0)}<span>${eventPage+1} / ${pages}</span>${button('下一页当日记录','events-next',eventPage+1===pages)}</div>`:''}</section>`;
    }
    function paintEvent(){
      const el=node?.querySelector('#calendar-event-detail'),event=eventsForDay().find(e=>e.id===eventId);if(!el)return;
      if(!event){el.innerHTML='';return;}
      const trip=event.kind==='trip_end';
      el.innerHTML=`<section class="card insight-panel"><div class="insight-heading"><h3>${trip?'行程':'充电'}详情${event.cross_midnight?' · 跨午夜':''}</h3><span class="insight-badge">${event.partial?'部分记录':'完整记录'}</span></div><p>起点 ${esc(time(event.start_time))}<br>终点 ${esc(time(event.end_time))}</p><div class="insight-metrics"><div><span>${trip?'整趟里程':'充电类型'}</span><strong>${trip?number(event.distance_km)+' km':({ac:'交流',dc:'直流'}[event.charge_mode]||'未知')}</strong></div><div><span>整段观测时长</span><strong>${number(event.duration_seconds===null?null:event.duration_seconds/60)} 分钟</strong></div><div><span>起止 SOC</span><strong>${number(event.start_soc)}% → ${number(event.end_soc)}%</strong></div><div><span>SOC 电量估算</span><strong>${number(event.estimated_kwh)} kWh</strong></div></div><p class="insight-note">${event.partial?'起止或过程存在缺失，不能按完整记录理解。':'记录未标记为部分，不表示位置轨迹完整。'} 以上为整条事件摘要，不按本日时长分摊里程或电量。SOC 电量仅为容量与 SOC 变化换算，不是电表计量；无有效证据时显示未知。</p></section>`;
    }
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
    function mount(container){
      const changed=owner!==context(),remount=node!==container;node=container;
      if(changed){owner=context();data=null;selected=eventId='';eventPage=0;attempted=loading=false;error='';serial++;}
      if(changed||remount)paint();if(owner&&!attempted&&!loading)load();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if(event.type==='input'&&el.id==='calendar-month'){month=el.value;return true;}
      if(event.type!=='click')return false;
      const day=el.closest('[data-calendar-day]'),item=el.closest('[data-calendar-event]');
      if(day){selected=day.dataset.calendarDay;eventId='';eventPage=0;paint();return true;}
      if(item){eventId=item.dataset.calendarEvent;paintEvent();node.querySelector('#calendar-event-detail').scrollIntoView({block:'start'});return true;}
      const target=el.closest('[data-calendar]');if(!target||target.disabled)return false;
      const action=target.dataset.calendar;
      if(action==='load')load();
      else if(action==='previous'||action==='next'){
        const [year,index]=month.split('-').map(Number),date=new Date(Date.UTC(year,index-1+(action==='next'?1:-1),1));
        month=date.toISOString().slice(0,7);load();
      }else if(action==='snapshots'||action==='parking')navigate(action==='snapshots'?'time':'parking',selected);
      else if(action==='events-previous'){eventPage--;paintDay();}else if(action==='events-next'){eventPage++;paintDay();}
      return true;
    }
    return {mount,handle};
  }
  root.UsageCalendarPage={create};
})(window);
