(function(root){
  'use strict';
  const sourceNames={saved_precharge_reference:'充电前可信位置与连续停留参考',charge_samples:'整段充电定位',single_sample:'单点参考位置',charge_boundaries:'充电边界参考位置',stationary_between_trips:'相邻行程与连续停留推定',conflict:'定位冲突，暂不能确认',sample_limit:'定位样本超出分析上限',unknown:'缺少可用历史定位'};
  const stamp=t=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(t));
  function create({request,escape:esc,context,active,paint,onSaved,onError}){
    let id='',identity='',detail=null,draft=null,preview=null,candidates=null,error='',busy=false,loading=false,shown=false,map=null,marker=null,serial=0,page=0,moved=false;
    const button=(text,action,attrs='')=>`<button type="button" data-place-action="${action}" ${busy||loading?'disabled':''} ${attrs}>${text}</button>`;
    const valid=(token,owner)=>serial===token&&identity===owner&&context()===owner&&active();
    let pointerHeld=false;
    const deferredRefreshes=new Set();
    function finishInteraction(refresh){
      pointerHeld=false;root.removeEventListener('mouseup',releasePointer);root.removeEventListener('blur',releasePointer);
      const callbacks=[...deferredRefreshes];deferredRefreshes.clear();
      if(refresh&&callbacks.length){const token=serial,owner=identity;queueMicrotask(()=>{for(const callback of callbacks)if(valid(token,owner))callback();});}
    }
    // Leaflet handles mouseup on document first; flush only after its dragend.
    function releasePointer(){finishInteraction(true);}
    function holdPointer(event){
      if(event.button!==0||event.shiftKey)return;
      pointerHeld=true;root.addEventListener('mouseup',releasePointer);root.addEventListener('blur',releasePointer);
    }
    // Keep the marker alive through the entire gesture, including before dragstart.
    // Context changes and navigation bypass this guard and cancel queued refreshes.
    function deferRefresh(callback){
      if(!pointerHeld||identity!==context()||!active())return false;
      deferredRefreshes.add(callback);return true;
    }
    function removeMap(){finishInteraction(false);if(map){map.remove();map=null;marker=null;}}
    function close(redraw=true){serial++;removeMap();id='';identity='';detail=draft=preview=candidates=null;error='';busy=loading=shown=moved=false;if(redraw)paint();}
    async function open(eventId){
      close(false);id=eventId;identity=context();const owner=identity,token=++serial;loading=true;paint();
      try{
        const result=await request('/api/insights/charging-place?event='+encodeURIComponent(id),undefined,50000,{active});
        if(!valid(token,owner))return;if(result.context!==owner)throw Error('账号或车辆已切换，请重新读取。');
        detail=result;draft={event_id:id,revision:result.revision,scope:result.correction_scope||'single',name:result.name==='地点未知'?'':result.name,
          station_name:result.station_name||'',latitude:result.location?.latitude??null,longitude:result.location?.longitude??null,radius_m:result.radius_m||75};
      }catch(e){if(valid(token,owner))error=e.message;}
      finally{if(valid(token,owner)){loading=false;paint();}}
    }
    function invalidate(){preview=null;page=0;const panel=document.querySelector('.cr-place-editor');panel?.querySelector('[data-place-preview]')?.remove();const save=panel?.querySelector('[data-place-action="save"]');if(save)save.disabled=true;}
    function payload(action){return {...draft,context:identity,action};}
    async function run(action){
      if(busy||loading||!draft)return;const owner=identity,token=serial;busy=true;error='';paint();
      try{
        const route='/api/insights/charging-place'+(action==='candidates'?'/candidates':'');
        const body=action==='candidates'?{context:owner,event_id:id}:action==='save'?{...payload(action),token:preview?.token}:payload(action);
        const result=await request(route,body,50000,{active});
        if(!valid(token,owner))return;if(result.context!==owner)throw Error('账号或车辆已切换，请重新读取。');
        if(action==='preview'){preview=result;page=0;}
        if(action==='candidates')candidates=result;
        if(action==='save'){close(false);await onSaved();return;}
      }catch(e){if(valid(token,owner)){error=e.message;if(action==='save')preview=null;}}
      finally{if(valid(token,owner)){busy=false;paint();}}
    }
    async function undo(revision){
      if(busy)return;const owner=context();close(false);identity=owner;const token=++serial;busy=true;paint();
      try{const result=await request('/api/insights/charging-place',{context:owner,action:'undo',revision});if(!valid(token,owner))return;if(result.context!==owner)throw Error('账号或车辆已切换，请重新读取。');close(false);await onSaved();}
      catch(e){if(valid(token,owner)){busy=false;onError(e.message);}}
    }
    function html(eventId){
      if(id!==eventId)return '';
      const evidence=detail?.evidence;
      return `<section class="cr-place-editor" aria-label="充电地点详情"><div class="cr-editor-heading"><h4>充电地点</h4>${button('关闭地点详情','close')}</div>${loading?'<p role="status">正在读取历史定位依据…</p>':''}${error?`<p class="notice error" role="alert">${esc(error)}</p>`:''}${draft?`
        <div class="cr-location-evidence"><strong>${esc(sourceNames[evidence.source]||'参考位置')}</strong><span>${detail.name_source==='manual'?'名称已手动确认':detail.name_source==='unknown'?'场所名称待确认':'沿用已保存地点名称'}</span><p>${evidence.sample_count} 个有效定位点${evidence.outlier_count?` · 排除 ${evidence.outlier_count} 个漂移点`:''}${evidence.stationary_samples?` · ${evidence.stationary_samples} 个连续停留状态`:''}${detail.reference?' · 位置仅供参考':''}${evidence.reference_age_seconds!=null?' · 可信位置早于首次充电观测 '+Math.round(evidence.reference_age_seconds)+' 秒':''}</p>${evidence.start_time?`<p>${esc(stamp(evidence.start_time))} 至 ${esc(stamp(evidence.end_time))}</p>`:''}</div>
        ${detail.reference_candidate?`<div class="cr-reference-candidate"><strong>有充电前参考位置，尚未确认</strong><p class="cr-muted">早于首次充电观测 ${Math.round(detail.reference_candidate.age_seconds)} 秒。${detail.reference_candidate.name!=='地点未知'?esc(detail.reference_candidate.name)+'。':''}${detail.reference_candidate.boundary_distance_m>75?'与充电期间位置相差约 '+Math.round(detail.reference_candidate.boundary_distance_m)+' 米。':''}现有证据不足以自动采用；可在地图检查后仅修正本次。</p>${button('在地图查看参考位置','reference-map')}${button('采用参考位置作为本次修正','reference-use')}</div>`:''}
        <div class="cr-place-fields"><label>场所名称<input data-place-field="name" aria-label="场所名称" maxlength="80" value="${esc(draft.name)}" placeholder="例如：某某广场地下停车场" ${busy?'disabled':''}></label><label>充电站名称<input data-place-field="station_name" aria-label="充电站名称" maxlength="80" value="${esc(draft.station_name)}" placeholder="可留空，确认具体站点后填写" ${busy?'disabled':''}></label><label>地点修改范围<select data-place-field="scope" aria-label="地点修改范围" ${busy?'disabled':''}><option value="single" ${draft.scope==='single'?'selected':''}>仅本次充电</option><option value="place" ${draft.scope==='place'?'selected':''}>同地点历史及后续充电</option></select></label><label>同地点匹配范围<select data-place-field="radius_m" aria-label="同地点匹配范围" ${busy?'disabled':''}>${[25,50,75,100,150].map(r=>`<option value="${r}" ${draft.radius_m===r?'selected':''}>${r} 米</option>`).join('')}</select></label></div>
        <p class="cr-muted">场所与充电站分别保存。空站名表示未确认；候选站点不会自动选中。其他记录的单次修正优先保留；本次可切换为同地点规则。</p>
        <div class="cr-place-tools">${button('查找附近充电站','candidates')}${button(shown?'收起地点地图':'查看并校正地图位置','map')}</div>
        ${candidates?`<div class="cr-station-candidates" aria-label="附近充电站候选">${candidates.status==='unavailable'?'<p>暂不能查询附近站点，可手动填写。请检查地图服务配置或稍后重试。</p>':candidates.status==='no_location'?'<p>缺少历史位置，可先校正本次地点，保存后再查询站点。</p>':candidates.candidates.length?`<p class="cr-muted">仅为附近候选，不代表本次实际充电站。距离基于已保存位置；地图改点后请先预览、保存再查询。</p>${candidates.candidates.map((r,i)=>`<div><span>${esc(r.name)} <small>约 ${Math.round(r.distance_m)} 米</small></span>${button('选择 '+r.name,'station',`data-index="${i}"`)}</div>`).join('')}`:'<p>附近暂无可用充电站候选，可手动填写。</p>'}</div>`:''}
        ${shown?`<div class="cr-map-section"><p class="cr-muted">点击地图或拖动绿色标记校正位置。小点为历史定位，灰点为排除的漂移点；校正不会改写原始记录。</p><div class="cr-place-map" role="region" tabindex="0" aria-label="充电地点校正地图"></div><div class="cr-coordinate-fields"><label>纬度（WGS84）<input type="number" step="any" data-place-field="latitude" aria-label="纬度（WGS84）" value="${draft.latitude??''}" ${busy?'disabled':''}></label><label>经度（WGS84）<input type="number" step="any" data-place-field="longitude" aria-label="经度（WGS84）" value="${draft.longitude??''}" ${busy?'disabled':''}></label>${button('清除本次位置','clear-point')}${button('查看全部定位点','map-all')}</div><p class="cr-map-status" role="status">${moved?'地图位置已调整，尚未保存。':''}</p>${root.AmapMaps?'':'<p>地图组件未加载，可填写 WGS84 坐标后预览保存。</p>'}</div>`:''}
        ${preview?`<div data-place-preview role="status"><strong>将修改 ${preview.affected_count} 条已保存充电记录</strong><p>${esc(preview.name)}${preview.station_name?' · '+esc(preview.station_name):' · 具体站点未确认'}${preview.scope==='place'?'；同地点后续记录也沿用，其他记录已有的单次修正保留。':'；仅应用到本次充电。'}</p><p class="cr-muted">原始定位、账单与行程地点名称保持。${preview.location?'保存已选择的地图位置。':'位置保留未知。'}</p><ul>${preview.affected.slice(page*20,page*20+20).map(r=>`<li>${esc(r.date)} · ${esc(r.previous_name)}${r.previous_station?' / '+esc(r.previous_station):''}${r.effect==='outside_new_range'?' · 调整后移出范围，恢复 '+esc(r.new_name):''}</li>`).join('')}</ul>${preview.affected.length>20?`<div>${button('上一页预览','preview-previous',page===0?'disabled':'')} <span>${page+1} / ${Math.ceil(preview.affected.length/20)}</span> ${button('下一页预览','preview-next',(page+1)*20>=preview.affected.length?'disabled':'')}</div>`:''}</div>`:''}
        <div class="cr-place-tools">${button('预览地点修改','preview')}${button('保存地点修改','save',!preview?'disabled':'')}${detail.can_undo?button('撤销最近地点修改','undo'):''}${busy?'<span role="status">正在处理…</span>':''}</div>`:''}</section>`;
    }
    function selectPoint(p){
      if(busy||!draft||identity!==context()||!active())return;draft.latitude=Number(p.lat.toFixed(7));draft.longitude=Number(p.lng.toFixed(7));moved=true;invalidate();paint();
    }
    function setPin(point){
      if(!map)return;
      if(marker)marker.setLatLng(point);
      else{
        marker=root.L.marker(point,{draggable:true,icon:root.L.divIcon({className:'cr-map-pin',html:'<span></span>',iconSize:[24,24],iconAnchor:[12,12]})});
        marker.on('add',event=>event.target.getElement().addEventListener('mousedown',holdPointer,{capture:true}));
        marker.on('dragend',event=>selectPoint(event.target.getLatLng()));marker.addTo(map);
      }
    }
    function mount(node){
      const element=node?.querySelector('.cr-place-map');if(!element||map||!draft||!root.AmapMaps||!root.L)return;
      map=root.AmapMaps.createMap(element,{scrollWheelZoom:false});root.AmapMaps.addTiles(map);
      const point=Number.isFinite(draft.latitude)&&Number.isFinite(draft.longitude)?[draft.latitude,draft.longitude]:null;
      for(const sample of detail.samples){root.L.circleMarker([sample.latitude,sample.longitude],{radius:4,color:sample.outlier?'#737c77':'#326c94',fillOpacity:.6}).addTo(map).bindTooltip(esc(stamp(sample.time)));}
      if(point){setPin(point);map.setView(point,17);}
      else if(detail.reference_candidate){const p=detail.reference_candidate.location;root.L.circleMarker([p.latitude,p.longitude],{radius:9,color:'#9b6a25',fillOpacity:.25}).addTo(map).bindTooltip('充电前参考位置 · 尚未确认');map.setView([p.latitude,p.longitude],17);}
      else map.setView([35,105],4);
      map.on('click',e=>selectPoint(e.latlng));
    }
    function handle(event){
      const field=event.target.closest('[data-place-field]');
      if(field&&draft&&['input','change'].includes(event.type)){
        const key=field.dataset.placeField;draft[key]=['latitude','longitude'].includes(key)?field.value===''?null:Number(field.value):key==='radius_m'?Number(field.value):field.value;
        invalidate();if(key==='latitude'||key==='longitude'){moved=true;const status=document.querySelector('.cr-map-status');if(status)status.textContent='地图位置已调整，尚未保存。';if(Number.isFinite(draft.latitude)&&Number.isFinite(draft.longitude)&&Math.abs(draft.latitude)<=90&&Math.abs(draft.longitude)<=180){setPin([draft.latitude,draft.longitude]);if(event.type==='change')map?.setView([draft.latitude,draft.longitude],17);}}return true;
      }
      if(event.type!=='click')return false;
      const target=event.target.closest('[data-place-action]');if(!target||target.disabled)return false;
      const action=target.dataset.placeAction;
      if(action==='close')close();
      if(action==='map'){shown=!shown;paint();}
      if(action==='map-all'&&map){const points=detail.samples.map(s=>[s.latitude,s.longitude]);if(marker)points.push([marker.getLatLng().lat,marker.getLatLng().lng]);if(points.length)map.fitBounds(points,{padding:[30,30],maxZoom:17});}
      if(action==='reference-map'){shown=true;paint();}
      if(action==='reference-use'){const candidate=detail.reference_candidate;draft.latitude=candidate.location.latitude;draft.longitude=candidate.location.longitude;draft.scope='single';if(!draft.name&&candidate.name!=='地点未知')draft.name=candidate.name;moved=true;shown=true;invalidate();paint();}
      if(action==='clear-point'){draft.latitude=draft.longitude=null;moved=true;invalidate();paint();}
      if(action==='station'){draft.station_name=candidates.candidates[Number(target.dataset.index)].name;invalidate();paint();}
      if(action==='preview-previous'){page=Math.max(0,page-1);paint();}
      if(action==='preview-next'){page++;paint();}
      if(['preview','save','candidates'].includes(action))run(action);
      if(action==='undo')undo(detail.revision);
      return true;
    }
    return {open,html,mount,handle,close,removeMap,undo,deferRefresh};
  }
  root.ChargingPlaceEditor={create};
})(window);
