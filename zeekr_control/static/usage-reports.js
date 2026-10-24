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
  function departureBins(hours){
    return Array.from({length:6},(_,i)=>{
      const slice=Array.isArray(hours)?hours.slice(i*4,i*4+4):[];
      return slice.length===4&&slice.every(v=>Number.isInteger(v)&&v>=0)?slice.reduce((a,b)=>a+b,0):null;
    });
  }
  function eventGraphic(row,maxima){
    const valid=(v,max=1e12)=>Number.isFinite(v)&&v>=0&&v<=max?v:null;
    const trip=row.kind==='trip_end',value=valid(trip?row.distance_km:Number.isFinite(row.duration_seconds)?row.duration_seconds/60:null);
    const energy=valid(row.estimated_kwh),startSoc=valid(row.start_soc,100),endSoc=valid(row.end_soc,100);
    return {value,ratio:value===null?null:value/Math.max(1,maxima[trip?'trip':'charge']),unit:trip?'km':'分钟',
      energy,energyRatio:energy===null?null:energy/Math.max(1,maxima.energy),
      startSoc:startSoc===null||endSoc===null?null:startSoc,endSoc:startSoc===null||endSoc===null?null:endSoc};
  }
  function changeExtent(values){
    const max=values.reduce((m,v)=>Number.isFinite(v)?Math.max(m,Math.abs(v)):m,0);
    return Math.max(60,Math.ceil(max/30)*30);
  }
  function deltaGeometry(value,extent){
    if(!Number.isFinite(value)||!Number.isFinite(extent)||extent<=0)return null;
    const width=Math.min(50,Math.abs(value)/extent*50);
    return {left:value<0?50-width:50,width,negative:value<0};
  }
  function dailyDeltas(current,previous){
    return pairedDays(current,previous).map(row=>({...row,difference:row.current.distance===null||!row.previous||row.previous.distance===null?null:
      Math.round((row.current.distance-row.previous.distance)*1e6)/1e6}));
  }
  function differenceDomain(values){
    let low=0,high=0;for(const v of values)if(Number.isFinite(v)){low=Math.min(low,v);high=Math.max(high,v);}
    if(low===high)return {low:0,high:1,ticks:[0,1]};
    const target=(high-low)/3,power=10**Math.floor(Math.log10(target));
    const step=[1,2,5,10].find(v=>v*power>=target)*power;
    low=Math.floor(low/step)*step;high=Math.ceil(high/step)*step;
    const ticks=Array.from({length:Math.round((high-low)/step)+1},(_,i)=>Number((low+i*step).toPrecision(10)));
    return {low,high,ticks};
  }
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',period='week',date=currentDate(),data=null,error='',loading=false,attempted=false,serial=0;
    let dayFilter='',kind='all',quality='all',page=0,selectedEvent='';
    const context=()=>getState()?.insights_context||'';
    let places=null,placesError='',placesLoading=false,placesSerial=0;
    const automatic=root.AutomaticInsightsPage?.create({getState,request,escape:esc,active,time,compact:true,navigate:()=>{}});
    function placesView(){
      if(data?.period!=='week')return '';
      const item=p=>`<article><h4>${esc(p.label)}</h4>${pairBars(p.departures,p.arrivals,v=>num(v)+' 次',null,['出发','到达'])}</article>`;
      const unknown=places&&(places.unknown_departures||places.unknown_arrivals)?item({label:'未识别参考地点',departures:places.unknown_departures,arrivals:places.unknown_arrivals}):'';
      const content=places?`<div class="report-place-graphs">${places.places.slice(0,2).map(item).join('')||'<p>暂无可信地点记录。</p>'}${unknown}</div>${places.places.length>2?`<details class="report-more-places"><summary>更多地点（${places.places.length-2}）</summary><div class="report-place-graphs">${places.places.slice(2).map(item).join('')}</div></details>`:''}`:'';
      return `<div class="report-reference-place"><div class="insight-heading"><h4>参考地点</h4><button class="button secondary" data-report="places" ${placesLoading?'disabled':''}>读取本周地点</button></div><div id="report-places">${placesLoading?'<p role="status">正在读取地点…</p>':placesError?`<p role="alert">${esc(placesError)}</p>`:places?content:'<p class="insight-note">按需读取参考地点，不保证真实目的地。</p>'}</div></div>`;
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
    function pairBars(previous,current,format=num,maximum=null,labels=periodName()){
      const valid=v=>Number.isFinite(v)&&v>=0?v:null;
      const a=valid(previous),b=valid(current),max=Math.max(1,maximum??Math.max(a||0,b||0));
      return `<div class="report-pair">${[[labels[0],a,'previous'],[labels[1],b,'current']].map(([name,value,cl])=>`<div class="${cl}"><span>${esc(name)}</span><i aria-hidden="true"><b style="width:${value===null?0:Math.min(100,value/max*100)}%" ${value===0?'class="zero"':''}></b></i><span>${esc(format(value))}</span></div>`).join('')}</div>`;
    }
    function coverageChart(){
      const [before,now]=periodName();
      const calendars=[[before,data.previous],[now,data.current]].map(([label,period])=>`<div class="report-coverage-row"><span>${label}</span><div class="report-coverage-cells" style="--coverage-days:${period.days.length}" role="img" aria-label="${esc(label+'：'+period.days.map(d=>d.date+' '+({observed:'有读取',missing:'无读取',future:'未来日期'}[d.coverage])).join('；'))}">${period.days.map(d=>`<i class="${d.coverage}" title="${esc(d.date)}" aria-hidden="true"></i>`).join('')}</div><span>${period.coverage.days_with_reads} 天</span></div>`).join('');
      return `<section class="card insight-panel" id="report-coverage"><div class="insight-heading"><h3>归档、片段与地点</h3></div><div class="report-reference-grid ${data.period==='month'?'no-places':''}"><div><h4>有归档读取的日期</h4>${calendars}</div><div><h4>片段记录</h4>${pairBars(data.previous.totals.partial_trip_count,data.current.totals.partial_trip_count,v=>num(v)+' 次')}</div>${placesView()}</div><p class="insight-note report-compact-foot">有采样不代表全天覆盖；空格为无归档读取，虚线格为未来日期。片段已计入已记录里程，不补算缺失部分。地点仅供参考。${data.history_quality.unreadable_or_undated?`另有 ${data.history_quality.unreadable_or_undated} 条历史记录无法归期。`:''}</p></section>`;
    }
    function deltaPlot(value,extent,status=''){
      const geometry=deltaGeometry(value,extent);
      if(!geometry)return `<span class="report-delta-status">${esc(status||'无有效值')}</span>`;
      return `<span class="report-delta-plot" aria-hidden="true">${[0,25,50,75,100].map(t=>`<i class="tick ${t===50?'center':''}" style="left:${t}%"></i>`).join('')}${geometry.width?`<i class="bar ${geometry.negative?'negative':''}" style="left:${geometry.left}%;width:${geometry.width}%"></i>`:'<i class="zero"></i>'}</span>`;
    }
    function departureChart(){
      const previous=departureBins(data.previous.departure_hours),current=departureBins(data.current.departure_hours);
      const diffs=current.map((v,i)=>v===null||previous[i]===null?null:v-previous[i]);
      const max=Math.max(2,...diffs.filter(Number.isFinite).map(Math.abs));
      return `<section class="card insight-panel" id="report-departure"><div class="insight-heading"><div><h3>出发时段变化</h3><p class="insight-note">${periodName().join(' → ')} · 次</p></div></div><div class="report-hour-deltas">${current.map((count,i)=>`<div><span>${String(i*4).padStart(2,'0')}—${String(i*4+3).padStart(2,'0')} 时</span><span>${num(previous[i])} → ${num(count)}</span>${deltaPlot(diffs[i],max)}<b>${signed(diffs[i])}</b></div>`).join('')}</div><p class="insight-note report-compact-foot">按已知出发时刻统计，含片段；共用 −${num(max)}～+${num(max)} 次刻度。缺少开始时间的记录不分配时段。</p></section>`;
    }
    const periodName=()=>data.period==='week'?['上周','本周']:['上期','本期'];
    const signed=(value,format=num)=>!Number.isFinite(value)?'—':(value>0?'+':value<0?'−':'')+format(Math.abs(value));
    const plotNum=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:6}).format(value):'—';
    const coreMetrics=[['distance_km','已记录里程','km'],['trip_count','结束行程','次'],['duration_seconds','观测时段','小时',3600],['estimated_kwh_per_100km','百公里耗电估算','kWh/100km']];
    const energyMetrics=[['trip_estimated_kwh','行程耗电估算','kWh'],['charge_count','结束充电','次'],['charge_estimated_kwh','充入电量估算','kWh'],['charging_paid_cents','充电实付','元',100]];
    function metricChange(key){
      const r=compareValues(data.previous.totals[key],data.current.totals[key],data.comparison.comparable);
      if(key==='charging_paid_cents'&&[data.current,data.previous].some(p=>p.payments?.unpriced_bill_count||p.payments?.pending_charge_bill_count))return {...r,percent:null,reason:'incomplete_bills'};
      return r;
    }
    function comparisonCard([key,label,unit,scale=1],extent){
      const r=metricChange(key),[before,now]=periodName();
      const amount=v=>!Number.isFinite(v)?'—':key==='charging_paid_cents'?(v/scale).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}):num(v/scale);
      const reason=r.reason?reasons[r.reason]:'';
      return `<article class="report-delta-row" ${key==='distance_km'?'id="report-distance"':''} data-report-metric="${key}" aria-label="${esc(label+'，'+before+' '+amount(r.previous)+'，'+now+' '+amount(r.current)+' '+unit+'，'+(reason||'环比 '+signed(r.percent)+'%'))}"><div class="report-delta-label"><h4>${label}</h4><span class="report-values"><small>${before}</small> ${amount(r.previous)} → <strong>${amount(r.current)}</strong> <small>${unit}</small></span></div><div class="report-delta-line">${deltaPlot(r.percent,extent,reason)}<span class="report-delta-change"><b>${r.percent===null?'—':signed(r.percent)+'%'}</b><small>${signed(r.difference,amount)}${unit.length<=5?' '+unit:''}</small></span></div></article>`;
    }
    function comparisonPanel(metrics,title,id){
      const extent=changeExtent(coreMetrics.concat(energyMetrics).map(([key])=>metricChange(key).percent));
      return `<section class="card insight-panel" id="${id}"><div class="insight-heading"><h3>${title}</h3></div><div class="report-delta-axis" aria-hidden="true"><span>−${num(extent)}%</span><span>0</span><span>+${num(extent)}%</span></div>${metrics.map(row=>comparisonCard(row,extent)).join('')}</section>`;
    }
    function dailyChart(){
      const days=dailyDeltas(data.current,data.previous),domain=differenceDomain(days.map(d=>d.difference));
      const span=domain.high-domain.low,position=value=>(value-domain.low)/span*100,zero=position(0);
      const [before,now]=periodName(),weekday=['日','一','二','三','四','五','六'];
      return `<section class="card insight-panel" id="report-daily-comparison"><div class="insight-heading"><div><h3>每日里程增减</h3><p class="insight-note">${now} − ${before} · km · ${data.period==='week'?'按星期':'按月内日期'}对齐</p></div>${dayFilter?button('显示整个周期','clear-day'):''}</div><div class="report-chart-scroll" tabindex="0" role="region" aria-label="每日里程增减图"><div class="report-day-chart-layout ${days.some(d=>d.difference!==null)?'':'report-no-deltas'}" style="--day-count:${days.length}"><div class="report-day-axis" aria-hidden="true">${domain.ticks.map(t=>`<span style="bottom:${position(t)}%">${plotNum(t)}</span>`).join('')}</div><div class="report-daily-chart report-delta-days" style="--day-count:${days.length}">${days.map(({current:day,previous,difference})=>{
        const reason=day.state==='future'?'未来日期':!previous?'上期无对应日':difference===null?'差额未知':signed(difference,plotNum)+' km';
        const label=`${day.date}，本期已观测 ${plotNum(day.distance)} km；${before} ${previous?.date||'无对应日'} ${plotNum(previous?.distance)} km；${reason}；${day.partial_trip_count?'含片段；':''}行程 ${day.trip_count}，充电 ${day.charge_count}`;
        const end=difference===null?zero:position(difference),height=Math.abs(end-zero),partial=day.partial_trip_count||previous?.partial_trip_count;
        return `<button data-report="day" data-date="${esc(day.date)}" data-distance-state="${day.state}" data-difference="${difference===null?'':difference}" aria-label="${esc(label)}" title="${esc(label)}" aria-pressed="${dayFilter===day.date}" ${day.state==='future'?'disabled':''}><span class="report-day-value">${day.state==='future'?'未到':!previous?'无对应日':signed(difference,plotNum)}</span><span class="report-delta-track" aria-hidden="true">${domain.ticks.map(t=>`<i class="grid ${t===0?'baseline':''}" style="bottom:${position(t)}%"></i>`).join('')}${difference===null?'':difference===0?`<i class="flat" style="bottom:${zero}%"></i>`:`<i class="bar ${difference<0?'negative':''} ${partial?'partial':''}" style="bottom:${Math.min(zero,end)}%;height:${height}%"></i>`}</span><span class="report-day-date">${data.period==='week'?weekday[new Date(day.date+'T12:00:00+08:00').getUTCDay()]+' · ':''}${day.date.slice(8)}</span><span class="report-day-coverage" aria-hidden="true">${day.charge_count?'充电 '+day.charge_count+' 次':day.coverage==='observed'?'●':day.coverage==='missing'?'○':''}</span></button>`;
      }).join('')}</div></div></div><p class="insight-note report-compact-foot">点击日期看记录。— 为差额未知，0 为已知零差额；不把缺记录当作零。${days.every(d=>d.difference===null)?'当前没有可比较的日期；本期记录仍可点击查看。':''}橙色含片段；有归档读取不等于全天覆盖。</p></section>`;
    }
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      const c=data?.current,w=c?.window;
      node.classList.add('report-compact');
      node.innerHTML=`<section class="card insight-panel report-controls"><div class="insight-toolbar"><label>报告周期<select id="report-period" aria-label="报告周期"><option value="week" ${period==='week'?'selected':''}>自然周</option><option value="month" ${period==='month'?'selected':''}>自然月</option></select></label><label>周期内日期<input id="report-date" type="date" value="${esc(date)}"></label>${button('查看报告','load',!owner||!date,'id="report-load"')}</div>${!data&&!loading&&owner?'<p class="insight-note">选择查询条件后，点击查询按钮显示结果。</p>':''}${loading?button('停止分析','stop')+'<p role="status">正在汇总本地记录…</p>':''}${error?`<div class="notice error" role="alert">${esc(error)}${data?' · 保留上次报告和原周期。':''}</div>`:''}${!owner?'<p>连接车辆账号并取得当前车辆绑定后，可查看报告。</p>':''}
        ${data?`<div class="report-period-head"><div><h3 id="report-title">${esc(w.start_date)} — ${esc(w.end_date)}</h3><p class="insight-note">北京时间 · ${data.period==='week'?'周一至周日':'自然月'} · ${statusText[c.status]} · 统计截至 ${esc(time(data.as_of))}<br>${esc(periodName()[0])} ${esc(data.previous.window.start_date)} — ${esc(data.previous.window.end_date)}</p></div><div class="insight-actions">${button('上一周期','previous')}${button('下一周期','next')}</div></div>`:''}</section>
        ${data?`<p class="report-direction-guide"><span class="negative">左减</span><span class="positive">右增</span><span>0 为中心，统一环比刻度；${esc(periodName().join(' → '))}。</span></p><div class="report-compact-top">${comparisonPanel(coreMetrics,data.period==='week'?'比上周，哪些变了':'比上期，哪些变了','report-graph-summary')}${comparisonPanel(energyMetrics,'耗电、充电与实付','report-energy-comparison')}</div><div class="report-compact-mid">${dailyChart()}${departureChart()}</div>${coverageChart()}
        <section class="card insight-panel"><div class="insight-heading"><h3>本期结束事件${dayFilter?' · '+esc(dayFilter):''}</h3><div class="insight-toolbar"><label>事件类型<select id="report-kind" aria-label="事件类型">${[['all','全部事件'],['trip_end','行程'],['charge_end','充电']].map(([k,v])=>`<option value="${k}" ${kind===k?'selected':''}>${v}</option>`).join('')}</select></label><label>事件完整性<select id="report-quality" aria-label="事件完整性">${[['all','全部记录'],['complete','完整记录'],['partial','片段记录']].map(([k,v])=>`<option value="${k}" ${quality===k?'selected':''}>${v}</option>`).join('')}</select></label></div></div><div id="report-events"></div></section><p class="insight-note report-reading-note">变化只反映已记录数据；覆盖差异不等于真实用车增减。电量为 SOC 变化估算；实付按账单日期统计，不等于行驶成本。</p>`:''}`;
      if(data){const extra=document.createElement('section');extra.className='card insight-panel';extra.id='report-automatic';node.querySelector('#report-coverage')?.after(extra);automatic?.mount(extra);}
      paintEvents();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintEvents(){
      const el=node?.querySelector('#report-events');if(!el||!data)return;
      const rows=events(),pages=Math.max(1,Math.ceil(rows.length/12));page=Math.min(page,pages-1);
      const maxima=rows.reduce((m,row)=>{
        const values=eventGraphic(row,{trip:1,charge:1,energy:1}),key=row.kind==='trip_end'?'trip':'charge';
        m[key]=Math.max(m[key],values.value||0);m.energy=Math.max(m.energy,values.energy||0);return m;
      },{trip:1,charge:1,energy:1});
      const displayed=rows.slice(page*12,page*12+12),selected=displayed.find(row=>row.id===selectedEvent);
      if(!selected)selectedEvent='';
      const group=(kind,title)=>{
        const found=displayed.filter(row=>row.kind===kind);if(!found.length)return '';
        return `<div class="report-record-group"><h4>${title}</h4><div class="report-record-scroll"><div class="report-record-bars" style="--record-count:${found.length}">${found.map(row=>{const g=eventGraphic(row,maxima);return `<button data-report="event" data-report-event="${esc(row.id)}" data-id="${esc(row.id)}" aria-pressed="${row.id===selectedEvent}" aria-label="${esc((row.kind==='trip_end'?'行程':'充电')+' '+time(row.start_time)+' 至 '+time(row.end_time)+'，'+num(g.value)+' '+g.unit+'，'+(row.partial?'片段记录':'完整记录'))}"><span>${num(g.value)} ${g.unit}</span><i class="track" aria-hidden="true">${g.ratio===null?'':`<b class="${row.partial?'partial':''} ${g.value===0?'zero':''}" style="height:${Math.min(100,g.ratio*100)}%"></b>`}</i><small>${esc(time(row.end_time)).split(' ')[0]}</small></button>`;}).join('')}</div></div></div>`;
      };
      let detail='';
      if(selected){
        const row=selected,g=eventGraphic(row,maxima),trip=row.kind==='trip_end';
        detail=`<article id="report-selected-event" class="report-event-viz ${row.partial?'partial':''}"><div class="report-event-heading"><div><h4>${trip?'行程':'充电'} · ${row.partial?'片段记录':'完整记录'}</h4><p>${esc(time(row.start_time))} → ${esc(time(row.end_time))}</p></div><details class="report-event-detail"><summary>原始明细</summary><p>事件记录容量 ${num(row.battery_capacity_kwh)} kWh · 观测时长 ${num(row.duration_seconds===null?null:row.duration_seconds/60)} 分钟</p></details></div><div class="report-selected-values"><span>${trip?'已记录里程':'观测时长'} <b>${num(g.value)} ${g.unit}</b></span><div class="report-event-soc"><span>SOC 端点 <b>${num(g.startSoc)}% → ${num(g.endSoc)}%</b></span>${g.startSoc===null?'<p>端点未知</p>':`<svg viewBox="0 0 110 18" role="img" aria-label="SOC 从 ${g.startSoc}% 到 ${g.endSoc}%"><line x1="5" y1="9" x2="105" y2="9" class="report-soc-track"/><line x1="${5+g.startSoc}" y1="9" x2="${5+g.endSoc}" y2="9" class="report-soc-range"/><circle cx="${5+g.startSoc}" cy="9" r="3" class="report-soc-start"/><circle cx="${5+g.endSoc}" cy="9" r="3" class="report-soc-end"/></svg>`}</div><span>${trip?'耗电估算':'充入估算'} <b>${num(g.energy)} kWh</b></span></div></article>`;
      }
      el.innerHTML=`<p class="insight-note">匹配 ${rows.length} 条 · 同类里程／充电时长共享刻度。点击柱形查看 SOC 端点和明细；SOC 连线不代表中间过程。</p><div class="report-record-groups">${group('trip_end','行程 · km')}${group('charge_end','充电 · 观测分钟')}${displayed.length?'':'<p class="insight-empty">没有符合筛选的结束事件。没有记录不表示车辆未使用。</p>'}</div>${detail}<div class="insight-pagination">${button('上一页事件','events-previous',page===0)}<span>${page+1} / ${pages}</span>${button('下一页事件','events-next',page+1===pages)}</div>`;
    }
    let analysisController=null;
    function invalidate(){analysisController?.abort();serial++;placesSerial++;places=null;placesError='';placesLoading=false;data=null;attempted=loading=false;error=dayFilter=selectedEvent='';page=0;paint();}
    async function load(preserveSelection=false){
      if(!owner||!date||loading)return;analysisController=new AbortController();
      const token=++serial,identity=owner;
      attempted=true;loading=true;error='';paint();
      try{
        const result=await request(`/api/insights/report?period=${period}&date=${encodeURIComponent(date)}`,undefined,50000,{signal:analysisController.signal,active});
        if(!valid(token,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=result;placesSerial++;places=null;placesError='';placesLoading=false;if(!preserveSelection){dayFilter=selectedEvent='';page=0;}
      }catch(failure){if(valid(token,identity))error=failure.message;}
      finally{if(valid(token,identity)){loading=false;paint();}}
    }
    let tripRevision,chargeRevision,personalDataRevision;
    function mount(container){
      const changed=owner!==context(),recordsChanged=personalDataRevision!==JSON.stringify(getState()?.personal_records_revision)||tripRevision!==getState()?.trip_records_revision||chargeRevision!==getState()?.charge_records_revision,remount=node!==container;node=container;
      personalDataRevision=JSON.stringify(getState()?.personal_records_revision);
      tripRevision=getState()?.trip_records_revision;chargeRevision=getState()?.charge_records_revision;
      if(changed){analysisController?.abort();owner=context();data=null;error='';loading=false;attempted=false;serial++;placesSerial++;places=null;placesError='';placesLoading=false;dayFilter=selectedEvent='';page=0;}
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
        page=0;selectedEvent='';paintEvents();return true;
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
        case 'event':selectedEvent=target.dataset.id;paintEvents();break;
        case 'events-previous':page--;selectedEvent='';paintEvents();break;
        case 'events-next':page++;selectedEvent='';paintEvents();break;
      }
      return true;
    }
    return {mount,handle};
  }
  root.UsageReportPage={create,analyze,compareValues,pairedDays,departureBins,eventGraphic,changeExtent,deltaGeometry,dailyDeltas,differenceDomain};
})(window);
