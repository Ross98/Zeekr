'use strict';

const icons = {
  overview: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  car: '<path d="m4 10 2-6h12l2 6M4 10h16v8H4zM2 10h20M7 18v2m10-2v2M7 13h1m8 0h1"/>',
  energy: '<path d="m13 2-8 12h6l-1 8 9-13h-7z"/>',
  map: '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2.5"/>',
  tracks: '<circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M5 7v6a3 3 0 0 0 3 3h2a3 3 0 0 0 0-6h4a5 5 0 0 1 5 5v2"/>',
  fields: '<path d="M8 4h12M8 12h12M8 20h12"/><circle cx="3" cy="4" r=".5"/><circle cx="3" cy="12" r=".5"/><circle cx="3" cy="20" r=".5"/>',
  settings: '<path d="m9 3-1 3-3 1v4l-2 1 2 2v3l3 1 1 3h5l1-3 3-1v-3l3-2-3-2V7l-3-1-1-3z"/><circle cx="11.5" cy="12" r="3"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',
  arrow: '<path d="m9 5 7 7-7 7"/>',
  battery: '<rect x="2" y="6" width="18" height="12" rx="2"/><path d="M22 10v4M5 9v6m4-6v6m4-6v6"/>',
  range: '<path d="m8 3-5 18m13-18 5 18M12 3v4m0 4v3m0 4v3"/>',
  odometer: '<path d="M4 19a10 10 0 1 1 16 0Z"/><path d="m12 13 5-5"/><circle cx="12" cy="13" r="1"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.2"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'
};
const pages = { overview: '车辆总览', car: '车辆详情', energy: '能源与充电', map: '定位地图', tracks: '轨迹记录', fields: '参数详情', settings: '设置', more: '更多' };
const descriptions = { overview: '', car: '门窗、轮胎与座舱，逐项查看。', energy: '动力电池与充电参数，清晰分开。', map: '最近返回的位置，保留可信度与时间信息。', tracks: '留住走过的路，也如实保留数据的空白。', fields: '查看中文解释、原始字段与验证状态。', settings: '管理本机连接、隐私与轨迹采集。', more: '更多车辆信息与本机设置。' };
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.info}</svg>`;
let state = null, page = 'overview', busy = false, transientError = '', showPosition = false, showCoordinates = false;
let map = null, mapMarker = null, generation = 0, toastTimer;
let trackSource = 'local', trackDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year:'numeric',month:'2-digit',day:'2-digit' }).format(new Date());
let trackData = null, playback = [], search = '', groupFilter = '', unknownOnly = false;
let archiveVehicle = '';
let connectionFailures = 0, polling = false;
let refreshMessage = '';
const refreshMessages = {cached:'已复用本机缓存，未请求云端。',unchanged:'已读取云端，车辆数据未更新。',new:'已获得新车辆数据。',time_unknown:'已读取云端，车辆更新时间未知。'};

function navigation() {
  $('#navigation').innerHTML = Object.entries(pages).filter(([key]) => key !== 'more').map(([key, label]) => `<button class="nav-item ${page === key ? 'active' : ''}" data-page="${key}" ${page === key ? 'aria-current="page"' : ''}>${icon(key)}${label}</button>`).join('');
  $('#mobile-navigation').innerHTML = ['overview','car','map','tracks','more'].map(key => `<button data-page="${key}" class="${page === key || (key === 'more' && ['energy','fields','settings'].includes(page)) ? 'active' : ''}" aria-label="${pages[key]}">${icon(key)}<span>${{overview:'总览',car:'车辆',map:'地图',tracks:'轨迹',more:'更多'}[key]}</span></button>`).join('');
}

async function api(path, data, timeout = 50000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const options = data === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-Request-Key':state?.request_key || ''},body:JSON.stringify(data)};
    const response = await fetch(path, {...options,signal:controller.signal});
    let value;
    try { value = await response.json(); } catch { throw Error('本机服务响应无效，请重试。'); }
    if (!response.ok) throw Error(value.error || '请求失败，请稍后重试。');
    return value;
  } catch(error) {
    if(error.name==='AbortError') throw Error('本机服务响应超时，请稍后重试。');
    throw error;
  } finally { clearTimeout(timer); }
}

function relativeTime(value) {
  if (!Number.isFinite(value)) return '更新时间未知';
  const seconds = Math.floor((Date.now()-value)/1000);
  if(seconds < -60) return '时间异常，请核对时钟';
  if(seconds < 60) return '不足 1 分钟前';
  if(seconds < 3600) return `${Math.floor(seconds/60)} 分钟前`;
  if(seconds < 86400) return `${Math.floor(seconds/3600)} 小时 ${Math.floor(seconds%3600/60)} 分钟前`;
  return `${Math.floor(seconds/86400)} 天前`;
}
function age(value, prefix = '') {
  return `<span data-age="${Number.isFinite(value)?value:''}" data-prefix="${esc(prefix)}">${esc(prefix+relativeTime(value))}</span>`;
}
function waitSeconds() { return Math.max(0,Math.ceil((state?.next_query_at || 0)-Date.now()/1000)); }
function updateClock() {
  document.querySelectorAll('[data-age]').forEach(el => {
    const value=el.dataset.age===''?null:Number(el.dataset.age);
    el.textContent=el.dataset.prefix+relativeTime(value);
  });
  const button = document.querySelector('[data-action="refresh"]');
  const remaining=waitSeconds();
  if(button) {
    button.disabled=busy || remaining>0;
    button.innerHTML=`${icon('refresh')}${busy?'读取中…':remaining?`等待 ${remaining} 秒`:'刷新状态'}`;
  }
  if($('#refresh-hint')) $('#refresh-hint').textContent=remaining?`${remaining} 秒后可再次请求云端`:'读取云端缓存，车辆可能尚未更新';
}
function updateConnection() {
  const disconnected=connectionFailures>=2;
  $('#connectivity-notice').hidden=!disconnected;
  $('#local-connection').textContent=disconnected?'本机服务已断开':connectionFailures?'正在重连…':'本机服务已连接';
  $('#connection').textContent=disconnected?'本机服务已断开':state?.error?'车辆读取需检查':state?.authenticated?'本机会话已保存':'尚未登录';
  $('#local-connection').classList.toggle('unknown',disconnected);
}

function toast(message) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500);
}

function pill(value, kind = '', symbol = '') { return `<span class="pill ${kind}">${symbol ? icon(symbol) : ''}${esc(value)}</span>`; }
function row(name, value) { return `<div class="inline-row"><span>${esc(name)}</span><strong>${esc(value)}</strong></div>`; }
function action(label, name, kind = '', symbol = '') { return `<button class="button ${kind}" data-action="${name}" ${busy ? 'disabled' : ''}>${symbol ? icon(symbol) : ''}${esc(label)}</button>`; }
function link(label, target) { return `<button class="text-link" data-page="${target}">${esc(label)}${icon('arrow')}</button>`; }
function empty(title, text, symbol = 'info') { return `<div class="empty">${icon(symbol)}<h2>${esc(title)}</h2><p>${esc(text)}</p></div>`; }
function head() {
  return `<div class="page-head"><div><div class="eyebrow">MY ZEEKR / ${new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit'}).format(new Date())}</div><h1>${pages[page]}</h1><div class="subtle">${descriptions[page]}</div></div><div class="page-actions">${state?.vehicles?.length > 1 ? `<select id="vehicle-select" class="select" aria-label="选择车辆" ${state.recording.active ? 'disabled' : ''}>${state.vehicles.map(v => `<option value="${v.number}" ${v.number === state.vehicle ? 'selected' : ''}>${esc(v.label)}</option>`).join('')}</select>` : ''}<div class="refresh-control">${action(busy ? '读取中…' : '刷新状态','refresh','','refresh')}<span id="refresh-hint" class="subtle"></span></div></div></div>`;
}

function modelRequired() {
  if (state?.model) return '';
  const logged = state?.authenticated;
  return `<div class="card">${empty(logged ? '尚未读取车辆状态' : '连接你的极氪', logged ? '本机会话已就绪。点击“刷新状态”，读取车辆云端缓存。' : '先在本机终端完成登录，再返回页面刷新。手机号、验证码与凭据不进入页面。', 'car')}${!logged ? '<div class="empty" style="padding-top:0"><code>python3 -m zeekr_control login</code></div>' : ''}</div>`;
}

function metric(label, value, symbol, foot, battery = false) {
  if (value && typeof value==='object') {
    value=Number.isFinite(value.value)?`${new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3}).format(value.value)}${value.unit==='%'?'%':` ${value.unit}`}`:'未知';
  }
  const parts = value.match(/^(.*?)(%| km)$/);
  const num = parts ? parts[1] : value;
  const unit = parts ? parts[2].trim() : '';
  const percent = battery && value.endsWith('%') ? Math.max(0, Math.min(100, parseFloat(value))) : 0;
  return `<div class="metric"><div class="metric-label">${icon(symbol)}${label}</div><div class="metric-value">${esc(num)}${unit ? `<span class="metric-unit">${unit}</span>` : ''}</div>${battery && value.endsWith('%') ? `<div class="battery-track"><div class="battery-fill" style="width:${percent}%"></div></div>` : ''}<div class="metric-foot">${esc(foot)}</div></div>`;
}

function tyres(compact = false) {
  return `<div class="tyre-grid">${state.model.tyres.map(t => `<div class="tyre-item"><span class="tyre-name">${esc(t.name)}</span><div><span class="tyre-value">${esc(compact && Number.isFinite(t.pressure_value)?`${t.pressure_value.toFixed(1)} kPa`:t.pressure)}</span><span class="tyre-temp">${esc(t.temperature)}</span></div></div>`).join('')}</div>`;
}

function overview() {
  if (!state?.model) return modelRequired();
  const m = state.model, profile=state.profile || {name:'我的车辆',variant:'',image:''};
  const closure=m.closure || {doors:'未知',windows:'未知',trunk:'未知'};
  const recording=state.recording;
  const recordingLabel={never:'尚未开启',paused:'已暂停',active:'正在记录',failed:'采集失败'}[recording.status] || (recording.active?'正在记录':'已暂停');
  return `<section class="hero"><div class="hero-copy"><div class="hero-title">${esc(profile.name)}</div><div class="hero-sub">${esc(profile.variant)}</div><div class="hero-state">${pill(m.lock.confirmed?m.lock.value:'锁车状态未知',m.lock.confirmed?'good':'warn',m.lock.confirmed?'lock':'info')}${pill(m.charging.confirmed?m.charging.value:'充电状态未知',m.charging.confirmed?'':'warn','energy')}</div><div class="freshness">${icon('clock')}<div>${age(m.updated_time,'车辆数据更新于 ')}<span class="subtle">云端缓存 · 不代表实时状态</span></div></div><button class="closure-summary" data-page="car" aria-label="查看门窗详情">${[['doors','车门'],['windows','车窗'],['trunk','尾门']].map(([key,label])=>`<span class="${closure[key]==='未知'?'unknown':''}">${label}${esc(closure[key])}</span>`).join('')}${icon('arrow')}</button></div><div class="hero-car">${profile.image?`<img src="${esc(profile.image)}" alt="${esc(profile.image_alt)}">`:icon('car')}</div></section>
  <section class="metric-grid overview-metrics">${metric('动力电池',m.metric_details?.battery || m.metrics.battery,'battery','',true)}${metric('预估续航',m.metric_details?.range || m.metrics.range,'range','以车辆实际表现为准')}</section>
  <div class="overview-secondary"><span>累计里程 <strong>${esc(m.metrics.odometer)}</strong></span><details class="data-explanation"><summary>数据说明与完整时间</summary><div class="explanation-content"><p>动力电池使用动力电池专用字段，与低压电池分开。续航是车辆返回的估计。</p><p>胎压轮位及单位已核对；总览四舍五入至一位小数，车辆详情保留接口精度。未设置未经核对的胎压报警阈值。</p><p>门窗及锁车仅解释本车已验证的组合；未知不代表正常，也不代表异常。车型图片仅供参考。</p>${row('车辆状态时间',m.updated_at)}${row('温度状态时间',m.temperature_updated_at)}${row('最近云端读取',state.read_at)}</div></details></div>
  <div class="grid-two"><section class="card"><div class="card-head"><h2>座舱与环境</h2>${link('车辆详情','car')}</div><div class="card-body"><div class="temperature"><div><div class="small-label">车内温度</div><div class="temp-value">${esc(m.metrics.inside)}</div></div><div><div class="small-label">车外温度</div><div class="temp-value">${esc(m.metrics.outside)}</div></div></div><div class="divider"></div><div class="subtle">${age(m.temperature_updated_time,'温度更新于 ')} · 与整车状态可能不同步</div></div></section>
  <section class="card"><div class="card-head"><h2>轮胎状态</h2>${link('查看详情','car')}</div><div class="card-body">${tyres(true)}</div></section></div>
  <div class="grid-two grid-equal overview-links"><section class="card"><div class="card-head"><h2>最近位置</h2>${link('打开地图','map')}</div><div class="card-body"><div class="location-preview">${icon('map')}<span>${showPosition?'位置显示已开启 · 前往地图查看':'位置默认隐藏 · 按需打开地图'}</span></div></div></section><section class="card"><div class="card-head"><h2>行程记录</h2>${link('查看轨迹','tracks')}</div><div class="card-body">${row('本地采集',recordingLabel)}${row('最近新增观测',recording.last_new==='未知'?'暂无记录':recording.last_new)}${recording.error?`<p class="unknown">${esc(recording.error)}</p>`:''}<div class="subtle">仅记录采集开启期间的数据 · ${link('管理采集','settings')}</div></div></section></div>`;
}

function table(fields, paths = false) {
  if (!fields.length) return empty('暂无对应参数','接口尚未返回这一组字段；不以零值填充。');
  return `<div class="table-wrap"><table class="fields"><thead><tr><th>参数</th><th>当前值 / 原值</th><th>解释依据</th></tr></thead><tbody>${fields.map(f => `<tr><td>${esc(f.name)}${paths ? `<span class="field-path">${esc(f.path)}</span>` : ''}</td><td><span class="field-value">${esc(f.value)}</span>${f.evidence === '待核实' ? '<span class="field-path">原始值，含义待核对</span>' : ''}</td><td>${pill(f.evidence,f.evidence==='待核实'||f.evidence==='未知'?'warn':'')}</td></tr>`).join('')}</tbody></table></div>`;
}

function car() {
  if (!state?.model) return modelRequired();
  const m = state.model;
  return `<div class="grid-two"><section class="card"><div class="card-head"><h2>门锁、车门与车窗</h2>${pill('按本车已核对组合解释')}</div><div class="card-body"><div class="door-grid">${m.doors.map(d => `<div class="door-card"><h3>${esc(d.name)}</h3>${['door','lock','window'].map((key,i) => `<div class="inline-row"><span>${['车门','门锁','车窗'][i]}</span><span class="${d[key]==='未知'?'unknown':'known'}">${esc(d[key])}<span class="raw">原值 ${esc(d.raw[key])}</span></span></div>`).join('')}</div>`).join('')}</div><div class="section-gap">${row('中控锁组合',m.lock.value)}${row('尾门开闭',m.trunk)}${row('前舱盖',m.hood)}</div></div></section><section class="card"><div class="card-head"><h2>四轮胎压与胎温</h2></div><div class="card-body">${tyres()}<div class="divider section-gap"></div><p class="subtle">保留接口小数；轮位按左舵车辆显示。未设置未经核对的胎压报警阈值。</p><div class="temperature"><div><div class="small-label">车内</div><div class="temp-value">${esc(m.metrics.inside)}</div></div><div><div class="small-label">车外</div><div class="temp-value">${esc(m.metrics.outside)}</div></div></div><div class="subtle">温度更新 ${esc(m.temperature_updated_at)}</div></div></section></div>
  <section class="card"><div class="card-head"><h2>空调、座椅与空气质量</h2>${link('全部参数','fields')}</div><div class="card-meta">未核实枚举保留原值；通用字段不代表本车配备或正在运行该硬件。</div>${table(m.fields.filter(f => ['空调与舒适','空气质量'].includes(f.group)),true)}</section>`;
}

function energy() {
  if (!state?.model) return modelRequired();
  const m = state.model;
  return `<div class="metric-grid">${metric('动力电池',m.metrics.battery,'battery','不使用低压电池电量',true)}${metric('电池续航',m.metrics.range,'range','电动车专用续航字段')}${metric('充电组合',m.charging.value,'energy','仅匹配已核对状态时解释')}</div><div class="notice info">${icon('info')}充电状态、充电器状态、连接状态分别展示。“未充电”不等于“未插枪”。</div><div class="grid-two grid-equal"><section class="card"><div class="card-head"><h2>充电与放电</h2>${pill('缓存参数')}</div>${table(m.fields.filter(f => f.group==='能源与充电' && !['chargeLevel','distanceToEmptyOnBatteryOnly'].includes(f.key)),true)}</section><section class="card"><div class="card-head"><h2>低压电池</h2>${pill('独立于动力电池')}</div><div class="card-meta">健康字段不用于判断动力电池健康；电气字段单位仍需实车核对。</div>${table(m.fields.filter(f => f.group==='低压电池'),true)}</section></div>`;
}

function privacyGate(track = false) {
  return `<div class="map-empty">${icon(track?'tracks':'map')}<h2>${track?'按日期回看采样轨迹':'让位置，只在需要时出现'}</h2><p>显示位置后将加载 OpenStreetMap 底图，底图服务会收到对应区域的瓦片请求。经纬度文本默认隐藏。</p>${action('显示位置并加载地图','show-position')}<p class="subtle">随时可隐藏位置 · 不主动唤醒车辆</p></div>`;
}

function mapPage() {
  if (!state?.model) return modelRequired();
  if (!showPosition) return `<section class="card">${privacyGate()}</section>`;
  return `<div class="filters">${action('隐藏位置','hide-position','secondary')}${action('回到最近位置','recenter','secondary')}</div><div class="map-layout"><section class="card map-card"><div id="map" class="map-canvas" aria-label="车辆位置地图"></div><div id="map-status" class="map-status" role="status">正在读取最近位置…</div></section><section class="card"><div class="card-head"><h2>定位信息</h2></div><div class="map-meta" id="location-info"><div class="subtle">正在读取…</div></div></section></div>`;
}

function tracksPage() {
  const archives = state?.archived_vehicles || [];
  const toolbar = `<div class="track-toolbar"><div class="tabs" aria-label="轨迹来源"><button class="tab ${trackSource==='local'?'active':''}" data-source="local">本地记录</button><button class="tab ${trackSource==='cloud'?'active':''}" data-source="cloud">云端历史</button></div><label><span class="subtle">北京时间 </span><input type="date" id="track-date" aria-label="轨迹日期" value="${esc(trackDate)}"></label></div>`;
  if (trackSource === 'cloud') return toolbar + `<section class="card">${empty('云端历史尚未接入',state?.history?.detail || '历史轨迹接口尚未验证。','tracks')}<div class="card-meta">日期已保留，接口接入后用于查询；当前状态不代表没有行程。</div></section>`;
  const note = `<div class="notice info">${icon('info')}本地记录仅覆盖采集开启期间。重复缓存不新增定位，不可信点和较长间断不会连接。</div>`;
  if (!state?.model && !archives.length) return toolbar + note + modelRequired();
  if (!showPosition) return toolbar + note + `<section class="card">${privacyGate(true)}</section>`;
  const selector = archives.length ? `<select id="archive-vehicle" class="select" aria-label="已记录车辆"><option value="">${state.model?'当前车辆':'首辆本地车辆'}</option>${archives.map(v=>`<option value="${esc(v.key)}" ${v.key===archiveVehicle?'selected':''}>${esc(v.label)}</option>`).join('')}</select>` : '';
  return toolbar + note + `<div class="filters">${selector}${action('隐藏位置','hide-position','secondary')}${action('重新查询','reload-tracks','secondary','refresh')}${link('管理采集','settings')}</div><div id="track-content"><section class="card">${empty('正在读取记录','正在查询所选日期。','tracks')}</section></div>`;
}

function fieldsPage() {
  if (!state?.model) return modelRequired();
  const groups = [...new Set(state.model.fields.map(f => f.group))];
  return `<div class="filters"><input type="search" id="search" aria-label="搜索参数" placeholder="搜索中文名称或字段，如：胎压、chargeLevel" value="${esc(search)}"><select class="select" id="group" aria-label="参数分类"><option value="">全部分类</option>${groups.map(g => `<option ${groupFilter===g?'selected':''}>${esc(g)}</option>`).join('')}</select><label class="check"><input type="checkbox" id="unknown" ${unknownOnly?'checked':''}>仅待核实 / 未知</label></div><p class="section-note">这些是读取参数，不是控制开关。缺失值显示未知，未核实枚举保留原值；身份信息与位置字段不在此页展示。</p><section class="card" id="field-results"></section>`;
}

function renderFields() {
  if (!$('#field-results')) return;
  const items = state.model.fields.filter(f => (!groupFilter||f.group===groupFilter) && (!unknownOnly||['未知','待核实'].includes(f.evidence)) && `${f.name} ${f.path}`.toLowerCase().includes(search.toLowerCase()));
  $('#field-results').innerHTML = `<div class="card-head"><h2>车辆参数</h2><span class="subtle">${items.length} 项</span></div>${table(items,true)}`;
}

function settings() {
  const recording = state?.recording || {active:false,interval:300,last_sample:'未知',last_new:'未知'};
  return `<section class="card"><div class="card-head"><h2>连接与隐私</h2>${pill('仅本机访问')}</div><div class="card-body"><div class="settings-row"><div><h3>账号会话</h3><p>${state?.authenticated?'已发现本机会话；可用性以最近一次车辆读取结果为准。':'尚未登录。请在终端运行 python3 -m zeekr_control login。'}</p></div>${pill(state?.authenticated?'会话已保存':'未登录',state?.authenticated?'':'warn')}</div><div class="settings-row"><div><h3>位置显示</h3><p>地图及轨迹共用开关。隐藏后清除当前页面的地图与坐标；不会删除已有本地记录或停止采集。</p></div>${action(showPosition?'隐藏位置':'显示位置并加载地图',showPosition?'hide-position':'show-position','secondary')}</div></div></section>
  <section class="card section-gap"><div class="card-head"><h2>本地轨迹采集</h2>${pill(recording.active?'采集中':'已暂停',recording.active?'good':'')}</div><div class="card-body"><div class="notice info">${icon('info')}开启后保存当前缓存并定期读取。浏览器关闭不停止后端；Mac 休眠、断网或服务退出期间无法采集。读取失败会暂停，需手动恢复。</div><div class="settings-row"><div><h3>采样间隔</h3><p>默认 300 秒，可设 60–3600 秒。仅控制请求频率，不保证车辆位置按此频率更新。</p></div><div class="settings-control"><label><input type="number" id="interval" aria-label="采样间隔（秒）" min="60" max="3600" step="1" value="${recording.interval}" ${recording.active?'disabled':''}> 秒</label>${action(recording.active?'暂停采集':'开始采集','recording',recording.active?'secondary':'')}</div></div>${row('最近采样检查',recording.last_sample)}${row('最近新增观测',recording.last_new)}${row('轨迹数据库大小',`${((state?.storage_bytes||0)/1024).toFixed(1)} KB`)}<div class="subtle">保存在本机应用数据目录 ZeekrControl/tracks.sqlite3；默认不自动删除历史记录。</div></div></section><section class="card section-gap"><div class="card-head"><h2>关于数据</h2></div><div class="card-body"><p class="subtle">界面依据已核对的字段规则解释车辆数据。社区接口可能变化；字段存在不代表硬件可用，更不代表远程控制已接入。</p>${row('历史轨迹接口','尚未接入')}${row('后端监听','127.0.0.1 · 仅本机')}${row('数据来源','GW2 云端缓存')}</div></section>`;
}

function more() { return `<div class="more-grid">${['energy','fields','settings'].map(key => `<button data-page="${key}">${icon(key)}${pages[key]}${icon('arrow')}</button>`).join('')}</div>`; }

function render() {
  generation++;
  if (map) { map.remove(); map = null; mapMarker = null; }
  navigation();
  $('#main').dataset.page=page;
  updateConnection();
  $('.breadcrumb').textContent = `我的车库 / ${state?.profile?.name || '我的车辆'}`;
  const error = transientError || state?.error;
  const body = {overview,car,energy,map:mapPage,tracks:tracksPage,fields:fieldsPage,settings,more}[page]();
  $('#main').innerHTML = head() + (error ? `<div class="notice error" role="alert">${icon('info')}<p>${esc(error)}${state?.model?' · 下方保留上次读取的数据与原时间。':''}</p></div>` : '') + (page==='overview' && refreshMessage?`<div class="refresh-result" role="status">${esc(refreshMessage)}</div>`:'') + body + (state?.model ? `<div class="status-footer">本次读取 ${esc(state.read_at)} · 车辆状态更新 ${esc(state.model.updated_at)}</div>` : '');
  updateClock();
  if (page === 'fields') renderFields();
  if (page === 'map' && showPosition && state?.model) loadLocation(generation);
  if (page === 'tracks' && trackSource === 'local' && showPosition && (state?.model || state?.archived_vehicles?.length)) loadTracks(generation);
}

function createMap(center, zoom = 14) {
  if (!window.L) throw Error('地图组件无法加载，请重启本机服务。');
  map = L.map('map', { attributionControl:true, scrollWheelZoom:false }).setView(center,zoom);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { minZoom:2,maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors' })
    .on('tileerror', () => { if ($('#map-status')) $('#map-status').textContent = '部分底图未加载，可稍后重试；位置标记仅依据已返回数据。'; }).addTo(map);
  return map;
}

async function loadLocation(version) {
  try {
    const location = await api('/api/location');
    if (generation !== version || !showPosition) return;
    $('#location-info').innerHTML = `${row('位置可信度',location.trusted?'接口标记可信':'位置未确认')}${row('整车缓存更新时间',location.updated_at)}${row('本次读取时间',location.read_at)}${row('GPS 采集时间','定位采集时间未提供')}${row('坐标系',location.coordinate_system)}<p class="subtle">${esc(location.transform)}。不以速度 0 判断停车。</p>${action(showCoordinates?'隐藏经纬度':'显示经纬度','coordinates','quiet')}${showCoordinates ? row('经纬度',location.valid?`${location.latitude.toFixed(6)}, ${location.longitude.toFixed(6)}`:'未知') : ''}`;
    if (!location.plottable) {
      $('#map').innerHTML = empty(location.valid?'坐标系尚未适配':'暂无有效位置',location.valid?'当前坐标系未核验与底图转换，暂不落点。':'接口未返回有效经纬度，不使用零点或演示位置代替。','map');
      $('#map-status').textContent = '未绘制位置';
      return;
    }
    createMap([location.latitude,location.longitude]);
    mapMarker = L.circleMarker([location.latitude,location.longitude],{radius:10,color:location.trusted?'#20776e':'#7e898a',weight:3,fillOpacity:.3}).addTo(map);
    mapMarker.bindTooltip(location.trusted?'接口标记可信 · 坐标对齐待核验':'位置未确认 · 候选位置');
    $('#map-status').textContent = location.trusted?'接口标记可信；缓存位置，坐标对齐待核验。':'灰色候选位置：本次可信标记为 false 或缺失，不代表已确认当前位置。';
  } catch (error) {
    if (generation !== version) return;
    $('#map').innerHTML = empty('位置读取失败',error.message,'map');
    $('#map-status').textContent = '位置不可用';
  }
}

async function loadTracks(version) {
  try {
    const result = await api(`/api/tracks?date=${encodeURIComponent(trackDate)}${archiveVehicle?'&vehicle='+encodeURIComponent(archiveVehicle):''}`);
    if (generation !== version || !showPosition) return;
    trackData = result;
    playback = result.observations.filter(point => point.plottable);
    if (!result.count) {
      $('#track-content').innerHTML = `<section class="card">${empty('这一天还没有本地记录',state.recording.active?'采集正在运行，新的缓存观测将在此显示。':'开启采集后，新的位置观测将保存在本机。此前未采集的路段无法补回。','tracks')}<div class="card-meta">${link('前往采集设置','settings')}</div></section>`;
      return;
    }
    $('#track-content').innerHTML = `<div class="map-layout"><section class="card"><div id="map" class="map-canvas" aria-label="本地采样轨迹地图"></div><div id="map-status" class="map-status">${result.count} 条观测 · ${result.segments.length} 个可信片段 · ${result.truncated?'仅显示前 5000 条，请缩小范围':'时间以缓存状态时间为准，缺失时使用本机观测时间'}</div><div class="track-timeline"><div id="playback-label" class="subtle">拖动滑块逐点回看</div><input id="playback" type="range" aria-label="轨迹回看位置" min="0" max="${Math.max(0,playback.length-1)}" value="0" ${playback.length?'':'disabled'}></div></section><section class="card"><div class="card-head"><h2>采样时间线</h2>${pill('本地记录')}</div><div class="point-list">${result.observations.map(point=>`<div class="point"><span>${esc(point.time_label.replace('（北京时间）',''))}<span class="field-path">${esc(point.time_source)}</span></span>${pill(point.trusted?'接口标记可信':'位置未确认',point.trusted?'':'warn')}</div>`).join('')}</div></section></div>`;
    if (!playback.length) { $('#map').innerHTML = empty('没有可绘制的位置','观测已保存，但坐标无效或坐标系尚未适配。','map'); return; }
    createMap([playback[0].latitude,playback[0].longitude],13);
    result.segments.forEach(segment => {
      if (segment.length>1) L.polyline(segment.map(p=>[p.latitude,p.longitude]),{color:'#20776e',weight:4}).addTo(map);
    });
    playback.forEach(point => L.circleMarker([point.latitude,point.longitude],{radius:4,color:point.trusted?'#20776e':'#9aa4a2',fillOpacity:.7,weight:1}).addTo(map));
    if (playback.length>1) map.fitBounds(playback.map(p=>[p.latitude,p.longitude]),{padding:[30,30],maxZoom:16});
    setPlayback(0);
  } catch (error) {
    if (generation === version) $('#track-content').innerHTML = `<section class="card">${empty('记录读取失败',error.message,'tracks')}</section>`;
  }
}

function setPlayback(index) {
  const point = playback[index];
  if (!point || !map) return;
  if (mapMarker) mapMarker.remove();
  mapMarker = L.circleMarker([point.latitude,point.longitude],{radius:9,color:point.trusted?'#20776e':'#8a9391',fillOpacity:.35,weight:3}).addTo(map);
  map.panTo([point.latitude,point.longitude]);
  $('#playback-label').textContent = `${index+1} / ${playback.length} · ${point.time_label} · ${point.time_source} · ${point.trusted?'接口标记可信':'位置未确认'}`;
}

async function refresh() {
  if (busy || waitSeconds()>0) return;
  const selected = Number($('#vehicle-select')?.value || state?.vehicle || 1);
  busy = true; transientError = ''; render();
  try {
    state = await api('/api/refresh',{vehicle:selected});
    connectionFailures=0;
    refreshMessage=refreshMessages[state.refresh_result] || '已读取云端缓存。';
    toast(refreshMessage);
  } catch (error) {
    transientError = error.message;
    try { state = await api('/api/state',undefined,8000); connectionFailures=0; } catch { connectionFailures=2; }
    refreshMessage='';
  } finally { busy = false; render(); }
}

async function toggleRecording() {
  if (busy) return;
  const interval = Number($('#interval')?.value || state.recording.interval);
  if (!Number.isInteger(interval) || interval<60 || interval>3600) { toast('采样间隔须为 60–3600 秒的整数。'); return; }
  busy=true;
  try {
    state = await api('/api/recording',{active:!state.recording.active,interval});
    transientError='';
    toast(state.recording.active?'采集已开启，后端运行期间持续记录。':'采集已暂停，已有记录保留。');
  } catch(error) { transientError=error.message; }
  finally { busy=false;render(); }
}

document.addEventListener('click', event => {
  const target = event.target.closest('button');
  if (!target || target.disabled) return;
  if (target.dataset.page) { page=target.dataset.page; render(); window.scrollTo(0,0); return; }
  if (target.dataset.source) { trackSource=target.dataset.source; render(); return; }
  switch(target.dataset.action) {
    case 'refresh': refresh(); break;
    case 'reconnect': pollState(true); break;
    case 'show-position': showPosition=true;render();break;
    case 'hide-position': showPosition=false;showCoordinates=false;trackData=null;playback=[];render();break;
    case 'coordinates': showCoordinates=!showCoordinates;render();break;
    case 'recenter': if(map && mapMarker) map.setView(mapMarker.getLatLng(),15);break;
    case 'reload-tracks': render();break;
    case 'recording': toggleRecording();break;
  }
});
document.addEventListener('input', event => {
  if(event.target.id==='search') {search=event.target.value;renderFields();}
  if(event.target.id==='playback') setPlayback(Number(event.target.value));
});
document.addEventListener('change', event => {
  if(event.target.id==='group') {groupFilter=event.target.value;renderFields();}
  if(event.target.id==='unknown') {unknownOnly=event.target.checked;renderFields();}
  if(event.target.id==='track-date') {trackDate=event.target.value;render();}
  if(event.target.id==='archive-vehicle') {archiveVehicle=event.target.value;render();}
  if(event.target.id==='vehicle-select') refresh();
});

async function pollState(force = false) {
  if(polling || busy || (!force && document.hidden)) return;
  polling=true;
  try {
    const latest=await api('/api/state',undefined,8000);
    const changed=!state || latest.read_time!==state.read_time || latest.error!==state.error ||
      latest.recording.status!==state.recording.status || latest.recording.last_new!==state.recording.last_new ||
      latest.recording.last_sample!==state.recording.last_sample || latest.next_query_at!==state.next_query_at ||
      latest.request_key!==state.request_key;
    const restarted=state && latest.request_key!==state.request_key;
    state=latest; connectionFailures=0;
    if(restarted) { transientError='';refreshMessage=''; }
    if(changed) render();
    else { updateConnection();updateClock(); }
  } catch(error) {
    connectionFailures=state?connectionFailures+1:2;
    updateConnection();
    if(!state) $('#main').innerHTML=`<section class="card">${empty('本机服务未连接','检查本机服务后点击上方“重新连接”。')}</section>`;
  } finally {polling=false;}
}
pollState(true);
setInterval(pollState,5000);
setInterval(updateClock,1000);
