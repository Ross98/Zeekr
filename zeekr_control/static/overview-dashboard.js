(function(root){
  'use strict';
  const DAY=86400000;
  const numberFormat=new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2});
  const dateFormat=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'});
  const number=v=>Number.isFinite(v)?numberFormat.format(v):'未知';
  function summarize(report,ledger,today,span,recent={}){
    const allDays=[...(report?.previous?.days||[]),...(report?.current?.days||[])];
    const lookup=new Map(allDays.map(d=>[d.date,d]));
    const end=Date.parse(today+'T12:00:00+08:00');
    const days=Array.from({length:span},(_,i)=>{
      const date=new Date(end-(span-1-i)*DAY).toISOString().slice(0,10);
      return {date,distance_km:null,...lookup.get(date)};
    });
    const actual=ledger?.totals?.actual_cents;
    const pending=ledger?ledger.totals.unlinked_charge_count+ledger.totals.unknown_charge_count:null;
    const latest=['trip_end','charge_end'].flatMap(kind=>recent?.[kind]?.id?[{...recent[kind],kind}]:[]);
    const events=[...new Map([...latest,...(report?.current?.events||[]),...(report?.previous?.events||[])].map(event=>[event.id,event])).values()].sort((a,b)=>b.end_time-a.end_time);
    const todayData={...(lookup.get(today)||{distance_km:null,trip_count:null,partial_trip_count:null})};
    const open=report?.open_trip;
    const dayOf=stamp=>Number.isFinite(stamp)?dateFormat.format(new Date(stamp)):'';
    if(open&&dayOf(open.start_time)===today&&dayOf(open.end_time)===today){
      todayData.open_trip=open;
      todayData.open_distance_km=Number.isFinite(open.distance_km)?open.distance_km:null;
      if(todayData.open_distance_km!==null)todayData.distance_km=(todayData.distance_km??0)+todayData.open_distance_km;
    }
    return {today:todayData,days,actual:Number.isFinite(actual)?actual:null,pending,events};
  }
  function selectRecords(events,filter){
    if(filter!=='all')return events.filter(event=>event.kind===filter).slice(0,3);
    const selected=new Map();
    for(const kind of ['trip_end','charge_end']){const latest=events.find(event=>event.kind===kind);if(latest)selected.set(latest.id,latest);}
    for(const event of events){if(selected.size>=3)break;selected.set(event.id,event);}
    return [...selected.values()].sort((a,b)=>b.end_time-a.end_time);
  }
  function create({getState,request,escape:esc,active,openRecord,openTool,attention,time}){
    let owner='',key='',serial=0,report=null,ledger=null,errors=[],loading=false,loadedAt=0,left=false;
    const span=7;
    let filter='all',returnPoint=null;
    let pending=null,summaryCache=null,heights=new Map();
    const markup=new WeakMap();
    const date=()=>dateFormat.format(new Date());
    const scope=()=>getState()?.insights_context||'';
    const identity=()=>[scope(),date(),getState()?.trip_records_revision||0,getState()?.charge_records_revision||0].join('|');
    const valid=(token,context,stamp)=>serial===token&&scope()===context&&identity()===stamp;
    const node=id=>document.getElementById(id);
    function summary(){
      const today=date(),recent=getState()?.recent_events;
      if(!summaryCache||summaryCache.report!==report||summaryCache.ledger!==ledger||summaryCache.today!==today||summaryCache.span!==span||summaryCache.recent!==recent){
        summaryCache={report,ledger,today,span,recent,value:summarize(report,ledger,today,span,recent)};
      }
      return summaryCache.value;
    }
    function text(id,value){const target=node(id);if(target.textContent!==value)target.textContent=value;}
    function html(id,value){const target=node(id);if(markup.get(target)!==value){target.innerHTML=value;markup.set(target,value);}}
    function paint(){
      const container=document.getElementById('main');
      return root.RefreshView?root.RefreshView.preserve(container,paintContent):paintContent();
    }
    function paintContent(){
      if(!active()||!node('overview-records'))return;
      const stable=['overview-records','overview-today-note','overview-cost-note'];
      for(const id of stable)node(id).style.minHeight=!report&&heights.get(id)?heights.get(id)+'px':'';
      const data=summary(),today=data.today;
      text('overview-today-value',number(today.distance_km));
      const openNote=today.open_trip?` · ${today.open_trip.status==='waiting'?'待收尾':'记录中'} ${number(today.open_distance_km)} km · 观测至 ${new Date(today.open_trip.end_time).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false})}`:'';
      text('overview-today-note',today.trip_count===null?'尚无有效观测':`${today.trip_count} 次${today.open_trip?'已结束':'行程'}${today.partial_trip_count?' · 含 '+today.partial_trip_count+' 条片段':''}${openNote}`);
      text('overview-cost-value',data.actual===null?'未知':number(data.actual/100));
      text('overview-cost-note',data.pending===null?'账本尚未读取':`含充电、充电停车费与日常支出 · ${data.pending} 项充电待补`);
      const rows=selectRecords(data.events,filter);
      const loadLabel=loading?'正在读取已保存记录…':!owner?'连接当前车辆后可读取记录。':errors.length?errors.join('；'):'';
      html('overview-records',(loadLabel?`<p class="subtle" role="status">${esc(loadLabel)}</p>`:'')+(rows.map(e=>`<button class="overview-record-row" data-overview-record="${esc(e.id)}"><span><strong>${e.kind==='trip_end'?'行程':'充电'} · ${esc(time(e.end_time))}</strong><small>${e.partial?'片段记录':'未标记为片段'} · SOC ${number(e.start_soc)}% → ${number(e.end_soc)}%</small></span><span>${e.kind==='trip_end'?number(e.distance_km)+' km':'观测 '+number(Number.isFinite(e.duration_seconds)?e.duration_seconds/60:null)+' 分钟'}<small>查看详情 →</small></span></button>`).join('')||(!loading?'<p class="subtle">暂无符合筛选的结束记录。没有记录不表示没有用车。</p>':'')));
      if(report&&!loading)for(const id of stable)heights.set(id,node(id).getBoundingClientRect().height);
      node('overview-record-filter').value=filter;
      const items=attention();
      html('overview-tasks',`<div class="overview-task"><h3>车况与采集</h3><p class="subtle">${items.length?'需要留意 '+items.length+' 项':'暂无待处理提示；缓存不代表实时状态。'}</p><button class="button secondary" data-overview-tool="quality">查看采集与数据质量</button></div><div class="overview-task"><h3>费用待补${data.pending===null?'':` · ${data.pending} 项`}</h3><p class="subtle">未关联充电与已录账单的未知实际金额均需核对。</p><button class="button secondary" data-overview-tool="ledger">去补账</button></div><div class="overview-task"><h3>地点确认</h3><p class="subtle">按行程参考地点核对名称与分组范围。</p><button class="button secondary" data-overview-tool="places">查看地点与名称</button></div>`);

    }
    async function load(){
      const context=scope(),stamp=identity();if(!context){paint();return;}
      if(pending?.context===context&&pending.stamp===stamp)return pending.promise;
      const token=++serial;loading=true;errors=[];paint();
      const queryDate=date();
      const job={context,stamp,promise:Promise.allSettled([request('/api/insights/report?period=month&date='+queryDate),request('/api/insights/costs?date='+queryDate)])};
      pending=job;
      const results=await job.promise;
      if(pending===job)pending=null;
      if(!valid(token,context,stamp))return;
      results.forEach((result,i)=>{
        if(result.status==='fulfilled'&&result.value.context===context){if(i===0)report=result.value;else ledger=result.value;}
        else{if(i===0)report=null;else ledger=null;errors.push(i===0?'行程汇总读取失败，请重试':'费用汇总读取失败，请重试');}
      });
      loadedAt=Date.now();loading=false;paint();
    }
    function mount(){
      const context=scope(),stamp=identity();
      if(stamp!==key){if(owner!==context)heights.clear();serial++;key=stamp;owner=context;report=ledger=null;pending=summaryCache=null;errors=[];loading=false;loadedAt=0;}
      paint();
      if(!loading&&(left||Date.now()-loadedAt>30000)){left=false;load();}
    }
    function suspend(){left=true;}
    function remember(){returnPoint={scroll:scrollY,context:scope()};}
    function restore(){if(!returnPoint)return false;const point=returnPoint;returnPoint=null;if(point.context===scope())scrollTo(0,point.scroll);return true;}
    function backButton(){return returnPoint?.context===scope()?'<button class="button secondary overview-back" data-overview-back>← 返回总览原位置</button>':'';}
    function handle(event){
      if(event.type==='change'&&event.target.id==='overview-record-filter'){filter=event.target.value;paint();return true;}
      const button=event.type==='click'&&event.target.closest('[data-overview-record],[data-overview-tool],[data-overview-reload]');
      if(!button||!active())return false;
      if(button.hasAttribute('data-overview-reload'))load();
      else if(button.dataset.overviewTool){remember();openTool(button.dataset.overviewTool,date());}
      else{const record=summary().events.find(e=>e.id===button.dataset.overviewRecord);if(record){remember();openRecord(record);}}
      return true;
    }
    return {mount,suspend,handle,backButton,restore};
  }
  const exports={summarize,selectRecords,create};
  if(typeof module!=='undefined')module.exports=exports;else root.OverviewDashboard=exports;
})(typeof window==='undefined'?globalThis:window);
