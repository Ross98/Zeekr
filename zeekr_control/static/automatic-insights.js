(function(root) {
  'use strict';
  const number = value => Number.isFinite(value) ? new Intl.NumberFormat('zh-CN', {maximumFractionDigits:2}).format(value) : '未知';
  const statuses = {waiting:'等待首次分析',ready:'最近分析已完成',partial:'部分分析暂不可用',stale:'上次结果待更新',error:'最近分析失败',changed:'记录或统计口径已变化，等待重新分析'};
  function create({getState,request,escape:esc,active,time,navigate}) {
    let node=null, owner='', data=null, error='', loading=false, serial=0;
    const context=()=>getState()?.insights_context || '';
    const valid=(token,identity)=>token===serial && owner===identity && identity===context();
    const metric=(label,value)=>`<div><span>${label}</span><strong>${value}</strong></div>`;
    function energy(report) {
      const e=report.energy;
      if(e.status==='error')return '<p>行程历史暂不可用，等待下一次分析。</p>';
      const change=e.change_percent;
      const headline=e.status!=='ready' ? '有效样本不足，暂不判断变化' : !Number.isFinite(change) ? '基线无法比较' :
        change===0 ? '两段时间的估算能耗接近' : `最近 7 天估算能耗比此前 21 天${change>0?'高':'低'} ${number(Math.abs(change))}%`;
      return `<p class="auto-conclusion">${headline}</p><div class="insight-metrics">${metric('最近 7 天 · kWh/100km',number(e.recent.kwh_per_100km))}${metric('此前 21 天 · kWh/100km',number(e.baseline.kwh_per_100km))}</div>
        <p>纳入 ${e.recent.samples} / ${e.baseline.samples} 条记录，其中片段 ${e.recent.partial_samples} / ${e.baseline.partial_samples} 条；排除 ${e.recent.excluded} / ${e.baseline.excluded} 条。</p>
        <p class="insight-note">至少 3 / 5 条才比较。纳入有效观测至少 10 公里且电量下降至少 3 个百分点的记录，含片段。按总估算电量 / 总里程计算；来自 SOC 与电池容量估算。</p>
        <p class="insight-note">行程构成、温度和路况可能不同。变化不代表车辆故障，也不能单凭此处确定原因。</p>`;
    }
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(!active() || !node?.isConnected)return;
      const focused=node.contains(document.activeElement)?document.activeElement.id:null;
      const report=data?.report;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">自动洞察</span><h2>数据积累，结论随之更新</h2><p>对照最近 7 天与此前 21 天的估算能耗。</p></div><span class="insight-source">历史观测 · 北京时间</span></section>
        <section class="card insight-panel"><div class="insight-heading"><h3 id="auto-status">${!owner?'等待当前车辆缓存':data?statuses[data.status]||'分析状态未知':'点击读取最新结论'}</h3><button class="button secondary" id="auto-reload" data-auto="reload" ${!owner||loading?'disabled':''}>读取最新结论</button></div>
        ${loading?'<p role="status">正在读取已保存结论…</p>':''}${error?`<p class="notice error" role="alert">${esc(error)}${report?' · 保留上次结果及原分析时间。':''}</p>`:''}
        ${report?`<p id="auto-generated">分析时间：${esc(time(report.generated_at))}</p><p id="auto-range">记录范围：${report.start_date} 至 ${report.end_date}，截至分析时间。最近 7 天从 ${report.recent_start_date} 起。</p>`:'<p>后台成功采集后会生成分析。有足够证据时显示结论；样本不足时保留空白。</p>'}
        ${data?.next_check_at?`<p class="insight-note">下次检查计划：${esc(time(data.next_check_at))}。后台持续采集时，约每小时更新；采集暂停或失败时，可能延后。</p>`:''}
        ${data?.status==='error'?'<p class="notice error">本次分析未完成。保留的旧结果仍按原时间显示。</p>':''}
        ${data?.status==='stale'?'<p class="insight-note">已超过更新周期；以下为上次分析结果。</p>':''}
        <p class="insight-note">点击“读取最新结论”查看已保存分析。后台继续生成结论；页面仅读取历史分析结果，不触发车辆刷新。</p></section>
        ${report?`<div class="auto-grid"><section class="card insight-panel" id="auto-energy"><h3>行驶能耗</h3>${energy(report)}</section></div>
        <section class="card insight-panel"><h3>查看相关记录</h3><div class="insight-actions"><button class="button secondary" data-auto="report">周报与月报</button><button class="button secondary" data-auto="ledger">充电账本</button><button class="button secondary" data-auto="quality">采集诊断</button></div></section>
        ${report.unreadable_events?`<p class="insight-note">另有 ${report.unreadable_events} 条历史事件无法解析或归期，不能断言这些统计覆盖全部记录。</p>`:''}`:''}`;
      if(focused)node.querySelector('#'+focused)?.focus({preventScroll:true});
    }
    async function load() {
      if(!owner||loading||!active())return;
      const token=++serial, identity=owner;
      loading=true;error='';paint();
      try {
        const result=await request('/api/insights/automatic');
        if(!valid(token,identity))return;
        if(result.context!==identity)throw Error('账号或车辆已切换，请等待页面同步。');
        data=result;
      } catch(failure) {if(valid(token,identity))error=failure.message;}
      finally {if(valid(token,identity)){loading=false;paint();}}
    }
    function mount(container) {
      const changed=owner!==context(), remount=node!==container;node=container;
      if(changed){owner=context();data=null;error='';loading=false;serial++;}
      if(changed||remount)paint();
    }
    function handle(event) {
      if(!active()||!node?.contains(event.target)||event.type!=='click')return false;
      const button=event.target.closest('[data-auto]');
      if(!button||button.disabled)return false;
      if(button.dataset.auto==='reload')load();
      else navigate({report:'insights',ledger:'energy',quality:'settings'}[button.dataset.auto],button.dataset.auto);
      return true;
    }
    return {mount,handle};
  }
  root.AutomaticInsightsPage={create};
})(window);
