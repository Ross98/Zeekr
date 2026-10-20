(function(root){
  'use strict';
  const validMonth=value=>/^\d{4}-(0[1-9]|1[0-2])$/.test(value);
  const sources={home:'家充',public:'公共充电',unknown:'来源未知'};
  function summarize(response){
    const t=response.totals;
    return {charge:t.charge_cents,parking:t.charge_parking_cents,daily:t.life_cents,total:t.actual_cents,
      unknown:t.unknown_charge_count,unlinked:t.unlinked_charge_count,duplicates:response.duplicates||[],charts:response.charts||{categories:[],months:[]}};
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
  function create({getState,request,escape:esc,active,navigate,getView=()=> 'costs'}){
    const todayMonth=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'}).format(new Date()).slice(0,7);
    let node=null,owner='',month=todayMonth;
    let data=null,records=null,loading=false,recordsLoading=false,error='',recordsError='',serial=0,recordSerial=0,page=0;
    let summaryAttempted=false,recordsAttempted=false,summaryPending=null,recordsPending=null,category='',expanded=false;
    const context=()=>getState()?.insights_context||'';
    const money=v=>Number.isFinite(v)?(v/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})+' 元':'金额待补';
    const preserve=(container,fn)=>root.RefreshView?root.RefreshView.preserve(container,fn):fn();
    function reset(){serial++;recordSerial++;data=null;records=null;loading=false;recordsLoading=false;error='';recordsError='';summaryAttempted=false;recordsAttempted=false;summaryPending=null;recordsPending=null;page=0;category='';expanded=false;}
    function sync(){
      const identity=context();
      const fallback=identity===owner?month:todayMonth;
      const selected=root.BookSession?.month(identity,fallback)||fallback;
      if(identity!==owner||validMonth(selected)&&selected!==month){owner=identity;if(validMonth(selected))month=selected;reset();}
    }
    function paint(){
      if(!node?.isConnected||!active())return;
      if(getView()==='costs')root.updateBooksPeriod?.({id:'books-month',month,busy:false});
      preserve(node,()=>{
        const metrics=getView()==='costs'?`<div class="books-visual-total"><span>${esc(month)} 已录花费</span><strong>${data?(Number.isFinite(data.total)?money(data.total):'暂无已录金额'):'—'}</strong></div>`:`<div class="insight-metrics">${[['已录实际总额',data?.total],['充电费用',data?.charge],['充电停车费',data?.parking],['日常支出',data?.daily]].map(([label,value])=>`<div><span>${label}</span><strong>${data?(Number.isFinite(value)?money(value):'暂无已录金额'):'—'}</strong></div>`).join('')}</div>`;
        node.innerHTML=`<section class="card insight-panel books-summary" id="books-totals" aria-busy="${loading}">${metrics}<p class="insight-note">仅合计已录实际金额；估算不计入。${data?`${data.unknown} 笔充电金额待补。`:''}</p>${loading&&!data?'<p role="status">正在读取费用…</p>':''}${error?`<p class="notice error" role="alert">${esc(error)}</p>`:''}${data?`<div class="insight-actions books-review-actions"><button class="button secondary" data-costs="ledger">充电未关联 ${data.unlinked} 次</button><button class="button secondary" data-costs="unknown">实际金额待补 ${data.unknown} 笔</button><button class="button secondary" data-costs="life">查看日常支出</button>${data.duplicates.length?`<button class="button secondary" data-costs="duplicates">停车费重复线索 ${data.duplicates.length} 笔</button>`:''}</div>${data.duplicates.length?`<details class="books-duplicate"><summary>可能重复录入停车费 ${data.duplicates.length} 笔</summary><p class="insight-note">同日同金额仅为核对线索，不自动删除或扣减。</p><ul>${data.duplicates.map(r=>`<li>${esc(r.date)} · ${esc(r.title)} · ${money(r.amount_cents)}</li>`).join('')}</ul></details>`:''}`:''}</section>`;
      });
      root.syncBooksWriteControls?.();
      paintRecords();
    }
    function paintRecords(){
      if(getView()!=='costs'||!active())return;
      const workspace=root.document?.getElementById('costs-workspace');if(!workspace)return;
      const filtered=(records||[]).filter(row=>matchesCategory(row,category));
      const pages=Math.max(1,Math.ceil(filtered.length/10));page=Math.min(page,pages-1);
      preserve(workspace,()=>{
        const groups=data?.charts.categories||[],months=data?.charts.months||[];
        const names=[...new Set(months.flatMap(row=>row.categories.map(c=>c.category)).concat(groups.map(c=>c.category)))].sort();
        const tone=name=>names.includes(name)?names.indexOf(name)%6:4;
        const maxCategory=Math.max(1,...groups.map(c=>c.amount_cents)),maxMonth=Math.max(1,...months.map(m=>m.actual_cents||0));
        const largest=data?.charts.largest;
        const share=largest&&data?.total>0?(recordedAmount(largest)/data.total*100).toFixed(1)+'%':null;
        const rowHtml=row=>`<article class="books-timeline-row" data-books-record="${esc(row.kind+':'+row.id)}"><time datetime="${esc(row.date)}">${esc(row.date.slice(5).replace('-',' / '))}</time><i class="books-timeline-dot books-tone-${tone(row.category)}" aria-hidden="true"></i><div><strong>${esc(row.title)}</strong><span>${esc(row.category)} · ${esc(row.source)}${row.parking_cents>0?' · 含充电停车费 '+money(row.parking_cents):''}${row.actual_cents==null&&row.parking_cents>0?' · 充电金额待补':''}</span></div><strong class="books-timeline-amount">${row.actual_cents==null&&row.parking_cents>0?'已知 ':''}${money(recordedAmount(row))}</strong></article>`;
        const count=expanded?10:4;
        workspace.innerHTML=`<div class="books-chart-top"><section class="card insight-panel" data-books-panel="categories"><h2>钱花在哪里</h2>${groups.length?groups.map(g=>`<div class="books-category-row"><button class="books-category-button" data-costs="category" data-cost-category="${esc(g.category)}" aria-label="筛选分类 ${esc(g.category)}" aria-pressed="${category===g.category}">${esc(g.category)}</button><div class="books-category-track"><div class="books-category-fill books-tone-${tone(g.category)}" style="width:${g.amount_cents/maxCategory*100}%"></div></div><div class="books-category-money">${money(g.amount_cents)}<span>${data.total>0?(g.amount_cents/data.total*100).toFixed(1)+'%':'占比不适用'}</span></div></div>`).join(''):'<p class="insight-note">暂无已录分类金额。</p>'}</section><section class="card insight-panel books-largest" data-books-panel="largest"><h2>本月最大单笔</h2>${largest?`<div class="books-largest-main"><span>${esc(largest.date)} · ${esc(largest.category)}</span><strong>${money(recordedAmount(largest))}</strong><p>${esc(largest.title)}</p><span>${share?'占已录花费 '+share:'已录免费支出'}${largest.actual_cents==null?' · 仅已知部分':''}</span></div><div class="books-largest-footer">其余已录金额 ${money(Math.max(0,(data?.total||0)-recordedAmount(largest)))}</div>`:`<p class="insight-note">${recordsLoading?'正在读取记录…':recordsError?'记录读取失败，暂无法确定。':'暂无已录实际金额。'}</p>`}</section></div><section class="card insight-panel books-trend" data-books-panel="trend"><h2>近半年花费</h2><div class="books-trend-bars" role="img" aria-label="${esc(months.map(m=>m.month+' '+(m.actual_cents==null?'暂无已录金额':money(m.actual_cents))).join('；'))}">${months.map(m=>`<div class="books-trend-month" data-cost-month="${esc(m.month)}"><span class="books-trend-value">${m.actual_cents==null?'未录':money(m.actual_cents)}</span><div class="books-trend-stack" style="height:${m.actual_cents==null?0:Math.max(2,m.actual_cents/maxMonth*155)}px">${m.categories.map(g=>`<span class="books-tone-${tone(g.category)}" style="height:${m.actual_cents?g.amount_cents/m.actual_cents*100:0}%" title="${esc(g.category)} ${money(g.amount_cents)}"></span>`).join('')}</div><time>${esc(m.month.slice(5))}月</time></div>`).join('')}</div><div class="books-chart-legend">${names.map(name=>`<span><i class="books-tone-${tone(name)}"></i>${esc(name)}</span>`).join('')}</div><p class="insight-note">单位：元 · 仅已录金额；当前月截至读取时，其他月份为整月。未录不代表没有支出。</p></section><section class="card insight-panel books-timeline" data-books-panel="timeline"><div class="insight-heading"><h2>本月支出足迹</h2><button class="button secondary" data-costs="load" ${loading||recordsLoading||!owner?'disabled':''}>读取费用总览</button></div><div class="books-timeline-heading"><span>${esc(month)} · ${filtered.length} 笔${category?' · '+esc(category):''} · 新记录在前</span>${category?'<button class="button secondary" data-costs="all">全部分类</button>':''}</div>${recordsLoading&&!records?'<p role="status">正在读取费用记录…</p>':''}${recordsError?`<p class="notice error" role="alert">${esc(recordsError)}</p>`:''}${records?filtered.length?filtered.slice(page*10,page*10+count).map(rowHtml).join(''):'<p class="insight-empty">本月暂无已录费用；不代表没有支出。</p>':''}${filtered.length>4?`<div class="insight-pagination"><button class="button secondary" data-costs="expand">${expanded?'收起支出足迹':'展开更多支出'}</button>${expanded&&pages>1?`<button class="button secondary" data-costs="previous" ${page===0?'disabled':''}>上一页费用</button><span>${page+1} / ${pages}</span><button class="button secondary" data-costs="next" ${page+1===pages?'disabled':''}>下一页费用</button>`:''}</div>`:''}</section>`;
      });
    }
    function loadSummary(){
      if(!owner)return Promise.resolve();if(loading)return summaryPending||Promise.resolve();
      const identity=owner,selected=month,token=++serial;loading=true;summaryAttempted=true;error='';paint();
      summaryPending=(async()=>{try{
        const result=await request('/api/insights/costs?date='+selected+'-01');
        if(token!==serial||identity!==context()||selected!==month)return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=summarize(result);
      }catch(e){if(token===serial&&identity===context()&&selected===month){data=null;error=e.message;}}
      finally{if(token===serial){loading=false;summaryPending=null;paint();}}})();return summaryPending;
    }
    function loadRecords(){
      if(!owner||getView()!=='costs')return Promise.resolve();if(recordsLoading)return recordsPending||Promise.resolve();
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
    function refresh(){sync();const previousData=data,previousRecords=records;reset();data=previousData;records=previousRecords;paint();return Promise.all([loadSummary(),loadRecords()]);}
    function mount(container){const remount=node&&node!==container;node=container;sync();if(remount)return refresh();paint();if(!summaryAttempted)loadSummary();if(getView()==='costs'&&!recordsAttempted)loadRecords();}
    function selectMonth(value){if(!validMonth(value))return false;month=value;root.BookSession?.setMonth(owner,month);reset();paint();return true;}
    function handle(event){
      if(!active())return false;const el=event.target;
      if(event.type==='input'&&el.id==='books-month'&&getView()==='costs'){const changed=selectMonth(el.value);if(changed){loadSummary();loadRecords();}return changed;}
      if(event.type!=='click')return false;const button=el.closest('[data-costs]');if(!button||button.disabled)return false;
      const action=button.dataset.costs;
      if(action==='load')refresh();
      else if(action==='category'){category=button.dataset.costCategory;page=0;paintRecords();}
      else if(action==='all'){category='';page=0;paintRecords();}
      else if(action==='expand'){expanded=!expanded;page=0;paintRecords();}
      else if(action==='previous'||action==='next'){page+=action==='previous'?-1:1;paintRecords();}
      else navigate(action==='life'||action==='duplicates'?'life':'ledger',month+'-01',action==='unknown'?'unknown':'all');
      return true;
    }
    return {mount,handle,refresh,openDate:date=>{if(selectMonth(date.slice(0,7)))return Promise.all([loadSummary(),loadRecords()]);}};
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={summarize,mergeRecords,recordedAmount,matchesCategory,create};else root.BooksOverview={create};
})(typeof window==='undefined'?globalThis:window);
