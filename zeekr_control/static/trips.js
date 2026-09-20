'use strict';

// Local summaries never load coordinates. Only the shared position permission does.
let localTrips = null;
let tripManagementOpen = false;
const tripStatusLabels = {driving:'行程记录中', waiting:'停车确认中', ended:'已结束'};
const tripTime = value => Number.isFinite(value) ? new Intl.DateTimeFormat('zh-CN', {
  timeZone:'Asia/Shanghai', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false
}).format(new Date(value)) : '未知';
const tripNumber = (value, unit='') => Number.isFinite(value) ? `${Number(value.toFixed(2))}${unit}` : '未知';
const tripDuration = seconds => Number.isFinite(seconds) ? seconds < 60 ? `${Math.round(seconds)} 秒` : `${Number((seconds/60).toFixed(1))} 分钟` : '未知';
const tripPointKey = point => point ? `${point.state_time}:${point.observed_time}` : '';

function syncLocalTrips() {
  const context = [state?.request_key,state?.insights_context,state?.field_reviews?.vehicle || state?.vehicle,trackDate].join('|');
  if (!localTrips || localTrips.context !== context) {
    stopLocalPlayback();
    localTrips = {context,events:null,active:null,nextCursor:null,cursor:null,previous:[],listBusy:false,
      listError:'',listRequest:0,selection:'day',selected:null,route:null,routeError:'',routeBusy:false,
      routeRequest:0,index:0,speed:1,timer:null,layers:null,viewport:null,notice:''};
  }
  return localTrips;
}

function localTripsPage() {
  syncLocalTrips();
  return `<div id="local-trips">
    <div class="local-trip-tools"><div class="local-date-nav">${action('前一天','local-day-before','secondary')}${action('今天','local-today','secondary')}${action('后一天','local-day-after','secondary')}</div><div class="local-date-nav">${action(tripManagementOpen?'收起管理':'管理行程','local-manage','secondary')}${action('重新查询','local-reload','secondary','refresh')}</div></div>
    ${tripManagementOpen?'<div id="trip-management"></div>':''}
    <div id="local-trip-activity" class="notice info" role="status"></div>
    <div class="local-trip-layout"><section class="card local-trip-list-card"><div class="card-head"><h2>行程记录</h2><span class="subtle">北京时间</span></div><div id="local-trip-list"></div></section>
    <section class="card local-trip-detail" id="local-trip-detail"></section></div>
    <p class="section-note local-trip-note">本地采样仅覆盖后台记录期间。行程按结束日期归档；单趟路线包含跨午夜部分。路线为采样折线，坐标对齐仍待核验。</p>
  </div>`;
}

function localTripRow(trip) {
  const selected = localTrips.selection === trip.id;
  const status = tripStatusLabels[trip.status] || '已结束';
  return `<button class="local-trip-row ${selected?'selected':''}" data-local-trip="${esc(trip.id)}" aria-pressed="${selected}" aria-label="查看行程 ${esc(tripTime(trip.start_time))}，${esc(tripNumber(trip.distance_km,' km'))}">
    <span class="local-trip-row-head"><strong>${esc(tripTime(trip.start_time))}</strong>${pill(status,trip.status==='driving'?'good':trip.status==='waiting'?'warn':'')}</span>
    <span class="local-trip-row-end">${trip.status==='ended'?'结束':'最近记录'} ${esc(tripTime(trip.end_time))}</span>
    <span class="local-trip-row-values"><b>${esc(tripNumber(trip.distance_km,' km'))}</b><span>${esc(tripDuration(trip.duration_seconds))}</span></span>
    <span class="subtle">电量 ${esc(tripNumber(trip.start_soc,'%'))} → ${esc(tripNumber(trip.end_soc,'%'))}${trip.partial?' · 部分行程记录':''}</span>
  </button>`;
}

function renderLocalTripList() {
  const h = localTrips, target = $('#local-trip-list');
  if (!target) return;
  const focusId = document.activeElement?.dataset.localTrip;
  const current = h.active ? `<div class="local-trip-list-label">当前记录</div>${localTripRow(h.active)}` : '';
  const records = h.events?.length ? h.events.map(localTripRow).join('') : h.events === null ? (h.listError ? '' : '<p class="card-body subtle">正在读取行程…</p>') : '<p class="card-body subtle">这一天暂无已结束行程。仍可查看全天采样。</p>';
  target.innerHTML = `<button class="local-trip-day ${h.selection==='day'?'selected':''}" data-local-trip="day" aria-pressed="${h.selection==='day'}">${icon('map')}<span>全天总览</span>${icon('arrow')}</button>${current}<div class="local-trip-list-label">已结束行程</div>${h.listError?`<p class="card-body unknown" role="alert">${esc(h.listError)} ${action('重试','local-reload','quiet')}</p>`:''}${records}
    <div class="event-pagination local-trip-pagination"><button class="button secondary" data-action="local-prev" ${!h.previous.length||h.listBusy?'disabled':''}>上一页</button><span>第 ${h.previous.length+1} 页</span><button class="button secondary" data-action="local-next" ${!h.nextCursor||h.listBusy?'disabled':''}>下一页</button></div>`;
  if (focusId) [...target.querySelectorAll('[data-local-trip]')].find(button=>button.dataset.localTrip===focusId)?.focus({preventScroll:true});
}

function renderLocalTripActivity() {
  const target = $('#local-trip-activity');
  if (!target) return;
  const active = localTrips.active;
  const status = localTrips.listError ? '行程状态暂无法更新' : localTrips.events===null ? '正在读取行程状态' : active ? tripStatusLabels[active.status] : '所选日期无进行中的记录';
  const availability = !state?.recording?.active ? '采集已暂停' : !state?.monitoring?.online ? '后台未在线' : '后台采集中';
  target.innerHTML = `${icon('info')}<span><strong>${status}</strong> · ${availability}。${active?.status==='waiting'?'已观测到停车，等待连续确认后归档。':'状态来自后台最近观测，可能有延迟。'}${localTrips.notice?` ${esc(localTrips.notice)}`:''}</span>`;
}

function localTripFacts() {
  const h = localTrips, trip = h.selected;
  if (h.selection === 'day') return `<div class="local-trip-intro"><h2>全天采样总览</h2><p class="subtle">${esc(trackDate)} · 选择左侧行程，可单独查看这一趟路线。</p></div>`;
  if (!trip) return '<p class="card-body subtle">正在读取行程…</p>';
  const endLabel = trip.status==='ended'?'结束时间':trip.status==='waiting'?'停车观测':'最近观测';
  const delta = Number.isFinite(trip.start_soc)&&Number.isFinite(trip.end_soc) ? trip.end_soc-trip.start_soc : null;
  return `<div class="local-trip-intro"><div class="local-trip-title"><h2>单趟行程</h2>${pill(tripStatusLabels[trip.status]||'已结束')}</div>
    <div class="local-trip-times"><span>开始 ${esc(tripTime(trip.start_time))}</span><span>${endLabel} ${esc(tripTime(trip.end_time))}</span></div>
    <div class="local-trip-facts"><div><span>行驶里程</span><strong>${esc(tripNumber(trip.distance_km,' km'))}</strong></div><div><span>观测时长</span><strong>${esc(tripDuration(trip.duration_seconds))}</strong></div><div><span>起止电量</span><strong>${esc(tripNumber(trip.start_soc,'%'))} → ${esc(tripNumber(trip.end_soc,'%'))}</strong></div><div><span>电量变化</span><strong>${delta===null?'未知':`${delta>0?'+':''}${esc(tripNumber(delta))} 个百分点`}</strong></div></div>
    <p class="subtle local-record-note">${trip.partial?'行程记录：部分记录，起止或过程存在缺失。':'行程记录：未标记为部分记录。'}路线采样情况另列，不代表 GPS 路线完整。</p></div>`;
}

function renderLocalTripDetail() {
  const target = $('#local-trip-detail');
  if (!target) return;
  target.innerHTML = `<div id="local-trip-facts">${localTripFacts()}</div><div id="local-trip-route"></div>`;
  renderLocalRoute();
}

function localTripVisible(h) {
  return localTrips===h && page==='tracks' && trackSource==='local' && !!$('#local-trips');
}

function loadLocalTrips() {
  const h = syncLocalTrips();
  if (!h.listTask) {
    const task=fetchLocalTrips(h).finally(()=>{if(h.listTask===task)h.listTask=null;});
    h.listTask=task;
  }
  return h.listTask;
}

async function fetchLocalTrips(h) {
  h.listBusy=true; h.listError='';
  const request=++h.listRequest;
  renderLocalTripList();
  try {
    const result=await api(`/api/trips?date=${encodeURIComponent(trackDate)}${h.cursor?`&cursor=${encodeURIComponent(h.cursor)}`:''}`);
    if (!localTripVisible(h) || request!==h.listRequest) return;
    if(h.revision!==undefined&&result.revision!==h.revision&&h.selection!=='day'&&h.selection!=='current'){
      clearLocalRoute();h.selection='day';h.selected=null;h.notice='行程记录已变化，已回到全天总览。';renderLocalTripDetail();
    }
    h.revision=result.revision;
    h.events=result.events || [];h.active=result.active;h.nextCursor=result.next_cursor;
    if (h.selection==='current' && (!h.active || h.active.start_time!==h.selected?.start_time)) {
      const completed=h.events.find(event=>event.start_time===h.selected?.start_time);
      h.selection=completed?.id || 'day';h.selected=completed || null;
      clearLocalRoute();h.notice='进行中记录已更新，请查看已结束行程。';
      renderLocalTripDetail();
    } else if (h.selection!=='day') {
      h.selected=h.selection==='current'?h.active:h.events.find(event=>event.id===h.selection) || h.selected;
    }
  } catch(error) {
    if (localTripVisible(h) && request===h.listRequest) h.listError=error.message;
  } finally {
    h.listBusy=false;
    if (localTripVisible(h) && request===h.listRequest) {
      renderLocalTripList();renderLocalTripActivity();
      if ($('#local-trip-facts')) $('#local-trip-facts').innerHTML=localTripFacts();
    }
  }
}

function mountLocalTrips() {
  const h=syncLocalTrips();
  renderLocalTripList();renderLocalTripActivity();renderLocalTripDetail();
  if(tripManagementOpen)tripManager.mount($('#trip-management'));
  loadLocalTrips().then(()=>{if (showPosition && localTripVisible(h)) loadLocalRoute();});
}

function refreshLocalTrips() {
  if (!$('#local-trips')) return false;
  const h=localTrips;
  if (syncLocalTrips()!==h) return false;
  if(tripManagementOpen)tripManager.mount($('#trip-management'));
  renderLocalTripActivity();
  loadLocalTrips().then(()=>{
    if (localTripVisible(h) && showPosition && (h.selection==='day'||h.selection==='current'||!h.route)) loadLocalRoute();
  });
  return true;
}

function clearLocalRoute() {
  stopLocalPlayback();
  localTrips.routeRequest++;localTrips.route=null;localTrips.routeError='';localTrips.routeBusy=false;
  localTrips.index=0;localTrips.viewport=null;localTrips.layers=null;
  trackData=null;playback=[];
  if (map) {map.remove();map=null;mapMarker=null;}
}

async function loadLocalRoute(force=false) {
  const h=localTrips;
  if (!h || !showPosition || !localTripVisible(h) || (h.routeBusy&&!force)) return;
  h.routeBusy=true;h.routeError='';
  const selection=h.selection, request=++h.routeRequest;
  if (!h.route) renderLocalRoute();
  try {
    const result=await api(`/api/tracks?date=${encodeURIComponent(trackDate)}${selection==='day'?'':`&trip=${encodeURIComponent(selection)}`}`);
    if (!localTripVisible(h)||!showPosition||request!==h.routeRequest||selection!==h.selection) return;
    if (JSON.stringify(result)!==JSON.stringify(h.route)) {
      const point=tripPointKey(playback[h.index]);
      h.route=result;trackData=result;
      const next=result.observations.filter(item=>item.plottable);
      const matched=next.findIndex(item=>tripPointKey(item)===point);
      h.index=matched>=0?matched:Math.min(h.index,Math.max(0,next.length-1));
      playback=next;
      renderLocalRoute();
    }
  } catch(error) {
    if (localTripVisible(h)&&request===h.routeRequest&&showPosition) {h.routeError=error.message;renderLocalRoute();}
  } finally {
    if (request===h.routeRequest) {
      h.routeBusy=false;
      if(localTripVisible(h))renderLocalRouteStatus();
    }
  }
}

function localRouteQuality(result) {
  const quality=result.quality || {}, gaps=result.gaps || [];
  const trusted=result.observations.filter(point=>point.trusted&&point.plottable).length;
  const unknown=quality.untrusted_count ?? result.observations.filter(point=>!point.trusted).length;
  return `<div class="local-route-summary"><span><b>${result.count}</b> 条采样</span><span><b>${trusted}</b> 个可信可绘点</span><span><b>${gaps.length}</b> 处间断</span>${unknown?`<span>${unknown} 个位置未确认</span>`:''}</div>
    ${result.truncated?'<p class="unknown">仅展示前 5000 条采样，后续记录未展示；末个采样点不代表行程终点。</p>':''}
    <p class="subtle">${!result.count?'本次范围没有采样，无法判断路线情况。':gaps.length?'存在采样缺口，地图分段展示。':'当前记录未发现超过阈值的间断；不能据此确认实际路线完整。'}首末标记仅代表可绘采样点。</p>
    ${gaps.length?`<details class="local-gap-details"><summary>查看 ${gaps.length} 处采样间断</summary><ul>${gaps.map(gap=>`<li><span>${esc(tripTime(gap.start_time))} → ${esc(tripTime(gap.end_time))}</span><strong>${esc(tripDuration(gap.duration_seconds))}</strong><span class="subtle">${esc(gap.reason || '间断原因未确认')}</span></li>`).join('')}</ul></details>`:''}`;
}

function renderLocalRouteStatus() {
  const h=localTrips,target=$('#local-route-message');
  if (target) target.innerHTML=h.routeError?`<span class="unknown" role="alert">${esc(h.routeError)}${h.route?' · 保留上次路线。':''}</span> ${action('重试路线','local-route-retry','quiet')}`:h.routeBusy?'正在读取采样…':'';
}

function renderLocalRoute() {
  const h=localTrips,target=$('#local-trip-route');
  if (!target) return;
  if (!showPosition) {target.innerHTML=privacyGate(true);return;}
  const result=h.route;
  if (!result) {
    target.innerHTML=`<div class="local-route-toolbar">${action('隐藏位置','hide-position','secondary')}</div><div id="local-route-message" class="card-body" role="status"></div>`;
    renderLocalRouteStatus();return;
  }
  const existing=!!map && !!$('#local-trips #map');
  if (!existing) {
    target.innerHTML=`<div class="local-route-toolbar"><span class="subtle">${h.selection==='day'?'全天采样':'本趟采样'} · 北京时间</span><div class="local-route-actions">${action('查看全程','local-fit','secondary')}${action('隐藏位置','hide-position','secondary')}</div></div><div id="local-route-message" class="card-body" role="status"></div><div id="local-route-quality" class="local-route-quality"></div>
      <div id="map" class="map-canvas" aria-label="本地采样轨迹地图"></div><div id="map-status" class="map-status"></div>
      <div class="track-timeline"><div id="playback-label" class="subtle" aria-live="off">暂无可回看的位置</div><input id="playback" type="range" aria-label="轨迹回看位置" min="0" max="0" value="0" disabled>
      <div class="local-playback-controls">${action('上一点','local-step-back','secondary')}${action('播放','local-play','secondary')}${action('下一点','local-step-next','secondary')}<label>速度 <select id="local-playback-speed" class="select" aria-label="回放速度"><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label></div><p class="subtle local-playback-note">1× 每秒前进一个采样点；按记录回看，不代表实际车速。缺口直接跳到下一段。</p></div>
      <details class="local-observation-details"><summary>采样详情</summary><div id="local-observation-list" class="point-list"></div></details>`;
  }
  $('#local-route-quality').innerHTML=localRouteQuality(result);
  $('#local-observation-list').innerHTML=result.observations.map(point=>`<div class="point"><span>${esc(point.time_label)}<span class="field-path">${esc(point.time_source)}</span></span>${pill(point.trusted?'接口标记可信':'位置未确认',point.trusted?'':'warn')}</div>`).join('');
  $('#map-status').textContent=`${result.count} 条观测 · ${result.segments.length} 个可信片段 · 时间以缓存状态时间为准，缺失时使用本机观测时间`;
  playback=result.observations.filter(point=>point.plottable);
  $('#playback').max=Math.max(0,playback.length-1);$('#playback').disabled=!playback.length;
  $('#local-playback-speed').value=String(h.speed);
  renderLocalRouteStatus();
  if (!playback.length) {
    $('#map').innerHTML=empty(result.count?'没有可绘制的位置':h.selection==='day'?'这一天还没有本地记录':'本趟暂无位置采样',result.count?'观测已保存，但坐标无效或坐标系尚未适配。':'本次范围内没有采样，已有行程摘要仍可查看。','map');
    updateLocalPlaybackControls();return;
  }
  if (!existing) createMap([playback[0].latitude,playback[0].longitude],13);
  if (h.layers) h.layers.remove();
  h.layers=L.layerGroup().addTo(map);
  result.segments.forEach(segment=>{
    if (segment.length>1) L.polyline(segment.map(point=>[point.latitude,point.longitude]),{color:'#20776e',weight:4}).addTo(h.layers);
  });
  playback.forEach(point=>L.circleMarker([point.latitude,point.longitude],{radius:4,color:point.trusted?'#20776e':'#7c8588',fillOpacity:.7,weight:1}).addTo(h.layers));
  for (const [point,label] of [[playback[0],'首个采样点'],[playback.at(-1),'末个采样点']]) {
    L.circleMarker([point.latitude,point.longitude],{radius:7,color:point.trusted?'#20776e':'#7c8588',fillOpacity:1,weight:2}).addTo(h.layers).bindTooltip(label,{permanent:true,direction:label==='首个采样点'?'top':'bottom'});
  }
  // Mark only observed gap boundaries. Never place inferred coordinates in a gap.
  const knownPositions=new Map(playback.filter(point=>point.trusted&&Number.isFinite(point.state_time)).map(point=>[point.state_time,point]));
  for (const gap of result.gaps || []) {
    const boundaries=[...new Set([knownPositions.get(gap.start_time),knownPositions.get(gap.end_time)].filter(Boolean))];
    boundaries.forEach((point,index)=>{
      L.circleMarker([point.latitude,point.longitude],{radius:10,color:'#99621d',dashArray:'3 3',fillOpacity:0,weight:2}).addTo(h.layers)
        .bindTooltip(`采样间断 · ${tripDuration(gap.duration_seconds)}`,{permanent:index===boundaries.length-1,direction:'auto',className:'local-gap-tooltip'});
    });
  }
  if (!existing) {
    if (h.viewport) map.setView(h.viewport.center,h.viewport.zoom,{animate:false});
    else fitLocalRoute();
  }
  displayLocalPoint(h.index,false);
}

function fitLocalRoute() {
  if (!map || !playback.length) return;
  map.stop();map.invalidateSize({pan:false});
  map.fitBounds(playback.map(point=>[point.latitude,point.longitude]),{padding:[55,55],maxZoom:16,animate:false});
}

function displayLocalPoint(index,pan=true) {
  const h=localTrips;
  if (!h || !playback.length) return;
  h.index=Math.max(0,Math.min(index,playback.length-1));
  setPlayback(h.index,{pan});
  if ($('#playback')) $('#playback').value=h.index;
  updateLocalPlaybackControls();
}

function updateLocalPlaybackControls() {
  const h=localTrips;
  if (!h || !$('#local-trips')) return;
  const play=$('[data-action="local-play"]');
  if (play) {play.textContent=h.timer?'暂停':'播放';play.disabled=playback.length<2;}
  const back=$('[data-action="local-step-back"]'),next=$('[data-action="local-step-next"]');
  if(back)back.disabled=!playback.length||h.index===0;
  if(next)next.disabled=!playback.length||h.index>=playback.length-1;
}

function stopLocalPlayback() {
  if (!localTrips) return;
  clearInterval(localTrips.timer);localTrips.timer=null;
  updateLocalPlaybackControls();
}

function startLocalPlayback() {
  const h=localTrips;
  if (!h || playback.length<2 || !showPosition) return;
  stopLocalPlayback();
  if (h.index>=playback.length-1) displayLocalPoint(0);
  h.timer=setInterval(()=>{
    if (!localTripVisible(h)||!showPosition||document.hidden) {stopLocalPlayback();return;}
    displayLocalPoint(h.index+1);
    if(h.index>=playback.length-1)stopLocalPlayback();
  },1000/h.speed);
  updateLocalPlaybackControls();
}

function prepareLocalTripRender() {
  if (!localTrips) return;
  if (map && $('#local-trips')) localTrips.viewport={center:map.getCenter(),zoom:map.getZoom()};
  stopLocalPlayback();
  if (!showPosition) {localTrips.routeRequest++;localTrips.route=null;localTrips.routeBusy=false;localTrips.routeError='';localTrips.index=0;localTrips.viewport=null;}
}

function handleLocalTripAction(target) {
  if (page!=='tracks'||trackSource!=='local') return false;
  const h=localTrips;
  if (target.dataset.localTrip) {
    const selection=target.dataset.localTrip;
    if(h.selection===selection)return true;
    const trip=selection==='current'?h.active:h.events?.find(event=>event.id===selection);
    if(selection!=='day'&&!trip)return true;
    clearLocalRoute();h.selection=selection;h.selected=trip || null;h.notice='';
    renderLocalTripList();renderLocalTripDetail();
    if(showPosition)loadLocalRoute();return true;
  }
  switch(target.dataset.action) {
    case 'local-manage':tripManagementOpen=!tripManagementOpen;stopLocalPlayback();render();return true;
    case 'local-fit': stopLocalPlayback();fitLocalRoute();return true;
    case 'local-play': h.timer?stopLocalPlayback():startLocalPlayback();return true;
    case 'local-step-back': stopLocalPlayback();displayLocalPoint(h.index-1);return true;
    case 'local-step-next': stopLocalPlayback();displayLocalPoint(h.index+1);return true;
    case 'local-route-retry': loadLocalRoute(true);return true;
    case 'local-reload': loadLocalTrips().then(()=>{if(localTripVisible(h)&&showPosition)loadLocalRoute(true);});return true;
    case 'local-prev': if(h.previous.length){h.cursor=h.previous.pop();loadLocalTrips();}return true;
    case 'local-next': if(h.nextCursor){h.previous.push(h.cursor);h.cursor=h.nextCursor;loadLocalTrips();}return true;
    case 'local-day-before': case 'local-day-after': case 'local-today': {
      const date=new Date(`${trackDate || beijingDate(Date.now())}T12:00:00+08:00`);
      trackDate=target.dataset.action==='local-today'?beijingDate(Date.now()):beijingDate(date.getTime()+(target.dataset.action==='local-day-before'?-1:1)*86400000);
      render();return true;
    }
    default:return false;
  }
}

document.addEventListener('visibilitychange',()=>{if(document.hidden)stopLocalPlayback();});
