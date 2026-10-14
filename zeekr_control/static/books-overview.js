(function(root){
  'use strict';
  const validMonth=value=>/^\d{4}-(0[1-9]|1[0-2])$/.test(value);
  const sources={home:'家充',public:'公共充电',unknown:'来源未知'};
  function summarize(response){
    const t=response.totals;
    return {charge:t.charge_cents,parking:t.charge_parking_cents,daily:t.life_cents,total:t.actual_cents,
      unknown:t.unknown_charge_count,unlinked:t.unlinked_charge_count,duplicates:response.duplicates||[]};
  }
  function mergeRecords(ledger,life){
    const cents=value=>Number.isFinite(value)&&value>=0?value:null;
    return [...(ledger?.entries||[]).map(row=>({id:row.id,date:row.date,title:row.note||'充电账单',category:'充电',
      source:sources[row.source]||'来源未知',actual_cents:cents(row.actual_cents),parking_cents:cents(row.parking_fee_cents),kind:'charge',updated_at:row.updated_at||0})),
    ...(life?.expenses?.entries||[]).map(row=>({id:row.id,date:row.date,title:row.title,category:row.category,source:'生活账本',
      actual_cents:cents(row.amount_cents),parking_cents:null,kind:'life',updated_at:row.updated_at||0}))]
      .sort((a,b)=>b.date.localeCompare(a.date)||b.updated_at-a.updated_at||String(b.id).localeCompare(String(a.id)));
  }
  function create({getState,request,escape:esc,active,navigate,getView=()=> 'costs'}){
    const todayMonth=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'}).format(new Date()).slice(0,7);
    let node=null,owner='',month=todayMonth;
    let data=null,records=null,loading=false,recordsLoading=false,error='',recordsError='',serial=0,recordSerial=0,page=0;
    let summaryAttempted=false,recordsAttempted=false,summaryPending=null,recordsPending=null;
    const context=()=>getState()?.insights_context||'';
    const money=v=>Number.isFinite(v)?(v/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})+' 元':'金额待补';
    const preserve=(container,fn)=>root.RefreshView?root.RefreshView.preserve(container,fn):fn();
    function reset(){serial++;recordSerial++;data=null;records=null;loading=false;recordsLoading=false;error='';recordsError='';summaryAttempted=false;recordsAttempted=false;summaryPending=null;recordsPending=null;page=0;}
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
        node.innerHTML=`<section class="card insight-panel books-summary" id="books-totals" aria-busy="${loading}"><div class="insight-metrics">${[['已录实际总额',data?.total],['充电费用',data?.charge],['充电停车费',data?.parking],['日常支出',data?.daily]].map(([label,value])=>`<div><span>${label}</span><strong>${data?(Number.isFinite(value)?money(value):'暂无已录金额'):'—'}</strong></div>`).join('')}</div><p class="insight-note">仅合计已录实际金额；估算不计入。${data?`${data.unknown} 笔充电金额待补。`:''}</p>${loading&&!data?'<p role="status">正在读取费用…</p>':''}${error?`<p class="notice error" role="alert">${esc(error)}</p>`:''}${data?`<div class="insight-actions books-review-actions"><button class="button secondary" data-costs="ledger">充电未关联 ${data.unlinked} 次</button><button class="button secondary" data-costs="unknown">实际金额待补 ${data.unknown} 笔</button><button class="button secondary" data-costs="life">查看日常支出</button>${data.duplicates.length?`<button class="button secondary" data-costs="duplicates">停车费重复线索 ${data.duplicates.length} 笔</button>`:''}</div>${data.duplicates.length?`<details class="books-duplicate"><summary>可能重复录入停车费 ${data.duplicates.length} 笔</summary><p class="insight-note">同日同金额仅为核对线索，不自动删除或扣减。</p><ul>${data.duplicates.map(r=>`<li>${esc(r.date)} · ${esc(r.title)} · ${money(r.amount_cents)}</li>`).join('')}</ul></details>`:''}`:''}</section>`;
      });
      root.syncBooksWriteControls?.();
      paintRecords();
    }
    function paintRecords(){
      if(getView()!=='costs'||!active())return;
      const workspace=root.document?.getElementById('costs-workspace');if(!workspace)return;
      const pages=Math.max(1,Math.ceil((records?.length||0)/10));page=Math.min(page,pages-1);
      preserve(workspace,()=>{
        workspace.innerHTML=`<section class="card insight-panel"><div class="insight-heading"><h2>本月费用记录</h2><button class="button secondary" data-costs="load" ${loading||recordsLoading||!owner?'disabled':''}>读取费用总览</button></div><p class="insight-note">${esc(month)} · 充电与生活账本合并查看，充电停车费单独列出。</p>${recordsLoading&&!records?'<p role="status">正在读取费用记录…</p>':''}${recordsError?`<p class="notice error" role="alert">${esc(recordsError)}</p>`:''}${records?records.length?`<div class="books-records-wrap"><table class="books-records"><thead><tr><th scope="col">记录</th><th scope="col">日期</th><th scope="col">分类／来源</th><th scope="col">实际金额</th><th scope="col">充电停车费</th></tr></thead><tbody>${records.slice(page*10,page*10+10).map(row=>`<tr data-books-record="${esc(row.kind+':'+row.id)}"><th scope="row">${esc(row.title)}</th><td>${esc(row.date)}</td><td>${esc(row.category)} · ${esc(row.source)}</td><td>${money(row.actual_cents)}</td><td>${row.kind==='charge'?money(row.parking_cents):'—'}</td></tr>`).join('')}</tbody></table></div>${pages>1?`<div class="insight-pagination"><button class="button secondary" data-costs="previous" ${page===0?'disabled':''}>上一页费用</button><span>${page+1} / ${pages}</span><button class="button secondary" data-costs="next" ${page+1===pages?'disabled':''}>下一页费用</button></div>`:''}`:'<p class="insight-empty">本月暂无已录费用；不代表没有支出。</p>':''}</section>`;
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
      else if(action==='previous'||action==='next'){page+=action==='previous'?-1:1;paintRecords();}
      else navigate(action==='life'||action==='duplicates'?'life':'ledger',month+'-01',action==='unknown'?'unknown':'all');
      return true;
    }
    return {mount,handle,refresh,openDate:date=>{if(selectMonth(date.slice(0,7)))return Promise.all([loadSummary(),loadRecords()]);}};
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={summarize,mergeRecords,create};else root.BooksOverview={create};
})(typeof window==='undefined'?globalThis:window);
