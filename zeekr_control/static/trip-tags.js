(function(root){
  'use strict';
  const number=value=>Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'—';
  const monthNow=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'}).format(new Date());
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',month=monthNow(),data=null,selected=null,tags='',note='',attempted=false,loading=false,busy=false;
    let serial=0,writeSerial=0,error='',status='',filter='',completeness='all',groupA='',groupB='',page=0,trashPage=0;
    let routeShown=false,routeBusy=false,routeData=null,routeError='',routeSerial=0,routeMap=null;
    const context=()=>getState()?.insights_context||'';
    const valid=(token,current,identity)=>token===current&&owner===identity&&context()===identity;
    const button=(label,action,disabled=false,extra='')=>`<button class="button secondary" data-tag="${action}" ${disabled||busy?'disabled':''} ${extra}>${label}</button>`;
    const options=value=>(data?.groups||[]).map(g=>`<option value="${esc(g.tag)}" ${g.tag===value?'selected':''}>${esc(g.tag)}</option>`).join('');
    const labelList=()=>[...new Set(tags.split(/[,，\n]/).map(s=>s.trim()).filter(Boolean))];
    function syncQuickLabels(){
      const selected=new Set(labelList());
      node?.querySelectorAll('[data-tag="toggle-label"]').forEach(button=>{
        const used=selected.has(button.dataset.label);
        button.setAttribute('aria-pressed',String(used));
        button.setAttribute('aria-label',`${used?'取消':'选择'}标签 ${button.dataset.label}`);
      });
    }
    const tripDate=value=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
    function closeRoute(){routeSerial++;routeShown=routeBusy=false;routeData=null;routeError='';routeMap?.remove();routeMap=null;}
    function routeView(){
      if(!selected)return '';
      return `<div id="tag-route" class="tag-route"><div class="insight-actions">${routeShown?button('隐藏路线小地图','hide-route'):button('查看路线小地图','show-route')}</div>${routeShown?`${routeBusy?'<p role="status">正在读取本趟路线…</p>':''}${routeError?`<p role="alert" class="notice error">${esc(routeError)}</p>`:''}${routeData?'<div id="tag-route-map" aria-label="本趟采样路线小地图"></div><p class="insight-note">仅连接可信采样点；首末点不一定是真实出发地和目的地。稀疏连线不代表实际道路。</p>':''}`:'<p class="insight-note">位置默认隐藏。点击后才读取本趟采样并加载地图底图。</p>'}</div>`;
    }
    function paint(){
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      routeMap?.remove();routeMap=null;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">行程标签</span><h2>同类行程，放在一起看</h2><p>通勤、接娃、周末出游，让每趟记录有自己的分类。</p></div><span class="insight-source">自定义标签 · 同类比较</span></section>
        <section class="card insight-panel"><div class="insight-toolbar"><label>标签月份<input id="tag-month" type="month" aria-label="标签月份" value="${esc(month)}"></label>${button('读取行程标签','load',!owner||!month||loading)}${button('撤销标签操作','undo',!data?.can_undo)}</div>${loading?'<p role="status">正在读取…</p>':''}${status?`<p role="status" class="insight-note">${esc(status)}</p>`:''}${error?`<p role="alert" class="notice error">${esc(error)}</p>`:''}${data?`<p class="insight-note">${data.window.start_date} — ${data.window.end_date} · 按行程结束日期归期，${data.events.length} 条行程，${data.untagged_count} 条未贴标签。一趟可有多个标签，同组结果不能相加当总量。</p>`:''}${!owner?'<p>连接车辆账号并取得当前车辆绑定后，可管理标签。</p>':''}</section>
        ${selected?`<section class="card insight-panel"><div class="insight-heading"><h3>标注这趟行程</h3>${button('取消标注','cancel')}</div><p>${esc(time(selected.start_time))} → ${esc(time(selected.end_time))}<br>${number(selected.distance_km)} km · ${number(selected.duration_seconds===null?null:selected.duration_seconds/60)} 分钟 · ${selected.partial?'观测片段':'完整记录'}</p>${routeView()}<form id="tag-form" class="ledger-form" novalidate><div class="ledger-wide"><strong>点选已有标签</strong><div class="tag-quick-list">${(data?.suggested_tags||[]).map(tag=>`<button type="button" class="tag-quick" data-tag="toggle-label" data-label="${esc(tag)}" aria-label="${labelList().includes(tag)?'取消':'选择'}标签 ${esc(tag)}" aria-pressed="${labelList().includes(tag)}" ${busy?'disabled':''}>${esc(tag)}</button>`).join('')||'<span class="insight-note">还没有已有标签，可在下方输入新标签。</span>'}</div></div><label class="ledger-wide">行程标签（逗号分隔）<input id="tag-labels" aria-label="行程标签（逗号分隔）" type="text" maxlength="300" value="${esc(tags)}" ${busy?'disabled':''}></label><label class="ledger-wide">行程备注<textarea id="tag-note" aria-label="行程备注" maxlength="1000" rows="3" ${busy?'disabled':''}>${esc(note)}</textarea></label></form><p class="insight-note">可用中文或英文逗号分隔，每趟最多 10 个标签，每个 24 字。留空可清除标签；备注单独保留。</p><div class="insight-actions">${button('保存行程标签','save',loading)}</div></section>`:''}
        ${data?`<section class="card insight-panel"><div class="insight-heading"><h3>同类比较</h3><span class="insight-badge">${data.groups.length} 类标签</span></div>${data.groups.length?`<div class="ledger-form"><label>比较标签 A<select id="tag-group-a" aria-label="比较标签 A">${options(groupA)}</select></label><label>比较标签 B<select id="tag-group-b" aria-label="比较标签 B">${options(groupB)}</select></label></div>`:'<p class="insight-empty">从下方选择行程添加标签，即可比较。</p>'}<div id="tag-comparison"></div><p class="insight-note">完整与片段均按有效观测计入，每项单列样本数；均值表示每条记录的观测值，不代表完整行程均值。SOC 回升不算负耗电。百公里估算使用同一批至少 10 km、SOC 下降至少 3 个百分点且电量可估算的记录，按总估算电量 ÷ 总里程计算。SOC 电量不是电表计量。</p><p class="insight-note">距离、时长、样本量不同都可能影响结果。没有天气、路况或驾驶方式证据，不据此归因或排名。</p></section>
        <section class="card insight-panel"><div class="insight-heading"><h3>本月行程</h3><div class="insight-toolbar"><label>筛选标签<select id="tag-filter" aria-label="筛选标签"><option value="">全部标签与未标注</option>${options(filter)}</select></label><label>标签行程完整性<select id="tag-completeness" aria-label="标签行程完整性">${[['all','全部记录'],['complete','完整记录'],['partial','仅片段']].map(([key,label])=>`<option value="${key}" ${key===completeness?'selected':''}>${label}</option>`).join('')}</select></label></div></div><div id="tag-events"></div></section><div id="tag-trash"></div>`:''}`;
      paintGroups();paintEvents();paintRoute();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function paintGroups(){
      const el=node?.querySelector('#tag-comparison');if(!data||!el)return;
      const metric=(label,value,unit,divisor=1)=>`<div><strong>${label}</strong><span>均值 ${number(value.mean===null?null:value.mean/divisor)} ${unit} · 中位 ${number(value.median===null?null:value.median/divisor)} ${unit}</span><span>范围 ${number(value.minimum===null?null:value.minimum/divisor)}–${number(value.maximum===null?null:value.maximum/divisor)} ${unit} · ${value.samples} 个有效样本</span></div>`;
      el.innerHTML=`<div class="tag-comparison">${[groupA,groupB].map((tag,i)=>{
        const g=data.groups.find(g=>g.tag===tag);if(!g)return '';
        return `<article><h4>${i?'B':'A'} · ${esc(tag)}</h4><p>${g.count} 条记录 · 完整 ${g.complete_count} · 片段 ${g.partial_count}</p>${metric('已观测里程',g.distance_km,'km')}${metric('观测时段',g.duration_seconds,'分钟',60)}${metric('观测 SOC 下降',g.soc_consumed,'百分点')}${metric('SOC 电量估算',g.estimated_kwh,'kWh')}<div><strong>百公里电量估算</strong><span>${number(g.efficiency.value)} kWh/100km</span><span>${g.efficiency.samples} 个有效样本 · 合计 ${number(g.efficiency.distance_km)} km</span></div></article>`;
      }).join('')}</div>`;
    }
    function paintRoute(){
      const el=node?.querySelector('#tag-route-map');if(!el||!routeData)return;
      const points=(routeData.observations||[]).filter(p=>p.trusted===true&&p.plottable===true&&Number.isFinite(p.latitude)&&Number.isFinite(p.longitude));
      if(!points.length){el.textContent='本趟暂无位置采样，无法绘制路线。';return;}
      routeMap=L.map(el,{zoomControl:false,scrollWheelZoom:false});
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:18}).addTo(routeMap);
      const layer=L.layerGroup().addTo(routeMap);
      const density=RouteQuality.analyze(routeData.observations||[],routeData.segments||[],'state_time');
      density.parts.forEach(part=>L.polyline(part.points.map(p=>[p.latitude,p.longitude]),RouteQuality.lineOptions(part)).addTo(layer));
      for(const [point,label] of [[points[0],'首个采样点'],[points.at(-1),'末个采样点']])
        L.circleMarker([point.latitude,point.longitude],{radius:6,color:'#20776e',fillOpacity:1}).addTo(layer).bindTooltip(label);
      const bounds=points.map(p=>[p.latitude,p.longitude]);
      if(bounds.length===1)routeMap.setView(bounds[0],14);
      else routeMap.fitBounds(bounds,{padding:[24,24],maxZoom:15});
    }
    async function loadRoute(){
      if(!selected||routeShown)return;
      const identity=owner,eventId=selected.id,token=++routeSerial;
      routeShown=routeBusy=true;routeData=null;routeError='';paint();
      try{
        const result=await request(`/api/tracks?date=${encodeURIComponent(tripDate(selected.end_time))}&trip=${encodeURIComponent(eventId)}`);
        if(token!==routeSerial||owner!==identity||context()!==identity||selected?.id!==eventId)return;
        routeData=result;
      }catch(failure){if(token===routeSerial&&owner===identity&&selected?.id===eventId)routeError=failure.message;}
      finally{if(token===routeSerial&&owner===identity&&selected?.id===eventId){routeBusy=false;paint();}}
    }
    function paintEvents(){
      const el=node?.querySelector('#tag-events');if(!el||!data)return;
      const rows=data.events.filter(r=>(!filter||r.tags.includes(filter))&&(completeness==='all'||r.partial===(completeness==='partial')));
      const pages=Math.max(1,Math.ceil(rows.length/10));page=Math.max(0,Math.min(page,pages-1));
      el.innerHTML=(rows.slice(page*10,page*10+10).map(r=>`<article class="rule-record" data-tag-event="${esc(r.id)}"><div class="insight-heading"><h4>${esc(time(r.end_time))}</h4><span class="insight-badge">${r.partial?'观测片段':'完整记录'}</span></div><div class="tag-trip-facts"><span>开始<strong>${esc(time(r.start_time))}</strong></span><span>结束<strong>${esc(time(r.end_time))}</strong></span><span>里程<strong>${number(r.distance_km)} km</strong></span><span>时长<strong>${number(r.duration_seconds===null?null:r.duration_seconds/60)} 分钟</strong></span></div><p>SOC ${number(r.start_soc)}% → ${number(r.end_soc)}% · 电量估算 ${number(r.estimated_kwh)} kWh</p><div class="insight-badges">${r.tags.map(tag=>`<span class="insight-badge">${esc(tag)}</span>`).join('')||'<span class="insight-note">未贴标签</span>'}</div>${r.note?`<p class="ledger-note">${esc(r.note)}</p>`:''}<div class="insight-actions">${button('标注这趟行程','edit',false,`data-id="${esc(r.id)}"`)}${r.annotation_id?button('删除行程标签','delete',false,`data-id="${esc(r.annotation_id)}"`):''}</div></article>`).join('')||'<p class="insight-empty">本月没有符合筛选的行程</p>')+`<div class="insight-pagination">${button('上一页标签行程','previous',page===0)}<span>${rows.length} 条 · ${page+1} / ${pages}</span>${button('下一页标签行程','next',page+1===pages)}</div>`;
      const trashPages=Math.max(1,Math.ceil(data.trash.length/10));trashPage=Math.min(trashPage,trashPages-1);
      node.querySelector('#tag-trash').innerHTML=data.trash.length?`<section class="card insight-panel"><h3>已删除的行程标签</h3><div class="ledger-trash-list">${data.trash.slice(trashPage*10,trashPage*10+10).map(r=>`<div><span>${esc(time(r.end_time))} · ${esc(r.tags.join('、')||'无标签')}</span>${button('恢复行程标签','restore',false,`data-id="${esc(r.id)}"`)}</div>`).join('')}</div><div class="insight-pagination">${button('上一页删除标签','trash-previous',trashPage===0)}<span>${trashPage+1} / ${trashPages}</span>${button('下一页删除标签','trash-next',trashPage+1===trashPages)}</div></section>`:'';
    }
    async function load(){
      if(!owner||!month)return false;
      const token=++serial,identity=owner;attempted=true;loading=true;error='';paint();
      try{const result=await request('/api/insights/trip-tags?date='+encodeURIComponent(month+'-01'));
        if(!valid(token,serial,identity))return false;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data=result;page=trashPage=0;
        if(selected){selected=data.events.find(row=>row.id===selected.id)||null;if(!selected)closeRoute();}
        if(!data.groups.some(g=>g.tag===groupA))groupA=data.groups[0]?.tag||'';
        if(!data.groups.some(g=>g.tag===groupB))groupB=data.groups[1]?.tag||data.groups[0]?.tag||'';
        if(!data.groups.some(g=>g.tag===filter))filter='';return true;
      }catch(failure){if(valid(token,serial,identity))error=failure.message;return false;}
      finally{if(valid(token,serial,identity)){loading=false;paint();}}
    }
    async function mutate(action,id){
      if(busy||loading||!data||action==='save'&&!selected)return;
      const token=++writeSerial,identity=owner,payload={action,id,revision:data.revision,context:owner};
      if(action==='save')Object.assign(payload,{id:selected.annotation_id,event_id:selected.id,tags:tags.split(/[,，\n]/).map(s=>s.trim()).filter(Boolean),note});
      busy=true;error='';status='';paint();
      try{const result=await request('/api/insights/trip-tags',payload);if(!valid(token,writeSerial,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        data.revision=result.revision;data.can_undo=result.can_undo;status='行程标签操作已保存。';
        if(action==='delete'&&selected?.annotation_id===id){selected=null;tags=note='';closeRoute();}
        if(!await load()&&valid(token,writeSerial,identity))status+=' 列表尚未刷新，请重新读取核对。';
      }catch(failure){if(valid(token,writeSerial,identity))error=failure.message+' 填写内容保留；请重新读取核对后操作。';}
      finally{if(valid(token,writeSerial,identity)){busy=false;paint();}}
    }
    let tripRevision;
    function mount(container){
      const changed=owner!==context()||tripRevision!==getState()?.trip_records_revision,remount=node!==container;node=container;
      tripRevision=getState()?.trip_records_revision;
      if(changed){owner=context();data=null;selected=null;tags=note='';attempted=false;loading=busy=false;serial++;writeSerial++;error=status='';filter=groupA=groupB='';closeRoute();}
      if(changed||remount)paint();if(owner&&!attempted&&!loading)load();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if(event.type==='input'&&el.id==='tag-month'){month=el.value;node.querySelector('[data-tag="load"]').disabled=!owner||!month||loading||busy;return true;}
      if(event.type==='input'&&el.id==='tag-labels'){tags=el.value;syncQuickLabels();return true;}
      if(event.type==='input'&&el.id==='tag-note'){note=el.value;return true;}
      if(event.type==='change'){
        if(el.id==='tag-group-a'){groupA=el.value;paintGroups();return true;}
        if(el.id==='tag-group-b'){groupB=el.value;paintGroups();return true;}
        if(el.id==='tag-filter'){filter=el.value;page=0;paintEvents();return true;}
        if(el.id==='tag-completeness'){completeness=el.value;page=0;paintEvents();return true;}
      }
      if(event.type!=='click')return false;
      const target=el.closest('[data-tag]');if(!target||target.disabled)return false;
      const action=target.dataset.tag,id=target.dataset.id;
      if(action==='load')load();
      else if(action==='edit'){closeRoute();selected=data.events.find(r=>r.id===id);tags=selected.tags.join(', ');note=selected.note;error='';paint();node.querySelector('#tag-form').scrollIntoView({block:'start'});}
      else if(action==='cancel'){selected=null;tags=note='';closeRoute();paint();}
      else if(action==='show-route')loadRoute();
      else if(action==='hide-route'){closeRoute();paint();}
      else if(action==='toggle-label'){
        const labels=labelList(),label=target.dataset.label,index=labels.indexOf(label);
        if(index<0)labels.push(label);else labels.splice(index,1);
        tags=labels.join(', ');paint();
      }
      else if(action==='previous'){page--;paintEvents();}else if(action==='next'){page++;paintEvents();}
      else if(action==='trash-previous'){trashPage--;paintEvents();}else if(action==='trash-next'){trashPage++;paintEvents();}
      else mutate(action,id);return true;
    }
    return {mount,handle};
  }
  root.TripTagsPage={create};
})(window);
