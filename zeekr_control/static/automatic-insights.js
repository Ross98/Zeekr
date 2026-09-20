(function(root) {
  'use strict';
  const number = value => Number.isFinite(value) ? new Intl.NumberFormat('zh-CN', {maximumFractionDigits:2}).format(value) : '未知';
  const statuses = {waiting:'等待首次分析',ready:'最近分析已完成',partial:'部分分析暂不可用',stale:'上次结果待更新',error:'最近分析失败',changed:'记录已变化，等待重新分析'};
  function create({getState,request,escape:esc,active,time}) {
    let node=null, owner='', data=null, error='', loading=false, serial=0, nextRead=0;
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
        <p>纳入 ${e.recent.samples} / ${e.baseline.samples} 趟；排除 ${e.recent.excluded} / ${e.baseline.excluded} 趟。</p>
        <p class="insight-note">至少 3 / 5 趟才比较。只纳入完整、至少 10 公里且电量下降至少 3 个百分点的行程。按总估算电量 / 总里程计算；来自 SOC 与电池容量估算。</p>
        <p class="insight-note">行程构成、温度和路况可能不同。变化不代表车辆故障，也不能单凭此处确定原因。</p>`;
    }
    function charging(report) {
      const c=report.charging;
      if(c.status==='error')return '<p>充电历史暂不可用，等待下一次分析。</p>';
      return `<p class="insight-note">${report.start_date} 至 ${report.end_date}，按充电类型分组。各组至少 5 次才展示电量分布。</p>${Object.entries(c.groups).map(([mode,g])=>
        `<article class="auto-charge-group"><h4>${{ac:'交流充电',dc:'直流充电',unknown:'类型未知'}[mode]} · ${g.samples} 次</h4>${g.status==='ready'?
          `<p>开始电量中位数 <strong>${number(g.start_soc.median)}%</strong>，结束电量中位数 <strong>${number(g.end_soc.median)}%</strong>。</p><p class="insight-note">中间 50% 样本：开始 ${number(g.start_soc.p25)}–${number(g.start_soc.p75)}%，结束 ${number(g.end_soc.p25)}–${number(g.end_soc.p75)}%。</p>`:
          '<p class="insight-note">有效样本不足，继续积累。</p>'}</article>`).join('')}
        <p class="insight-note">排除 ${c.excluded} 次不完整或无法验证的记录。只描述历史习惯，不作为充电目标或电池健康判断。</p>`;
    }
    function quality(report) {
      const q=report.quality;
      if(q.status==='error')return '<p>采集时间记录暂不可用，等待下一次分析。</p>';
      return `<p class="auto-conclusion">${q.reads?'最近 7 天，读取覆盖 '+q.read_slots+' / '+q.elapsed_slots+' 个半小时时段':'最近 7 天没有归档读取'}</p>
        <div class="insight-metrics">${metric('归档读取',q.reads+' 次')}${metric('有效时间推进',q.counts.new+' 次')}${metric('重复缓存',q.counts.repeat+' 次')}${metric('陈旧或异常',q.counts.invalid+' 次')}</div>
        <p>同时间修订 ${q.counts.revision} 次；有有效时间推进的时段 ${q.new_slots} / ${q.elapsed_slots}。</p>
        <p>范围内最后归档读取：${esc(time(q.last_read_at))}。</p>
        <p>车辆时间到云端读取时间差：中位数 ${number(q.p50_seconds)} 秒，95% 分位数 ${number(q.p95_seconds)} 秒。</p>
        <p class="insight-note">时段命中不等于持续在线。重复缓存不代表新车况；未读到数据不代表车辆离线。时间差包含陈旧读取，不是网络耗时。</p>`;
    }
    function paint() {
      if(!active() || !node?.isConnected)return;
      const focused=node.contains(document.activeElement)?document.activeElement.id:null;
      const report=data?.report;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">自动洞察</span><h2>数据积累，结论随之更新</h2><p>能耗、充电习惯、采集质量，定期汇总已有记录。</p></div><span class="insight-source">历史观测 · 北京时间</span></section>
        <section class="card insight-panel"><div class="insight-heading"><h3 id="auto-status">${!owner?'等待当前车辆缓存':data?statuses[data.status]||'分析状态未知':'正在读取分析状态'}</h3><button class="button secondary" id="auto-reload" data-auto="reload" ${!owner||loading?'disabled':''}>读取最新结论</button></div>
        ${loading?'<p role="status">正在读取已保存结论…</p>':''}${error?`<p class="notice error" role="alert">${esc(error)}${report?' · 保留上次结果及原分析时间。':''}</p>`:''}
        ${report?`<p id="auto-generated">分析时间：${esc(time(report.generated_at))}</p><p id="auto-range">记录范围：${report.start_date} 至 ${report.end_date}，截至分析时间。最近 7 天从 ${report.recent_start_date} 起。</p>`:'<p>后台成功采集后会生成分析。有足够证据时显示结论；样本不足时保留空白。</p>'}
        ${data?.next_check_at?`<p class="insight-note">下次检查计划：${esc(time(data.next_check_at))}。后台持续采集时，约每小时更新；采集暂停或失败时，可能延后。</p>`:''}
        ${data?.status==='error'?'<p class="notice error">本次分析未完成。保留的旧结果仍按原时间显示。</p>':''}
        ${data?.status==='stale'?'<p class="insight-note">已超过更新周期；以下为上次分析结果。</p>':''}
        <p class="insight-note">页面可见时约每 30 秒读取最新结论。仅读取历史分析结果，不触发车辆刷新。</p></section>
        ${report?`<div class="auto-grid"><section class="card insight-panel" id="auto-energy"><h3>行驶能耗</h3>${energy(report)}</section><section class="card insight-panel" id="auto-charging"><h3>充电习惯</h3>${charging(report)}</section><section class="card insight-panel" id="auto-quality"><h3>采集质量</h3>${quality(report)}</section></div>
        ${report.unreadable_events?`<p class="insight-note">另有 ${report.unreadable_events} 条历史事件无法解析或归期，不能断言这些统计覆盖全部记录。</p>`:''}`:''}`;
      if(focused)node.querySelector('#'+focused)?.focus({preventScroll:true});
    }
    async function load() {
      if(!owner||loading||!active())return;
      const token=++serial, identity=owner;
      loading=true;error='';nextRead=Date.now()+30000;paint();
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
      if(changed){owner=context();data=null;error='';loading=false;nextRead=0;serial++;}
      if(changed||remount)paint();
      // Reuse the dashboard heartbeat; no timer survives leaving this tool.
      if(active()&&document.visibilityState==='visible'&&owner&&!loading&&Date.now()>=nextRead)load();
    }
    function handle(event) {
      if(!active()||!node?.contains(event.target)||event.type!=='click')return false;
      const button=event.target.closest('[data-auto="reload"]');
      if(!button||button.disabled)return false;
      load();return true;
    }
    return {mount,handle};
  }
  root.AutomaticInsightsPage={create};
})(window);
