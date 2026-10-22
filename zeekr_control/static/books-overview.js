(function(root){
  'use strict';
  const validMonth=value=>/^\d{4}-(0[1-9]|1[0-2])$/.test(value);
  const sources={home:'家充',public:'公共充电',unknown:'来源未知'};
  function summarize(response){
    const t=response.totals;
    return {charge:t.charge_cents,parking:t.charge_parking_cents,daily:t.life_cents,total:t.actual_cents,
      unknown:t.unknown_charge_count,unlinked:t.unlinked_charge_count,duplicates:response.duplicates||[],asOf:response.as_of,window:response.window,recordPage:response.records,charts:response.charts||{categories:[],months:[]}};
  }
  function mergeRecords(ledger,life){
    const cents=value=>Number.isFinite(value)&&value>=0?value:null;
    return [...(ledger?.entries||[]).map(row=>({id:row.id,date:row.date,title:row.note||'充电账单',category:'充电',
      source:sources[row.source]||'来源未知',actual_cents:cents(row.actual_cents),parking_cents:cents(row.parking_fee_cents),kind:'charge',updated_at:row.updated_at||0})),
    ...(life?.expenses?.entries||[]).map(row=>({id:row.id,date:row.date,title:row.title,category:row.category,source:'生活账本',
      actual_cents:cents(row.amount_cents),parking_cents:null,kind:'life',updated_at:row.updated_at||0}))]
      .sort((a,b)=>b.date.localeCompare(a.date)||b.updated_at-a.updated_at||String(b.id).localeCompare(String(a.id)));
  }
  function recordedAmount(row){
    return row.actual_cents==null&&!(row.parking_cents>0)?null:(row.actual_cents||0)+(row.parking_cents||0);
  }
  function matchesCategory(row,category){
    return !category||row.category===category||(row.kind==='charge'&&category==='充电停车费'&&row.parking_cents>0);
  }
  function categoryAmount(row,category){
    if(row.kind==='charge'&&category==='充电')return row.actual_cents;
    if(row.kind==='charge'&&category==='充电停车费')return row.parking_cents;
    return recordedAmount(row);
  }
  function pieSegments(groups){
    const positive=groups.filter(g=>Number.isFinite(g.amount_cents)&&g.amount_cents>0);
    const total=positive.reduce((sum,g)=>sum+g.amount_cents,0);let angle=0;
    return positive.map((group,i)=>{const start=angle,ratio=group.amount_cents/total;
      angle=i===positive.length-1?Math.PI*2:angle+ratio*Math.PI*2;
      return {...group,ratio,start,end:angle};});
  }
  function formatShare(amount,total){
    if(!(total>0)||!Number.isFinite(amount))return '占比不适用';
    const share=amount/total*100;
    return share>0&&share<.1?'<0.1%':share.toFixed(1)+'%';
  }
  function pieChart(groups,category,tone,money,esc){
    const segments=pieSegments(groups);
    if(!segments.length)return '<p class="books-pie-empty">暂无可绘制的已录金额</p>';
    const total=segments.reduce((sum,g)=>sum+g.amount_cents,0);
    const selected=groups.find(g=>g.category===category);
    const amount=money(selected?selected.amount_cents:total).replace(' 元','');
    const circumference=2*Math.PI*84;
    const label=category||'已录总额';
    const labelParts=label.length>10?[label.slice(0,12),label.slice(12)]:[label];
    return `<svg class="books-pie" viewBox="0 0 220 220" aria-label="已录支出分类环图"><circle class="books-pie-track" cx="110" cy="110" r="84"/>${segments.map(g=>{
      const length=g.ratio*circumference,gap=g.ratio===1?0:Math.min(2.5,length*.18);
      const shape=`<circle cx="110" cy="110" r="84" transform="rotate(-90 110 110)" stroke-dasharray="${length-gap} ${circumference-length+gap}" stroke-dashoffset="${-g.start*84-gap/2}"/>`;
      return `<a href="#costs-workspace" data-costs="category" data-cost-category="${esc(g.category)}" class="books-pie-slice books-tone-${tone(g.category)}" aria-label="饼图分类 ${esc(g.category)} ${money(g.amount_cents)}" aria-current="${category===g.category?'true':'false'}"><title>${esc(g.category)} · ${money(g.amount_cents)} · ${esc(formatShare(g.amount_cents,total))}</title>${shape}</a>`;
    }).join('')}<g class="books-pie-center" text-anchor="middle"><text class="books-pie-label" x="110" y="${labelParts.length>1?80:93}">${labelParts.map((part,i)=>`<tspan x="110" dy="${i?14:0}">${esc(part)}</tspan>`).join('')}</text><text class="books-pie-total" x="110" y="123" style="font-size:${amount.length>10?18:24}px">${esc(amount)}</text><text class="books-pie-unit" x="110" y="147">元${selected&&total>0?' · '+esc(formatShare(selected.amount_cents,total)):''}</text></g></svg>`;
  }

  function chartPoints(rows,asOf,annual=false){
    const current=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'}).format(new Date(Number.isFinite(asOf)?asOf:Date.now()));
    const boundary=annual?current.slice(0,4):current;
    return rows.map(row=>{const key=annual?row.year:row.month;return {...row,key,
      value:key>boundary?null:row.actual_cents??0,inferred:row.actual_cents==null&&key<=boundary,
      partial:key===boundary,future:key>boundary};});
  }
  function lineChart(rows,width,annual,asOf,esc){
    const points=chartPoints(rows,asOf,annual),money=v=>(v/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})+' 元';
    if(!points.length)return '<p class="insight-note">暂无已录金额。</p>';
    const height=250,left=64,right=36,top=35,bottom=48,max=Math.max(1,...points.map(p=>(p.value||0)/100));
    const unit=10**Math.floor(Math.log10(max)),ceiling=Math.ceil(max/unit)*unit;
    const x=i=>points.length===1?(left+width-right)/2:left+i*(width-left-right)/(points.length-1),y=v=>height-bottom-v/100/ceiling*(height-top-bottom);
    let paths='';
    for(let i=1;i<points.length;i++)if(points[i-1].value!==null&&points[i].value!==null)paths+=`<path class="books-line-path${points[i].partial?' books-line-partial':''}" d="M${x(i-1)},${y(points[i-1].value)}L${x(i)},${y(points[i].value)}"/>`;
    const ticks=[0,ceiling/2,ceiling];
    return `<svg class="books-line-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(points.map(p=>p.key+' '+(p.future?'未来期间':money(p.value)+(p.inferred?'，无已录金额按零显示':''))+(p.partial?'，截至目前':'')).join('；'))}"><text x="${left}" y="15">金额 / 元</text>${ticks.map(t=>`<line class="books-line-grid" x1="${left}" x2="${width-right}" y1="${y(t*100)}" y2="${y(t*100)}"/><text x="${left-10}" y="${y(t*100)+4}" text-anchor="end">${t.toLocaleString('zh-CN')}</text>`).join('')}${paths}${points.map((p,i)=>`${p.value!==null?`<g data-cost-point="${esc(p.key)}" data-display-cents="${p.value}" data-partial="${p.partial}"><title>${esc(p.key+' '+money(p.value)+(p.inferred?'（无已录金额）':'')+(p.partial?'，截至目前':''))}</title><circle class="books-line-hit" fill="transparent" cx="${x(i)}" cy="${y(p.value)}" r="14"/><circle class="books-line-point${p.partial?' books-line-point-open':''}" cx="${x(i)}" cy="${y(p.value)}" r="4"/><text class="books-line-value" x="${x(i)+(p.partial&&!annual?9:0)}" y="${y(p.value)-13}" text-anchor="${i===0?'start':i===points.length-1?'end':p.partial&&!annual?'start':'middle'}">${Math.round(p.value/100).toLocaleString('zh-CN')}</text></g>`:''}<text x="${x(i)}" y="${height-20}" text-anchor="middle">${esc(annual?p.key:p.key.slice(5)+'月')}</text>`).join('')}<text x="${width-right}" y="${height-3}" text-anchor="end">${annual?'年份':'月份'}</text></svg>`;
  }
  function create({getState,request,escape:esc,active,navigate,getView=()=> 'costs'}){
    const todayMonth=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'}).format(new Date()).slice(0,7);
    let node=null,owner='',month=todayMonth,scope='month',chartYear='',recordPage=null;
    const allHistory=()=>getView()==='costs'&&scope==='all';
    let data=null,records=null,loading=false,recordsLoading=false,error='',recordsError='',serial=0,recordSerial=0,page=0;
    let summaryAttempted=false,recordsAttempted=false,summaryPending=null,recordsPending=null,category='';
    const context=()=>getState()?.insights_context||'';
    const money=v=>Number.isFinite(v)?(v/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})+' 元':'金额待补';
    const preserve=(container,fn)=>root.RefreshView?root.RefreshView.preserve(container,fn):fn();
    function reset(){serial++;recordSerial++;data=null;records=null;loading=false;recordsLoading=false;error='';recordsError='';summaryAttempted=false;recordsAttempted=false;summaryPending=null;recordsPending=null;page=0;category='';recordPage=null;}
    function sync(){
      if(getView()!=='costs'&&scope==='all'){scope='month';chartYear='';reset();}
      const identity=context();
      const fallback=identity===owner?month:todayMonth;
      const selected=root.BookSession?.month(identity,fallback)||fallback;
      if(identity!==owner||validMonth(selected)&&selected!==month){owner=identity;scope='month';chartYear='';if(validMonth(selected))month=selected;reset();}
    }
    function paint(){
      if(!node?.isConnected||!active())return;
      if(getView()==='costs')root.updateBooksPeriod?.({id:'books-month',month,busy:false});
      preserve(node,()=>{
        const metrics=getView()==='costs'?`<div class="books-scope-switch" aria-label="费用统计范围"><button class="button secondary" data-costs="scope-month" aria-pressed="${!allHistory()}">本月</button><button class="button secondary" data-costs="scope-all" aria-pressed="${allHistory()}">全部历史</button></div><div class="books-visual-total"><span>${allHistory()?'全部历史累计花费':esc(month)+' 已录花费'}</span><strong>${data?(Number.isFinite(data.total)?money(data.total):'暂无已录金额'):'—'}</strong></div>`:`<div class="insight-metrics">${[['已录实际总额',data?.total],['充电费用',data?.charge],['充电停车费',data?.parking],['日常支出',data?.daily]].map(([label,value])=>`<div><span>${label}</span><strong>${data?(Number.isFinite(value)?money(value):'暂无已录金额'):'—'}</strong></div>`).join('')}</div>`;
        node.innerHTML=`<section class="card insight-panel books-summary" id="books-totals" aria-busy="${loading}">${metrics}<p class="insight-note">仅合计已录实际金额；估算不计入。${data?`${data.unknown} 笔充电金额待补。`:''}${allHistory()&&data?.window?.start_date?' 账目日期 '+esc(data.window.start_date)+' 至 '+esc(data.window.end_date)+'。':''}</p>${loading&&!data?'<p role="status">正在读取费用…</p>':''}${error?`<p class="notice error" role="alert">${esc(error)}</p>`:''}${data?`<div class="insight-actions books-review-actions"><button class="button secondary" data-costs="ledger">${allHistory()?'按月核对未关联充电':'充电未关联 '+data.unlinked+' 次'}</button><button class="button secondary" data-costs="unknown">${allHistory()?'按月补充充电金额':'实际金额待补 '+data.unknown+' 笔'}</button><button class="button secondary" data-costs="life">${allHistory()?'按月管理日常支出':'查看日常支出'}</button>${data.duplicates.length?`<button class="button secondary" data-costs="duplicates">停车费重复线索 ${data.duplicates.length} 笔</button>`:''}</div>${data.duplicates.length?`<details class="books-duplicate"><summary>可能重复录入停车费 ${data.duplicates.length} 笔</summary><p class="insight-note">同日同金额仅为核对线索，不自动删除或扣减。</p><ul>${data.duplicates.map(r=>`<li>${esc(r.date)} · ${esc(r.title)} · ${money(r.amount_cents)}</li>`).join('')}</ul></details>`:''}`:''}</section>`;
      });
      root.syncBooksWriteControls?.();
      paintRecords();
    }
    function paintRecords(){
      if(getView()!=='costs'||!active())return;
      const workspace=root.document?.getElementById('costs-workspace');if(!workspace)return;
      const filtered=(records||[]).filter(row=>matchesCategory(row,category));
      const total=allHistory()?(recordPage?.total||0):filtered.length;
      const pages=allHistory()?(recordPage?.pages||1):Math.max(1,Math.ceil(total/10));if(!allHistory()||recordPage)page=Math.min(page,pages-1);
      preserve(workspace,()=>{
        const groups=data?.charts.categories||[],months=data?.charts.months||[];
        const names=[...new Set(groups.map(c=>c.category).concat(months.flatMap(row=>row.categories.map(c=>c.category))))];
        const tone=name=>names.includes(name)?names.indexOf(name)%8:4;
        const selectedGroup=groups.find(g=>g.category===category);
        const detailAmount=category?selectedGroup?.amount_cents:data?.total;
        const busy=loading||recordsLoading;
        const rowHtml=row=>{
          const partial=!category&&row.actual_cents==null&&row.parking_cents>0;
          const parking=row.parking_cents>0?(category==='充电'?' · 另录停车费 ':category==='充电停车费'?' · 对应充电金额 ':' · 含充电停车费 '):'';
          const related=category==='充电停车费'?row.actual_cents:row.parking_cents;
          return `<article class="books-timeline-row" data-books-record="${esc(row.kind+':'+row.id)}"><time datetime="${esc(row.date)}">${esc(row.date)}</time><div><strong>${esc(row.title)}</strong><span>${category?'':esc(row.category)+' · '}${esc(row.source)}${parking?parking+money(related):''}${partial?' · 充电金额待补':''}</span></div><strong class="books-timeline-amount">${partial?'已知 ':''}${money(categoryAmount(row,category))}</strong></article>`;
        };
        const categories=`<section class="card insight-panel" data-books-panel="categories"><h2>钱花在哪里</h2><p class="insight-note">点击扇区或分类，查看右侧明细。</p>${pieChart(groups,category,tone,money,esc)}<div class="books-category-legend">${groups.map(g=>`<button class="books-category-button" data-costs="category" data-cost-category="${esc(g.category)}" aria-label="筛选分类 ${esc(g.category)}" aria-pressed="${category===g.category}"><i class="books-category-swatch books-tone-${tone(g.category)}" aria-hidden="true"></i><span>${esc(g.category)}</span><span class="books-category-money">${money(g.amount_cents)}<small>${esc(formatShare(g.amount_cents,data.total))}</small></span></button>`).join('')}</div></section>`;
        const details=`<section class="card insight-panel books-details" data-books-panel="details" aria-busy="${busy}"><div class="insight-heading"><h2>${category?esc(category)+'明细':'支出明细'}</h2>${category?'<button class="button secondary" data-costs="all">全部分类</button>':''}</div><div class="books-details-summary"><span>${allHistory()?'全部历史':esc(month)} · ${records?total+' 笔':'正在读取'} · 新记录在前</span><strong>已录 ${money(detailAmount)}</strong></div><div class="books-detail-list" aria-live="polite">${busy&&!records?'<p role="status">正在读取支出明细…</p>':''}${recordsError||(!busy&&!records&&error)?`<p class="notice error" role="alert">${esc(recordsError||error)}</p>`:''}${records?(filtered.length?filtered.slice(allHistory()?0:page*10,(allHistory()?0:page*10)+10).map(rowHtml).join(''):`<p class="insight-empty">${category?'该分类':allHistory()?'当前范围':'本月'}暂无费用记录；不代表没有支出。</p>`):''}</div><div class="books-details-footer"><button class="button secondary" data-costs="load" ${busy||!owner?'disabled':''}>读取费用总览</button>${pages>1?`<div class="insight-pagination"><button class="button secondary" data-costs="previous" ${busy||page===0?'disabled':''}>上一页费用</button><span>${page+1} / ${pages}</span><button class="button secondary" data-costs="next" ${busy||page+1===pages?'disabled':''}>下一页费用</button></div>`:''}</div></section>`;
        workspace.innerHTML=`<div class="books-chart-top">${categories}${details}</div><section class="card insight-panel books-trend" data-books-panel="trend"><div class="insight-heading"><h2>${allHistory()?'月度花费':'近半年花费'}</h2>${allHistory()?`<label class="books-year-control">花费年份<select data-books-year aria-label="花费年份">${(data?.charts.years?.length?data.charts.years:[chartYear||month.slice(0,4)]).map(year=>`<option value="${esc(year)}" ${year===(data?.charts.year||chartYear)?'selected':''}>${esc(year)} 年</option>`).join('')}</select></label>`:''}</div><div class="books-line-chart" data-books-line="months"></div><div class="books-line-data">${months.map(m=>`<span data-cost-month="${esc(m.month)}">${esc(m.month)}</span>`).join('')}</div><p class="insight-note">按已录账目统计，无账目月份按 0 显示；未来月份留空。悬停查看精确金额，空心点及虚线表示未结束期间。</p></section>${allHistory()?`<section class="card insight-panel books-annual" data-books-panel="annual"><h2>年度花费</h2><div class="books-line-chart" data-books-line="annual"></div><div class="books-line-data">${(data?.charts.annual||[]).map(row=>`<span data-cost-year="${esc(row.year)}">${esc(row.year)} ${money(row.actual_cents??0)}</span>`).join('')}</div><p class="insight-note">各年已录金额，非累计；本年截至目前，不直接计算全年同比。</p></section>`:''}`;
      });
      paintLineCharts();
      if(chartObserver){chartObserver.disconnect();chartObserver.observe(workspace);}
    }
    function paintLineCharts(){
      if(!active()||getView()!=='costs')return;
      const workspace=root.document?.getElementById('costs-workspace');
      for(const container of workspace?.querySelectorAll?.('[data-books-line]')||[]){
        const width=container.getBoundingClientRect().width;if(width<200)continue;
        const annual=container.dataset.booksLine==='annual';
        container.innerHTML=lineChart((annual?data?.charts.annual:data?.charts.months)||[],width,annual,data?.asOf,esc);
      }
    }
    const chartObserver=root.ResizeObserver?new root.ResizeObserver(paintLineCharts):null;
    function loadSummary(){
      if(!owner)return Promise.resolve();if(loading)return summaryPending||Promise.resolve();
      const identity=owner,selected=month,selectedScope=allHistory()?'all':'month',token=++serial;loading=true;summaryAttempted=true;error='';paint();
      summaryPending=(async()=>{try{
        const result=await request('/api/insights/costs?date='+selected+'-01'+(selectedScope==='all'?'&scope=all&page='+page+'&category='+encodeURIComponent(category)+(chartYear?'&year='+chartYear:''):''));
        if(token!==serial||identity!==context()||selected!==month)return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=summarize(result);
        if(selectedScope==='all'){chartYear=result.charts.year;recordPage=result.records;page=recordPage.page;records=recordPage.rows.map(row=>({...row,source:row.kind==='charge'?(sources[row.source]||'来源未知'):'生活账本'}));}
      }catch(e){if(token===serial&&identity===context()&&selected===month){data=null;if(selectedScope==='all'){records=null;recordPage=null;}error=e.message;}}
      finally{if(token===serial){loading=false;summaryPending=null;paint();}}})();return summaryPending;
    }
    function loadRecords(){
      if(!owner||getView()!=='costs'||allHistory())return Promise.resolve();if(recordsLoading)return recordsPending||Promise.resolve();
      const identity=owner,selected=month,token=++recordSerial;recordsLoading=true;recordsAttempted=true;recordsError='';paintRecords();
      const [year,number]=selected.split('-').map(Number),last=new Date(Date.UTC(year,number,0)).getUTCDate();
      recordsPending=(async()=>{try{
        const [ledger,life]=await Promise.all([request('/api/insights/ledger?date='+selected+'-01'),request('/api/insights/life?start='+selected+'-01&end='+selected+'-'+last)]);
        if(token!==recordSerial||identity!==context()||selected!==month)return;
        if(ledger.context!==identity||life.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        records=mergeRecords(ledger,life);page=0;
      }catch(e){if(token===recordSerial&&identity===context()&&selected===month){records=null;recordsError=e.message;}}
      finally{if(token===recordSerial){recordsLoading=false;recordsPending=null;paintRecords();}}})();return recordsPending;
    }
    function refresh(){sync();const previousData=data,previousRecords=records,previousCategory=category;reset();data=previousData;records=previousRecords;category=previousCategory;paint();return Promise.all([loadSummary(),loadRecords()]);}
    function mount(container){const remount=node&&node!==container;node=container;sync();if(remount)return refresh();paint();if(!summaryAttempted)loadSummary();if(getView()==='costs'&&!recordsAttempted)loadRecords();}
    function selectMonth(value){if(!validMonth(value))return false;scope='month';chartYear='';month=value;root.BookSession?.setMonth(owner,month);reset();paint();return true;}
    function reloadAll(){serial++;loading=false;summaryPending=null;records=null;recordPage=null;return loadSummary();}
    function handle(event){
      if(!active())return false;const el=event.target;
      if(event.type==='change'&&el.matches?.('[data-books-year]')){chartYear=el.value;page=0;reloadAll();return true;}
      if(event.type==='input'&&el.id==='books-month'&&getView()==='costs'){const changed=selectMonth(el.value);if(changed){loadSummary();loadRecords();}return changed;}
      if(event.type!=='click')return false;const button=el.closest('[data-costs]');if(!button||button.disabled)return false;
      const action=button.dataset.costs;
      if(action==='load')refresh();
      else if(action==='scope-all'||action==='scope-month'){scope=action==='scope-all'?'all':'month';chartYear='';reset();paint();loadSummary();loadRecords();}
      else if(action==='category'){event.preventDefault?.();category=button.dataset.costCategory;page=0;if(allHistory())reloadAll();else paintRecords();}
      else if(action==='all'){category='';page=0;if(allHistory())reloadAll();else paintRecords();}
      else if(action==='previous'||action==='next'){page+=action==='previous'?-1:1;if(allHistory())reloadAll();else paintRecords();}
      else navigate(action==='life'||action==='duplicates'?'life':'ledger',month+'-01',action==='unknown'?'unknown':'all');
      return true;
    }
    return {mount,handle,refresh,openDate:date=>{if(selectMonth(date.slice(0,7)))return Promise.all([loadSummary(),loadRecords()]);}};
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={summarize,mergeRecords,recordedAmount,matchesCategory,categoryAmount,pieSegments,formatShare,chartPoints,create};else root.BooksOverview={create};
})(typeof window==='undefined'?globalThis:window);
