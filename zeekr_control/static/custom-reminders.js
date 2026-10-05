(function(root){
  'use strict';
  const kinds={low_soc:'电量低于阈值',high_soc:'电量达到阈值',parked_charging:'停车充电持续中',parked_windows:'停车后车窗未关（待核验）'};
  const reasons={unknown_time:'车辆时间未知',future:'车辆时间超前',stale:'缓存已陈旧',unknown_value:'条件数值或状态未知',unverified:'枚举尚未核验',matching:'本条符合条件',not_matching:'本条不符合条件',repeat:'重复缓存，未增加确认次数',revision:'同时间修订，重新确认'};
  const deliveries={local:'已记入站内历史',pending:'待发送',sending:'发送中',sent:'已发送',failed:'发送失败',uncertain:'发送结果未确认',cancelled:'已取消发送'};
  const blank=()=>({id:'',name:'',kind:'low_soc',threshold:25,confirm_seconds:120,cooldown_minutes:60,enabled:false,delivery:'in_app',recovery:true});
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',data=null,draft=blank(),attempted=false,loading=false,busy=false,dirty=false;
    let serial=0,writeSerial=0,lastLoaded=0,error='',status='',preview=null,rulePage=0,historyPage=0,historyFilter='all';
    let tyreData=null,tyreDraft=null,tyreBusy=false,tyreSerial=0,tyreError='',tyreStatus='';
    const context=()=>getState()?.insights_context||'';
    const valid=(token,current,identity)=>token===current&&identity===owner&&identity===context();
    const button=(label,action,disabled=false,extra='')=>`<button class="button secondary" data-rule="${action}" ${disabled||busy?'disabled':''} ${extra}>${label}</button>`;
    const field=(label,name,type='number',extra='')=>`<label>${label}<input id="rule-${name}" name="${name}" aria-label="${label}" type="${type}" value="${esc(draft[name])}" ${extra}></label>`;
    const check=(label,name)=>`<label class="rule-check"><input id="rule-${name}" name="${name}" type="checkbox" ${draft[name]?'checked':''}>${label}</label>`;
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(!node?.isConnected||!active())return;
      const focused=node.contains(document.activeElement)?document.activeElement:null;
      const focus=focused?{id:focused.id,start:focused.selectionStart,end:focused.selectionEnd}:null;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">自定义提醒</span><h2>条件确认，再提醒</h2><p>用后台已有观测判断，旧缓存不重复凑次数。</p></div><span class="insight-source">连续确认 · 可启停</span></section>
        <section class="card insight-panel"><div class="insight-toolbar">${button('读取规则与历史','load',!owner||loading)}${button('撤销规则操作','undo',!data?.can_undo)}<span>${loading?'正在读取…':lastLoaded?'读取于 '+esc(time(lastLoaded)):''}</span></div>${status?`<p class="insight-note" role="status">${esc(status)}</p>`:''}${error?`<p class="notice error" role="alert">${esc(error)}</p>`:''}${!owner?'<p>连接车辆账号并取得当前车辆绑定后，可管理提醒。</p>':''}<p class="insight-note">连续确认同时要求车辆时间和采集时间推进，至少两条新观测。条件持续时只提醒一次；确认恢复后，满足冷却时间才可再次触发。未知、修订和数据缺口会重新确认。</p></section>
        ${data?`<section class="card insight-panel"><div class="insight-heading"><h3>${draft.id?'编辑提醒':'新建提醒'}</h3>${button('新建规则','new')}</div><form id="rule-form" novalidate><fieldset class="rule-form ledger-form" ${busy?'disabled':''}>
          ${field('提醒名称','name','text','required maxlength="80"')}
          <label>提醒条件<select name="kind" id="rule-kind" aria-label="提醒条件">${Object.entries(kinds).map(([key,label])=>`<option value="${key}" ${draft.kind===key?'selected':''}>${label}</option>`).join('')}</select></label>
          ${field('电量阈值（%）','threshold','number','required min="1" max="99" step="1"')}
          ${field('连续确认（秒）','confirm_seconds','number','required min="60" max="86400" step="1"')}
          ${field('冷却时间（分钟）','cooldown_minutes','number','required min="1" max="43200" step="1"')}
          <label>提醒方式<select name="delivery" id="rule-delivery" aria-label="提醒方式"><option value="in_app" ${draft.delivery==='in_app'?'selected':''}>仅站内历史</option><option value="wecom" ${draft.delivery==='wecom'?'selected':''}>Bark＋站内历史（企业微信兜底）</option></select></label>
          ${check('启用这条规则','enabled')}${check('恢复时也发送通知','recovery')}</fieldset></form>
          <p class="insight-note">阈值仅用于电量条件。停车充电要求下电、有效零速及已核验充电状态。车窗仅核验关闭组合，打开枚举尚未核验；可保存停用规则，暂不能启用。</p><p class="insight-note">选择 Bark 并启用后，由采集后台优先推送到 Bark；失败时尝试企业微信。页面预览不发消息；发送结果不明时不会自动重发。只在当前账号与车辆下运行，采集暂停时不判断。</p>
          <div class="insight-actions">${button('预览条件','preview',loading)}${button('保存规则','save',loading)}</div>
          ${preview?`<div id="rule-preview-result" class="rule-preview"><strong>${preview.matches===true?'本条观测符合条件':preview.matches===false?'本条观测不符合条件':'暂不能判断'}</strong><p>${esc(reasons[preview.reason]||'未知')} · 车辆时间 ${esc(time(preview.state_time))}</p><p>预览不会触发提醒，不计入连续确认，不发送通知。</p></div>`:''}</section>
          <section class="card insight-panel"><h3>我的规则</h3><p class="insight-note">下方是最近一次评估，不保证当前车况。编辑、启停或恢复规则后重新确认；停用会阻止未发通知。</p><div id="rule-records"></div></section>
          <section class="card insight-panel"><div class="insight-heading"><h3>提醒历史</h3><label>历史类型<select id="rule-history-filter" aria-label="历史类型"><option value="all" ${historyFilter==='all'?'selected':''}>全部</option><option value="raised" ${historyFilter==='raised'?'selected':''}>条件成立</option><option value="recovered" ${historyFilter==='recovered'?'selected':''}>条件恢复</option></select></label></div><p class="insight-note">展示最近 100 条；本机保留最近 10000 条。点击“读取规则与历史”更新。站内历史不会推送系统通知。</p><div id="rule-history"></div></section>`:''}`;
      node.children[1].insertAdjacentHTML('afterend',tyrePanel());
      paintRecords();paintHistory();
      if(focus){const el=document.getElementById(focus.id);el?.focus({preventScroll:true});if(el&&focus.start!==null&&focus.start!==undefined)el.setSelectionRange(focus.start,focus.end);}
    }
    function tyrePanel(){
      const base=tyreDraft?.load==='full'?290:260;
      const control=(label,action,disabled=false)=>`<button class="button secondary" data-tyre="${action}" ${disabled||tyreBusy?'disabled':''}>${label}</button>`;
      return `<section class="card insight-panel" id="tyre-settings"><div class="insight-heading"><h3>胎压异常提醒</h3>${control('读取胎压设置','load',!owner)}</div><p class="insight-note">255/55 R19 · 车门标牌：轻载 260 kPa，满载 290 kPa。载荷由你手动选择。</p>
        ${tyreBusy?'<p role="status">正在处理胎压设置…</p>':''}${tyreError?`<p class="notice error" role="alert">${esc(tyreError)}</p>`:''}${tyreStatus?`<p role="status">${esc(tyreStatus)}</p>`:''}
        ${tyreData?`<fieldset class="rule-form ledger-form" ${tyreBusy?'disabled':''}><label>载荷参考<select id="tyre-load" aria-label="载荷参考"><option value="light" ${tyreDraft.load==='light'?'selected':''}>轻载 · 260 kPa</option><option value="full" ${tyreDraft.load==='full'?'selected':''}>满载 · 290 kPa</option></select></label><label class="rule-check"><input id="tyre-enabled" type="checkbox" ${tyreDraft.enabled?'checked':''}>启用胎压异常提醒</label></fieldset><p id="tyre-thresholds">偏低 ≤ ${base*.9} kPa · 明显偏低 ≤ ${base*.8} kPa · 恢复 ≥ ${base*.95} kPa</p><p class="insight-note">偏低和恢复：至少 3 条新观测，持续 120 秒。明显偏低：至少 2 条新观测。重复缓存、未知值不凑次数；数据缺口重新确认。同一异常只报一次，升级才再报。</p><p class="insight-note">Bark 发简短提醒，企业微信发详情；两路独立发送。发送结果不明时不自动重发。采集暂停时不判断。软件参考提醒，非厂家报警标准。</p><div class="insight-actions">${control('保存胎压设置','save')}</div><h4>胎压提醒历史</h4><p class="insight-note">最近 30 条，点击“读取胎压设置”更新。设置变化后重新确认。</p>${tyreData.history.map(row=>`<article class="rule-record"><p>${esc(time(row.created))}</p><p>${row.events.map(e=>esc(e.wheel)+' '+esc(e.pressure)+' kPa · '+({0:'恢复',1:'偏低',2:'明显偏低'}[e.level]||'未知')).join('<br>')}</p><p>Bark：${esc(deliveries[row.bark]||'未知')} · 企业微信：${esc(deliveries[row.wecom]||'未知')}</p></article>`).join('')||'<p class="insight-empty">还没有胎压提醒历史</p>'}`:'<p>读取后，可查看当前设置、切换载荷参考。</p>'}</section>`;
    }
    async function tyreAction(action){
      if(!owner||tyreBusy||action==='save'&&!tyreData)return;
      const identity=owner,token=++tyreSerial;
      const payload=action==='save'?{action:'save',...tyreDraft,revision:tyreData.config.revision,context:identity}:undefined;
      tyreBusy=true;tyreError='';tyreStatus='';paint();
      try{
        const result=await request('/api/insights/tyres',payload);
        if(!valid(token,tyreSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        tyreData=result;tyreDraft={enabled:result.config.enabled,load:result.config.load};
        if(action==='save')tyreStatus='胎压设置已保存。后台从新观测重新确认。';
      }catch(failure){if(valid(token,tyreSerial,identity))tyreError=failure.message+' 请重新读取核对后操作。';}
      finally{if(valid(token,tyreSerial,identity)){tyreBusy=false;paint();}}
    }
    function paintRecords(){
      const target=node?.querySelector('#rule-records');if(!data||!target)return;
      const pages=Math.max(1,Math.ceil(data.records.length/10));rulePage=Math.max(0,Math.min(rulePage,pages-1));
      target.innerHTML=(data.records.slice(rulePage*10,rulePage*10+10).map(row=>{
        const r=row.body,s=data.states[row.id],expired=s&&Date.now()-s.last_observed>180000;
        return `<article class="rule-record" data-rule-record="${esc(row.id)}"><div class="insight-heading"><h4>${esc(r.name)}</h4><span class="insight-badge">${row.deleted?'已删除':r.enabled?'已启用':'已停用'}</span></div><p>${kinds[r.kind]}${['low_soc','high_soc'].includes(r.kind)?' '+r.threshold+'%':''} · 连续 ${r.confirm_seconds} 秒 · 冷却 ${r.cooldown_minutes} 分钟</p><p>${r.delivery==='wecom'?'Bark＋站内历史（企业微信兜底）':'仅站内历史'} · ${r.recovery?'恢复时通知':'恢复只记历史'}</p>${s&&!row.deleted?`<p>最近评估：${expired?'观测已陈旧，等待新数据':esc(reasons[s.reason]||'等待评估')}；${s.active?'上次已确认条件成立':'尚未确认条件成立或已恢复'}。连续有效观测 ${s.count||0} 条。<br>车辆时间 ${esc(time(s.last_time))} · 评估时间 ${esc(time(s.last_observed))}</p>`:'<p>等待后台新观测评估。</p>'}<div class="insight-actions">${row.deleted?button('恢复规则','restore',false,`data-id="${esc(row.id)}"`):button('编辑规则','edit',false,`data-id="${esc(row.id)}"`)+button(r.enabled?'停用规则':'启用规则','toggle',false,`data-id="${esc(row.id)}"`)+button('删除规则','delete',false,`data-id="${esc(row.id)}"`)}</div></article>`;
      }).join('')||'<p class="insight-empty">还没有自定义规则</p>')+`<div class="insight-pagination">${button('上一页规则','rules-previous',rulePage===0)}<span>${rulePage+1} / ${pages}</span>${button('下一页规则','rules-next',rulePage+1===pages)}</div>`;
    }
    function paintHistory(){
      const target=node?.querySelector('#rule-history');if(!data||!target)return;
      const rows=data.history.filter(row=>historyFilter==='all'||row.kind===historyFilter),pages=Math.max(1,Math.ceil(rows.length/15));historyPage=Math.max(0,Math.min(historyPage,pages-1));
      target.innerHTML=(rows.slice(historyPage*15,historyPage*15+15).map(row=>`<article class="rule-record" data-rule-history="${row.id}"><div class="insight-heading"><h4>${esc(row.name)} · ${row.kind==='raised'?'条件成立':'条件恢复'}</h4><span class="insight-badge">${deliveries[row.delivery]||'未知'}</span></div><p>车辆时间 ${esc(time(row.state_time))}<br>记录时间 ${esc(time(row.created))}</p>${row.error?`<p>${esc(row.error)}</p>`:''}</article>`).join('')||'<p class="insight-empty">还没有符合筛选的提醒历史</p>')+`<div class="insight-pagination">${button('上一页提醒','history-previous',historyPage===0)}<span>${historyPage+1} / ${pages}</span>${button('下一页提醒','history-next',historyPage+1===pages)}</div>`;
    }
    async function load(){
      if(!owner)return false;
      const identity=owner,token=++serial;attempted=true;loading=true;error='';paint();
      try{const result=await request('/api/insights/rules');if(!valid(token,serial,identity))return false;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');data=result;lastLoaded=Date.now();return true;
      }catch(failure){if(valid(token,serial,identity))error=failure.message;return false;}
      finally{if(valid(token,serial,identity)){loading=false;paint();}}
    }
    async function mutate(action,id){
      if(busy||loading||!data)return;
      if(['save','preview'].includes(action)&&!node.querySelector('#rule-form').reportValidity())return;
      const identity=owner,token=++writeSerial;
      let payload={...draft,action,id:draft.id,revision:data.revision,context:owner};
      if(action==='toggle'){const row=data.records.find(r=>r.id===id);payload={...payload,...row.body,id,enabled:!row.body.enabled,action:'save'};}
      else if(!['save','preview'].includes(action))payload={action,id,revision:data.revision,context:owner};
      busy=true;error='';status='';paint();
      try{
        const result=await request('/api/insights/rules'+(action==='preview'?'/preview':''),payload);
        if(!valid(token,writeSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        if(action==='preview'){preview=result;return;}
        data.revision=result.revision;data.can_undo=result.can_undo;status='规则操作已保存。';
        if(action==='save'||action==='delete'&&draft.id===id){draft=blank();dirty=false;preview=null;}
        if(!await load()&&valid(token,writeSerial,identity))status+=' 列表尚未刷新，请重新读取核对。';
      }catch(failure){if(valid(token,writeSerial,identity))error=failure.message+' 填写内容保留；请重新读取核对后操作。';}
      finally{if(valid(token,writeSerial,identity)){busy=false;paint();}}
    }
    function mount(container){
      const changed=owner!==context(),remount=node!==container;node=container;
      if(changed){owner=context();data=null;draft=blank();attempted=false;loading=false;busy=false;dirty=false;serial++;writeSerial++;error='';status='';preview=null;lastLoaded=0;rulePage=historyPage=0;}
      if(changed){tyreData=tyreDraft=null;tyreBusy=false;tyreSerial++;tyreError=tyreStatus='';}
      if(changed||remount)paint();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;
      const el=event.target;
      if(event.type==='change'&&tyreDraft&&(el.id==='tyre-load'||el.id==='tyre-enabled')){
        if(el.id==='tyre-load')tyreDraft.load=el.value;else tyreDraft.enabled=el.checked;
        tyreStatus='';paint();return true;
      }
      const tyreTarget=event.type==='click'?el.closest('[data-tyre]'):null;
      if(tyreTarget&&!tyreTarget.disabled){tyreAction(tyreTarget.dataset.tyre);return true;}
      if(event.type==='change'&&el.id==='rule-history-filter'){historyFilter=el.value;historyPage=0;paintHistory();return true;}
      if((event.type==='input'||event.type==='change')&&Object.hasOwn(draft,el.name)){
        draft[el.name]=el.type==='checkbox'?el.checked:el.type==='number'?Number(el.value):el.value;dirty=true;preview=null;node.querySelector('#rule-preview-result')?.remove();return true;
      }
      if(event.type!=='click')return false;
      const target=el.closest('[data-rule]');if(!target||target.disabled)return false;
      const action=target.dataset.rule,id=target.dataset.id;
      if(action==='load')load();
      else if(action==='new'){draft=blank();dirty=false;preview=null;error='';paint();}
      else if(action==='edit'){const row=data.records.find(r=>r.id===id);draft={...row.body,id};dirty=false;preview=null;paint();node.querySelector('#rule-form').scrollIntoView({block:'start'});}
      else if(action==='rules-previous'){rulePage--;paintRecords();}
      else if(action==='rules-next'){rulePage++;paintRecords();}
      else if(action==='history-previous'){historyPage--;paintHistory();}
      else if(action==='history-next'){historyPage++;paintHistory();}
      else mutate(action,id);
      return true;
    }
    return {mount,handle};
  }
  root.CustomRemindersPage={create};
})(window);
