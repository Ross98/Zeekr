(function(root){
  'use strict';
  function summarize(charges,life){
    const bills=charges.entries,expenses=life.expenses.entries;
    const actual=bills.filter(row=>Number.isFinite(row.actual_cents));
    const charge=actual.reduce((sum,row)=>sum+row.actual_cents,0);
    const parking=bills.reduce((sum,row)=>sum+(row.parking_fee_cents||0),0);
    const daily=expenses.reduce((sum,row)=>sum+row.amount_cents,0);
    const duplicates=expenses.filter(row=>/停车/.test(row.category)&&bills.some(b=>b.date===row.date&&b.parking_fee_cents>0&&b.parking_fee_cents===row.amount_cents));
    return {charge:actual.length?charge:null,parking:bills.length?parking:null,daily:expenses.length?daily:null,
      total:actual.length||expenses.length||parking?charge+parking+daily:null,duplicates,
      unknown:bills.filter(row=>row.actual_cents===null).length,unlinked:charges.events.filter(row=>!row.recorded).length};
  }
  function create({getState,request,escape:esc,active,navigate}){
    let node,owner='',month=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'}).format(new Date()).slice(0,7),data=null,loading=false,error='',serial=0;
    const context=()=>getState()?.insights_context||'';
    const money=v=>Number.isFinite(v)?(v/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})+' 元':'暂无已录金额';
    function paint(){
      if(!node?.isConnected||!active())return;
      root.RefreshView.preserve(node,()=>{
        node.innerHTML=`<section class="card insight-panel"><h2>费用总览</h2>${root.booksCanReturn?.()?'<button class="button secondary" data-books-return>返回来源页面</button>':''}<div class="insight-toolbar"><label>账本月份<input id="books-month" type="month" value="${esc(month)}"></label><button class="button secondary" data-costs="load" ${loading?'disabled':''}>读取费用总览</button></div><p class="insight-note">按账单日期合计已录实际金额，估算另列；未记账不代表没有支出。</p>${loading?'<p role="status">正在读取费用…</p>':''}${error?`<p class="notice error" role="alert">${esc(error)}</p>`:''}</section>${data?`<section class="card insight-panel" id="books-totals"><div class="insight-metrics">${[['已录实际总额',data.total],['充电费用',data.charge],['充电停车费',data.parking],['日常支出',data.daily]].map(([label,value])=>`<div><span>${label}</span><strong>${money(value)}</strong></div>`).join('')}</div><p class="insight-note">总额为已填充电金额＋充电停车费＋日常支出，不代表全部用车成本。${data.unknown} 笔账单尚未填写实际充电金额。</p></section><section class="card insight-panel"><h3>待补与核对</h3><div class="insight-actions"><button class="button secondary" data-costs="ledger">充电未关联 ${data.unlinked} 次</button><button class="button secondary" data-costs="unknown">实际金额待补 ${data.unknown} 笔</button><button class="button secondary" data-costs="life">查看日常支出</button></div>${data.duplicates.length?`<p class="notice info books-duplicate">可能重复录入停车费 ${data.duplicates.length} 笔。同日同金额仅为核对线索，不自动删除或扣减。</p><ul>${data.duplicates.map(r=>`<li>${esc(r.date)} · ${esc(r.title)} · ${money(r.amount_cents)}</li>`).join('')}</ul>`:'<p class="insight-note">同笔充电停车费请勿再录到日常支出。</p>'}</section>`:''}`;
      });
    }
    async function load(){
      if(!owner||!month||loading)return;
      const identity=owner,selected=month,token=++serial;loading=true;error='';paint();
      const [year,m]=month.split('-').map(Number),end=month+'-'+new Date(Date.UTC(year,m,0)).getUTCDate();
      try{
        const [charges,life]=await Promise.all([request('/api/insights/ledger?date='+month+'-01'),request('/api/insights/life?start='+month+'-01&end='+end)]);
        if(token!==serial||identity!==context()||selected!==month)return;
        if(charges.context!==identity||life.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=summarize(charges,life);
      }catch(e){if(token===serial&&identity===context())error=e.message;}
      finally{if(token===serial){loading=false;paint();}}
    }
    function mount(container){const changed=owner!==context(),remount=node!==container;node=container;if(changed){owner=context();serial++;loading=false;data=null;error='';month=root.BookSession.read(owner,'costs')?.month||month;}if(changed||remount){paint();load();}}
    function handle(event){if(!active()||!node?.contains(event.target))return false;const el=event.target;if(event.type==='input'&&el.id==='books-month'){month=el.value;serial++;loading=false;data=null;root.BookSession.write(owner,'costs',{month});paint();return true;}if(event.type!=='click')return false;const button=el.closest('[data-costs]');if(!button||button.disabled)return false;if(button.dataset.costs==='load')load();else navigate(button.dataset.costs==='life'?'life':'ledger',month+'-01',button.dataset.costs==='unknown'?'unknown':'all');return true;}
    return {mount,handle};
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={summarize};else root.BooksOverview={create};
})(typeof window==='undefined'?globalThis:window);
