'use strict';

// Queries are explicit user actions; ordinary state polling never reads history.
let cloudHistory = null;
function syncCloudHistory() {
  const context = [trackDate,state?.vehicle,state?.request_key,state?.history?.connection_id,state?.history?.status].join('|');
  if (!cloudHistory || cloudHistory.context !== context) {
    cloudHistory = {context,result:null,busy:false,cursor:null,previous:[],selected:null,detail:null,detailBusy:false,detailRequest:0};
  }
}
function cloudButton(label, actionName, disabled = false) {
  return `<button class="button secondary" data-action="${actionName}" ${disabled?'disabled':''}>${label}</button>`;
}
function cloudConnectionHelp() {
  return `<details class="cloud-help"><summary>如何连接历史账号</summary><p>车辆状态和历史行程使用不同会话。请先确认同一副账号在官方 App 中能看到行程。</p><p>已有该账号的历史服务凭据时，在运行本服务的机器上执行：</p><code>python3 -m zeekr_control history-connect${(state?.vehicles?.length || 0)>1?' --vehicle '+Number(state.vehicle):''}</code><p>按终端提示隐藏输入已有凭据，再点击“查询行程”。凭据不要发送到聊天或粘贴到网页。没有历史凭据时，仍需完成官方 App 接口核验。</p></details>`;
}
function cloudStatus(result) {
  const titles = {authorization_required:'需要连接云端历史账号',vehicle_required:'请先选择车辆',vehicle_mismatch:'历史账号与当前车辆不匹配',forbidden:'账号无权读取云端历史',session_expired:'历史会话已失效',protocol_error:'历史接口暂不兼容',request_failed:'历史查询失败',rate_limited:'查询过于频繁',busy:'正在处理其他历史查询',selection_changed:'车辆或账号已切换'};
  return `<section class="card cloud-state" role="status">${empty(titles[result.status] || '历史查询暂不可用',result.message || result.detail || '请稍后重试。','tracks')}<div class="card-meta">${result.retry_after?`至少等待 ${esc(result.retry_after)} 秒后重试。`:'此状态不代表没有历史行程。'}${['authorization_required','session_expired','vehicle_mismatch'].includes(result.status)?cloudConnectionHelp():''}</div></section>`;
}
function cloudMetric(value, suffix) {
  return Number.isFinite(value) ? `${Number(value.toFixed(1))}${suffix}` : '未知';
}
function cloudTripDetail() {
  const trip = cloudHistory.selected;
  if (!trip) return '';
  let route;
  if (!showPosition) {
    route = `<div class="cloud-route-gate">${icon('map')}<h3>按需显示行程路线</h3><p class="subtle">路线可能包含常去地点。开启后会读取轨迹点；地图底图由 OpenStreetMap 提供。</p>${cloudButton('显示行程路线','cloud-show-route')}</div>`;
  } else if (cloudHistory.detailBusy) {
    route = `<div role="status">${empty('正在读取路线','正在查询所选行程的轨迹点。','tracks')}</div>`;
  } else if (!cloudHistory.detail) {
    route = `<div class="cloud-route-gate">${cloudButton('读取行程路线','cloud-retry-detail')}</div>`;
  } else if (!['available','empty'].includes(cloudHistory.detail.status)) {
    route = `<div class="cloud-route-error" role="status"><p>${esc(cloudHistory.detail.message || '路线读取失败，行程摘要仍可查看。')}</p>${cloudButton('重试路线','cloud-retry-detail')}</div>`;
  } else if (cloudHistory.detail.status === 'empty') {
    route = empty('这段行程没有可用轨迹点','已保留行程摘要，无法据此补画路线。','tracks');
  } else {
    route = `<div id="map" class="map-canvas" aria-label="云端行程路线地图"></div><div id="map-status" class="map-status"></div><div class="track-timeline"><div id="playback-label" class="subtle">拖动滑块逐点回看</div><input id="playback" type="range" aria-label="轨迹回看位置" min="0" max="0" value="0" disabled></div>`;
  }
  return `<section class="card" id="cloud-detail"><div class="card-head"><h2>行程详情</h2>${pill('云端历史')}${showPosition?cloudButton('隐藏位置','hide-position'):''}</div><div class="card-body cloud-trip-facts">${row('开始时间',trip.start_at)}${row('结束时间',trip.end_at)}${row('行驶里程',cloudMetric(trip.distance_km,' km'))}${row('行驶时长',cloudMetric(trip.duration_minutes,' 分钟'))}${row('平均速度',cloudMetric(trip.average_speed_kmh,' km/h'))}${row('行程上报',trip.report_at)}</div>${route}</section>`;
}
function cloudHistoryPage() {
  const h = cloudHistory;
  const connection = state?.history || {status:'authorization_required'};
  const today = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const dateControls = `<div class="cloud-controls"><div class="cloud-date-nav">${cloudButton('前一天','cloud-day-before')}${cloudButton('今天','cloud-today',trackDate===today)}${cloudButton('后一天','cloud-day-after',trackDate>=today)}</div><button class="button" data-action="cloud-query" ${h.busy||!trackDate?'disabled':''}>${icon('refresh')}${h.busy?'查询中…':'查询行程'}</button></div>`;
  const note = `<div class="notice info">${icon('info')}按北京时间的行程上报日期查询，跨午夜行程可能从前一天开始。云端记录与本地采样分别保存，不补画缺失路线。</div>`;
  if (h.busy) return dateControls + note + `<section class="card" aria-busy="true" role="status">${empty('正在查询云端行程','等待历史服务返回，请勿重复查询。','tracks')}</section>`;
  const result = h.result;
  if (!result) {
    if (connection.status !== 'ready') return dateControls + note + cloudStatus(connection);
    return dateControls + note + `<section class="card">${empty('查询所选日期的云端行程','选择日期，点击“查询行程”。','tracks')}</section>`;
  }
  if (!['available','empty'].includes(result.status)) return dateControls + note + cloudStatus(result);
  const trips = result.trips || [];
  const known = trips.filter(trip=>Number.isFinite(trip.distance_km));
  const summary = `<div class="cloud-summary" aria-label="本页行程统计"><div><span>本页行程</span><strong>${trips.length}<small> 段</small></strong></div><div><span>${known.length===trips.length?'本页里程':'本页已知里程'}</span><strong>${known.length?cloudMetric(known.reduce((sum,trip)=>sum+trip.distance_km,0),''): '—'}<small> km</small></strong></div><div class="cloud-read-time"><span>${result.cached?'本机缓存 · 原查询时间':'云端查询时间'}</span><p>${esc(result.read_at || '未知')}</p></div></div>`;
  const pagination = `<div class="cloud-pagination">${cloudButton('上一页','cloud-previous',!h.previous.length)}<span>第 ${h.previous.length+1} 页</span>${cloudButton('下一页','cloud-next',result.next_cursor==null)}</div>`;
  const list = result.status === 'empty' ? `<section class="card">${empty(h.previous.length?'没有更多行程':'这一天没有云端行程','历史服务已成功返回空记录。若官方 App 有记录，请核对日期及账号。','tracks')}</section>` : `<section class="card cloud-trip-list" aria-label="云端行程列表"><div class="card-head"><h2>行程列表</h2><span class="subtle">时间均为北京时间</span></div>${trips.map((trip,index)=>`<button class="cloud-trip ${h.selected?.key===trip.key?'selected':''}" data-cloud-trip="${esc(trip.key)}" aria-label="查看行程 ${index+1}，${esc(cloudMetric(trip.distance_km,' km'))}" aria-pressed="${h.selected?.key===trip.key}"><span class="cloud-trip-index">${String(index+1).padStart(2,'0')}</span><span class="cloud-trip-time">${esc((trip.start_at||'未知').replace('（北京时间）',''))}<span class="subtle">至 ${esc((trip.end_at||'未知').replace('（北京时间）',''))}</span></span><span class="cloud-trip-distance">${esc(cloudMetric(trip.distance_km,' km'))}<span class="subtle">${esc(cloudMetric(trip.duration_minutes,' 分钟'))}</span></span>${icon('arrow')}</button>`).join('')}</section>`;
  return dateControls + note + summary + `<div class="cloud-layout ${h.selected?'has-detail':''}"><div>${list}${pagination}</div>${cloudTripDetail()}</div>`;
}
async function queryCloudHistory(direction='first') {
  syncCloudHistory();
  const h = cloudHistory;
  if (h.busy || !trackDate) return;
  let cursor = null;
  if (direction==='next') cursor=h.result?.next_cursor;
  if (direction==='previous') cursor=h.previous.at(-1);
  if (direction==='next' && cursor==null || direction==='previous' && !h.previous.length) return;
  h.busy=true; h.selected=null; h.detail=null; h.detailRequest++;
  render();
  try {
    const result=await api(`/api/history?date=${encodeURIComponent(trackDate)}${cursor==null?'':'&cursor='+encodeURIComponent(cursor)}`);
    if (cloudHistory!==h) return;
    h.result=result;
    if (['available','empty'].includes(result.status)) {
      if(direction==='next') h.previous.push(h.cursor);
      else if(direction==='previous') h.previous.pop();
      else h.previous=[];
      h.cursor=cursor;
    }
  } catch(error) {
    if(cloudHistory!==h) return;
    h.result={status:'request_failed',message:error.message};
  } finally {
    if(cloudHistory===h) { h.busy=false; if(page==='tracks' && trackSource==='cloud') render(); }
  }
}
async function loadCloudDetail() {
  const h=cloudHistory;
  if(!h?.selected || !showPosition || h.detailBusy) return;
  const version=++h.detailRequest, trip=h.selected.key;
  h.detailBusy=true; h.detail=null; render();
  try {
    const result=await api(`/api/history/points?trip=${encodeURIComponent(trip)}`);
    if(cloudHistory===h && h.detailRequest===version && showPosition) h.detail=result;
  } catch(error) {
    if(cloudHistory===h && h.detailRequest===version) h.detail={status:'request_failed',message:error.message};
  } finally {
    if(cloudHistory===h && h.detailRequest===version) {
      h.detailBusy=false;
      if(page==='tracks' && trackSource==='cloud') render();
    }
  }
}
function renderCloudMap() {
  const result=cloudHistory?.detail;
  if(!showPosition || !result || result.status!=='available' || !$('#map')) return;
  playback=(result.points || []).filter(point=>point.plottable);
  const note=`${result.count} 个轨迹点 · ${result.unplottable_count || 0} 个点无法绘制${result.truncated?' · 仅显示前 5000 个点':''}。间断分段显示，不补画路线。`;
  $('#map-status').textContent=note;
  const density=RouteQuality.analyze(result.points || [],result.segments || [],'time');
  let densityPanel=$('#cloud-route-density');
  if(!densityPanel){densityPanel=document.createElement('div');densityPanel.id='cloud-route-density';$('#map').before(densityPanel);}
  densityPanel.innerHTML=RouteQuality.summary(density);
  if(!playback.length) {
    $('#map').innerHTML=empty('坐标系未确认','已返回轨迹点，但坐标无效或未声明支持的坐标系。保留行程摘要，不强行落点。','map');
    return;
  }
  try {
    createMap([playback[0].latitude,playback[0].longitude],13,{zoomAnimation:false,fadeAnimation:false,markerZoomAnimation:false});
    density.parts.forEach(part=>{
      L.polyline(part.points.map(point=>[point.latitude,point.longitude]),RouteQuality.lineOptions(part)).addTo(map)
        .bindTooltip(part.sparse?'稀疏示意线 · 不代表实际道路':'采样点连线 · 不保证实际道路形状');
    });
    playback.forEach(point=>L.circleMarker([point.latitude,point.longitude],{radius:4,color:'#20776e',weight:1,fillOpacity:.6}).addTo(map));
    if(playback.length>1) map.fitBounds(playback.map(point=>[point.latitude,point.longitude]),{padding:[30,30],maxZoom:16,animate:false});
    $('#playback').max=String(playback.length-1); $('#playback').disabled=false;
    setPlayback(0);
  } catch(error) { $('#map').innerHTML=empty('地图暂不可用',error.message,'map'); }
}
function cloudDate(offset) {
  const date = new Date(`${trackDate}T00:00:00+08:00`);
  if(!Number.isFinite(date.getTime())) return;
  date.setUTCDate(date.getUTCDate()+offset);
  trackDate=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
  render();
}
function handleCloudAction(target) {
  if(target.dataset.cloudTrip) {
    const trip=cloudHistory?.result?.trips.find(trip=>trip.key===target.dataset.cloudTrip);
    if(trip) {
      cloudHistory.selected=trip; cloudHistory.detail=null; cloudHistory.detailBusy=false; cloudHistory.detailRequest++;
      render();
      if(showPosition) loadCloudDetail();
    }
    return true;
  }
  switch(target.dataset.action) {
    case 'cloud-query': queryCloudHistory(); return true;
    case 'cloud-next': queryCloudHistory('next'); return true;
    case 'cloud-previous': queryCloudHistory('previous'); return true;
    case 'cloud-show-route': showPosition=true; loadCloudDetail(); return true;
    case 'cloud-retry-detail': loadCloudDetail(); return true;
    case 'cloud-day-before': cloudDate(-1); return true;
    case 'cloud-day-after': cloudDate(1); return true;
    case 'cloud-today': trackDate=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); render(); return true;
    default: return false;
  }
}
