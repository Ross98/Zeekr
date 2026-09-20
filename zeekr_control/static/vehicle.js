(function(root) {
  'use strict';
  const statuses = {known:'已解释',pending:'待核实',empty:'空值',invalid:'无效值',missing:'本次未返回'};
  function stateKey(state) {
    return JSON.stringify([state?.request_key,state?.field_reviews?.vehicle,state?.vehicle,state?.snapshot_revision,state?.read_time]);
  }
  function identity(state) { return JSON.stringify([state?.request_key,state?.field_reviews?.vehicle,state?.vehicle]); }
  function selectFields(data, options = {}) {
    const groups = (data?.groups || []).map(group => group.name);
    const query = (options.query || '').trim().toLowerCase();
    const fields = (data?.fields || []).filter(field =>
      (!options.group || options.group === 'all' || field.group === options.group) &&
      (!options.status || options.status === 'all' || field.status === options.status) &&
      (!query || [field.name,field.path,field.group].join(' ').toLowerCase().includes(query)))
      .sort((a,b) => Number(a.status === 'missing') - Number(b.status === 'missing') || groups.indexOf(a.group) - groups.indexOf(b.group));
    const pages = Math.max(1,Math.ceil(fields.length / 20));
    const page = Math.max(0,Math.min(pages - 1,Math.floor(options.page) || 0));
    return {fields:fields.slice(page * 20,page * 20 + 20),total:fields.length,page,pages,start:page * 20};
  }
  function create({getState,request,redraw,escape:esc,age,active}) {
    let tab = 'parameters', data = null, error = '', owner = '', attempted = '', loading = '', serial = 0;
    const filters = {query:'',group:'all',status:'all',page:0};
    function sync() {
      const next = identity(getState());
      if (next !== owner) { owner=next;data=null;error='';attempted='';loading='';serial++; }
    }
    async function ensure(force = false) {
      sync();
      if (!active() || tab !== 'parameters') return;
      const key = stateKey(getState());
      if (loading === key || (!force && attempted === key)) return;
      const token = ++serial;
      loading=key;attempted=key;error='';
      try {
        const result = await request('/api/vehicle/parameters');
        if (token !== serial || key !== stateKey(getState())) return;
        if (result.vehicle !== getState()?.vehicle || result.vehicle_key !== getState()?.field_reviews?.vehicle) {
          error='车辆缓存已切换，等待状态同步。';data=null;return;
        }
        data=result;
      } catch (failure) {
        if (token === serial && key === stateKey(getState())) error=failure.message;
      } finally {
        if (token === serial) { loading='';if(active())redraw(); }
      }
    }
    function focusSnapshot() {
      const el = document.activeElement;
      if (!el?.id?.startsWith('vehicle-')) return null;
      return {id:el.id,start:el.selectionStart,end:el.selectionEnd};
    }
    function restoreFocus(saved) {
      const el = saved && document.getElementById(saved.id);
      if (!el) return;
      if (el.disabled) {document.querySelector('.vehicle-pagination button:not(:disabled)')?.focus({preventScroll:true});return;}
      el.focus({preventScroll:true});
      if (saved.start != null && el.setSelectionRange) el.setSelectionRange(saved.start,saved.end);
    }
    function fieldRow(field) {
      const time = Number.isFinite(field.updated_time) ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(field.updated_time)) : '更新时间未知';
      return `<tr data-parameter="${esc(field.path)}"><td data-label="参数"><strong>${esc(field.name)}</strong><span class="vehicle-meta">${esc(field.group)}</span><details data-detail="parameter-${esc(field.path)}"><summary>字段说明</summary><code>${esc(field.path)}</code><p>单位：${esc(field.unit || '未提供')}</p><p>${esc(field.note)}</p><p>依据：${esc(field.basis)}</p></details></td><td data-label="当前值"><strong>${esc(field.value)}</strong></td><td data-label="原始值"><code>${esc(field.raw)}</code></td><td data-label="解释状态"><span class="vehicle-badge quality-${esc(field.status)}">${statuses[field.status] || '未知'}</span><span class="vehicle-meta">${esc(field.evidence)}</span></td><td data-label="来源时间"><span>${esc(time)}</span><span class="vehicle-meta">${age(field.updated_time)}</span><span class="vehicle-meta">${esc(field.time_source)}</span></td></tr>`;
    }
    function parametersView() {
      const counts = data?.counts;
      if (!data) return `<section class="card vehicle-empty" role="status"><h2>${error ? '参数读取失败' : '正在读取参数目录…'}</h2><p>${esc(error || '读取本机缓存与字段目录。')}</p>${error ? '<button class="button" data-vehicle="retry">重试</button>' : ''}</section>`;
      const selected = selectFields(data,filters);filters.page=selected.page;
      const changed = data.snapshot_revision !== getState()?.snapshot_revision;
      return `<section class="vehicle-catalog" aria-label="车辆全部参数">
        <div class="vehicle-intro"><div><h2>全部参数，一项不漏</h2><p>目录 ${counts.total} 项 · 本次返回 ${counts.returned} 项 · ${age(data.updated_time,'快照更新于 ')}<br>只读云端缓存；未返回不等于零，待核实不代表设备已配备。</p></div><span class="vehicle-source">本机缓存</span></div>
        ${error || changed ? `<div class="notice ${error?'error':'info'}" role="status"><p>${esc(error || '正在同步参数快照。')} · 保留上次参数快照与原时间。</p>${error?'<button class="button secondary" data-vehicle="retry">重试</button>':''}</div>` : ''}
        <div class="vehicle-counts">${Object.entries(statuses).map(([key,label])=>`<button id="vehicle-count-${key}" data-vehicle="status" data-value="${key}" aria-pressed="${filters.status===key}"><span>${label}</span><strong>${counts[key]}</strong></button>`).join('')}</div>
        <div class="card vehicle-list"><div class="vehicle-filters"><label class="vehicle-search">搜索参数<input id="vehicle-search" type="search" placeholder="中文名称 / 字段路径" value="${esc(filters.query)}"></label><label>参数分组<select id="vehicle-group"><option value="all">全部 ${data.groups.length} 组</option>${data.groups.map(group=>`<option value="${esc(group.name)}" ${filters.group===group.name?'selected':''}>${esc(group.name)} · ${group.count}</option>`).join('')}</select></label><label>解释状态<select id="vehicle-status"><option value="all">全部状态</option>${Object.entries(statuses).map(([key,label])=>`<option value="${key}" ${filters.status===key?'selected':''}>${label}</option>`).join('')}</select></label><button class="button secondary" id="vehicle-reset" data-vehicle="reset">重置筛选</button></div>
        <div class="vehicle-results" role="status">匹配 ${selected.total} 项 · 已返回优先 · 每页 20 项</div>
        ${selected.total ? `<table class="vehicle-table"><caption class="vehicle-sr">车辆参数、原值、解释依据与来源时间</caption><thead><tr><th scope="col">参数</th><th scope="col">当前值</th><th scope="col">原始值</th><th scope="col">解释状态</th><th scope="col">来源时间</th></tr></thead><tbody>${selected.fields.map(fieldRow).join('')}</tbody></table>` : '<p class="vehicle-empty">没有匹配参数。可重置筛选查看全部目录。</p>'}
        <div class="vehicle-pagination"><button class="button secondary" id="vehicle-prev" data-vehicle="prev" ${selected.page?'':'disabled'}>上一页</button><span>第 ${selected.page+1} / ${selected.pages} 页 · ${selected.total?selected.start+1:0}–${selected.start+selected.fields.length} 项</span><button class="button secondary" id="vehicle-next" data-vehicle="next" ${selected.page+1<selected.pages?'':'disabled'}>下一页</button></div></div>
        <p class="vehicle-footnote">“全部”指当前安全字段目录，已排除身份、坐标、凭据等私密字段；不是车辆全部 ECU / CAN 信号。</p>
      </section>`;
    }
    function render(overview,missing) {
      sync();
      return `<div class="vehicle-tabs" aria-label="车辆视图"><button id="vehicle-overview" data-vehicle="overview" aria-pressed="${tab==='overview'}">状态总览</button><button id="vehicle-parameters" data-vehicle="parameters" aria-pressed="${tab==='parameters'}">全部参数${data ? ' '+data.counts.total : ''}</button></div>${tab==='overview' ? overview() : missing()+parametersView()}`;
    }
    function handle(event) {
      const el = event.target;
      if (event.type === 'input' && el.id === 'vehicle-search') { filters.query=el.value;filters.page=0;redraw();return true; }
      if (event.type === 'change' && ['vehicle-group','vehicle-status'].includes(el.id)) { filters[el.id.slice(8)]=el.value;filters.page=0;redraw();return true; }
      if (event.type !== 'click') return false;
      const button = el.closest('button[data-vehicle]');
      if (!button || button.disabled) return false;
      switch (button.dataset.vehicle) {
        case 'overview': case 'parameters': tab=button.dataset.vehicle;break;
        case 'status': filters.status=filters.status===button.dataset.value?'all':button.dataset.value;filters.page=0;break;
        case 'reset': Object.assign(filters,{query:'',group:'all',status:'all',page:0});break;
        case 'prev': filters.page--;break;
        case 'next': filters.page++;break;
        case 'retry': ensure(true);return true;
        case 'locate': {
          const target=document.getElementById(button.dataset.target);
          if(target){target.scrollIntoView({block:'center',behavior:'auto'});target.focus({preventScroll:true});}
          return true;
        }
      }
      redraw();return true;
    }
    return {render,ensure,handle,focusSnapshot,restoreFocus};
  }
  const exports = {selectFields,stateKey,create};
  if (typeof module !== 'undefined' && module.exports) module.exports=exports;
  else root.VehiclePage=exports;
})(typeof window === 'undefined' ? globalThis : window);
