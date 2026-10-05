(function(root){
  'use strict';
  const num=n=>Number.isFinite(n)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(n):'—';
  const monthNow=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit'}).format(new Date());
  const modes={ac:'交流',dc:'直流'},sources={ac_ui:'交流电压 × 电流估算',dc_pile_ui:'直流桩端电压 × 电流估算'};
  const reasons={no_common_range:'没有共同的有效 SOC 观测范围',boundary_not_observed:'缺少共同边界的精确观测，耗时不插值',gaps_or_reset:'存在缺口或 SOC 倒退，区间耗时不比较',single_soc:'只共享一个 SOC 值，不能比较区间耗时'};
  function create({getState,request,escape:esc,active,time}){
    let node=null,owner='',data=null,error='',comparing=false,comparisonSerial=0,temperature='outside_temp';
    let months={a:monthNow(),b:monthNow()},choices={a:null,b:null},selected={a:'',b:''},loading={a:false,b:false};
    let attempted={a:false,b:false},listSerial={a:0,b:0},listError={a:'',b:''},pointIndex={a:0,b:0};
    const context=()=>getState()?.insights_context||'';
    const valid=(token,current,identity)=>token===current&&identity===owner&&context()===identity;
    const canCompare=()=>owner&&selected.a&&selected.b&&selected.a!==selected.b&&!loading.a&&!loading.b&&!comparing;
    function paint(){
      return root.RefreshView?root.RefreshView.preserve(node,paintContent):paintContent();
    }
    function paintContent(){
      if(root.deferDateRender?.(paint))return;
      if(!node?.isConnected||!active())return;
      const focus=node.contains(document.activeElement)?document.activeElement.id:null;
      node.innerHTML=`<section class="insight-hero"><div><span class="insight-eyebrow">充电曲线对比</span><h2>对齐电量，看两次充电</h2><p>功率、环境温度、经过时间，各自保留观测依据。</p></div><span class="insight-source">真实观测点 · 共同 SOC</span></section>
        <section class="card insight-panel"><div class="charge-selectors">${['a','b'].map(side=>`<div><h3>充电 ${side.toUpperCase()}</h3><div class="insight-toolbar"><label>充电 ${side.toUpperCase()} 月份<input id="charge-month-${side}" type="month" value="${esc(months[side])}"></label><button class="button secondary" data-charge-compare="load" data-side="${side}" ${!owner||!months[side]||loading[side]?'disabled':''}>读取充电 ${side.toUpperCase()}</button></div><label>充电记录 ${side.toUpperCase()}<select id="charge-select-${side}" aria-label="充电记录 ${side.toUpperCase()}" ${loading[side]?'disabled':''}><option value="">选择已结束充电</option>${(choices[side]?.events||[]).map(row=>`<option value="${esc(row.id)}" ${selected[side]===row.id?'selected':''}>${esc(time(row.end_time))} · ${num(row.start_soc)}% → ${num(row.end_soc)}%${row.partial?' · 片段':''}</option>`).join('')}</select></label>${listError[side]?`<p role="alert">${esc(listError[side])}</p>`:''}<p class="insight-note">${loading[side]?'读取中…':choices[side]?choices[side].window.start_date.slice(0,7)+' · '+choices[side].events.length+' 条记录':'先读取对应月份'}</p></div>`).join('')}</div><div class="insight-actions"><button id="charge-run-comparison" class="button" data-charge-compare="compare" ${canCompare()?'':'disabled'}>${comparing?'正在比较…':'比较这两次充电'}</button><span>可选不同月份。请选择两条不同记录。</span></div>${error?`<p class="notice error" role="alert">${esc(error)}</p>`:''}${!owner?'<p>等待当前账号的车辆缓存后可查看。</p>':''}</section>
        ${data?`<section class="card insight-panel"><div class="insight-heading"><h3>${data.common?`共同观测 SOC：${num(data.common.low)}% — ${num(data.common.high)}%`:'没有共同的有效 SOC 观测范围'}</h3><span class="insight-badge">已载入比较结果</span></div><div id="charge-compare-summary" class="charge-selectors">${['a','b'].map(side=>{
          const row=data[side],t=row.timing;
          return `<article><h4>${side.toUpperCase()} · ${esc(time(row.event.end_time))}</h4><p>${row.event.partial?'充电观测片段':'完整充电记录'} · ${row.modes.map(m=>modes[m]).join('、')||'模式未知'}</p><p>功率来源：${row.power_sources.map(s=>sources[s]).join('、')||'无已核验功率'}</p><p>原有效 SOC 范围 ${row.soc_range?row.soc_range.map(num).join(' — ')+'%':'未知'} · 共同区间 ${row.matched_count} 个观测点</p><div class="charge-duration"><span>共同区间的观测耗时</span><strong>${t.reason?'无法确定':t.minimum_seconds===t.maximum_seconds?num(t.minimum_seconds/60)+' 分钟':num(t.minimum_seconds/60)+' — '+num(t.maximum_seconds/60)+' 分钟'}</strong><p>${t.reason?esc(reasons[t.reason]):'按两个边界 SOC 的首次与末次观测给出范围；不伪造精确到达时刻。'}</p></div><p class="insight-note">读取 ${row.quality.reads} 条，有效 ${row.quality.eligible} 条；排除 ${row.quality.excluded} 条，格式异常 ${row.quality.invalid} 条。${row.quality.segments} 个连续片段。${row.downsampled?'显示抽样 '+row.display_count+' 点，统计使用全部有效点。':''}</p></article>`;
        }).join('')}</div><p class="insight-note">两次功率来源、交流/直流、SOC 覆盖、环境条件可能不同，不能据曲线直接判断电池健康或充电桩优劣。线条只连接同一连续片段的有效点。</p></section>
        ${data.common?`<section class="card insight-panel"><div class="insight-heading"><h3>共同 SOC 下的变化</h3><label>对比温度<select id="charge-temperature" aria-label="对比温度"><option value="outside_temp" ${temperature==='outside_temp'?'selected':''}>车外温度</option><option value="inside_temp" ${temperature==='inside_temp'?'selected':''}>座舱温度</option></select></label></div><div class="charge-legend"><span class="charge-key-a">A · 实线</span><span class="charge-key-b">B · 虚线</span></div><p class="insight-note">温度是车外或座舱观测，不是电池温度。旧温度与未知功率留空。相同 SOC 可以对应多条观测，竖向点列保留这些变化。</p><div id="charge-comparison-charts"></div><p class="insight-note">经过时间从各自在共同下界 SOC 的首次观测计时，包含时钟经过的空白；缺少该观测时不绘制时间曲线。缺口两侧不连线，不把经过时间当作净充电时长。</p></section>
        <section class="card insight-panel"><h3>逐点核对</h3><div class="charge-selectors">${['a','b'].map(side=>`<div><label>查看观测点 ${side.toUpperCase()}<select id="charge-point-select-${side}" aria-label="查看观测点 ${side.toUpperCase()}">${data[side].points.map((p,i)=>`<option value="${i}" ${i===pointIndex[side]?'selected':''}>${num(p.soc)}% · ${esc(time(p.time))}</option>`).join('')}</select></label><div id="charge-point-${side}"></div></div>`).join('')}</div></section>`:''}`:''}`;
      paintCharts();paintPoints();if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    }
    function plot(field,label,unit,divisor=1){
      const container=node.querySelector('#charge-comparison-charts'),width=Math.max(250,Math.min(1100,container.clientWidth||600));
      const height=285,left=51,right=18,top=20,bottom=45,innerW=width-left-right,innerH=height-top-bottom;
      const values=['a','b'].flatMap(side=>data[side].points.map(p=>p[field]).filter(Number.isFinite)).map(v=>v/divisor);
      let low=field.includes('temp')&&values.length?Math.floor(Math.min(...values)-1):0;
      let high=values.length?Math.max(...values):1;high=field.includes('temp')?Math.ceil(high+1):Math.max(1,Math.ceil(high/5)*5);
      if(high<=low)high=low+1;
      const xlow=data.common.low,xhigh=data.common.high,span=xhigh-xlow;
      const x=v=>span?left+(v-xlow)/span*innerW:left+innerW/2,y=v=>top+(high-v/divisor)/(high-low)*innerH;
      let paths='';
      for(const side of ['a','b']){
        const groups=new Map();
        data[side].points.forEach((p,i)=>{if(p[field]===null)return;const line=p.lines[field];if(!groups.has(line))groups.set(line,[]);groups.get(line).push({p,i});});
        for(const [line,rows] of groups){
          paths+=`<polyline class="compare-line-${side}" data-line="${side}-${line}" points="${rows.map(({p})=>x(p.soc).toFixed(2)+','+y(p[field]).toFixed(2)).join(' ')}"/>`;
          paths+=rows.map(({p,i})=>`<circle class="compare-point-${side}" data-charge-compare="point" data-side="${side}" data-index="${i}" cx="${x(p.soc).toFixed(2)}" cy="${y(p[field]).toFixed(2)}" r="${i===pointIndex[side]?4:2.5}"><title>${side.toUpperCase()} · ${num(p.soc)}% · ${num(p[field]/divisor)} ${unit} · ${esc(time(p.time))}</title></circle>`).join('');
        }
      }
      const ticks=Array.from({length:5},(_,i)=>i/4);
      return `<div class="charge-chart"><h4>${label} <small>(${unit})</small></h4>${!values.length?'<p class="insight-note">共同区间没有这个指标的有效点。</p>':''}<svg data-charge-chart="${field}" role="img" aria-label="${label}，横轴为共同 SOC，A 实线 B 虚线" viewBox="0 0 ${width} ${height}">${ticks.map(t=>{const yy=top+t*innerH,v=high-t*(high-low);return `<line class="compare-grid" x1="${left}" x2="${width-right}" y1="${yy}" y2="${yy}"/><text x="${left-8}" y="${yy+5}" text-anchor="end">${num(v)}</text>`;}).join('')}${ticks.map(t=>`<text x="${left+t*innerW}" y="${height-23}" text-anchor="middle">${num(xlow+t*span)}%</text>`).join('')}${paths}<text x="${left+innerW/2}" y="${height-3}" text-anchor="middle">SOC</text></svg></div>`;
    }
    function paintCharts(){
      const container=node?.querySelector('#charge-comparison-charts');if(!container||!data?.common||!active())return;
      container.innerHTML=plot('power_kw','观测功率','kW')+plot(temperature,temperature==='inside_temp'?'座舱温度':'车外温度','°C')+plot('elapsed_seconds','自共同下界首次观测后的经过时间','分钟',60);
    }
    function paintPoints(){
      if(!data||!node)return;
      for(const side of ['a','b']){const el=node.querySelector('#charge-point-'+side),p=data[side].points[pointIndex[side]];if(!el)continue;
        el.innerHTML=p?`<div class="parking-row-values"><span>SOC<strong>${num(p.soc)}%</strong></span><span>观测功率<strong>${num(p.power_kw)} kW</strong></span><span>车外温度<strong>${num(p.outside_temp)} °C</strong></span><span>座舱温度<strong>${num(p.inside_temp)} °C</strong></span></div><p class="insight-note">车辆时间 ${esc(time(p.time))}<br>采集时间 ${esc(time(p.observed_at))}<br>${modes[p.mode]} · ${sources[p.power_source]||'功率未核验或缺失'}<br>经过 ${num(p.elapsed_seconds===null?null:p.elapsed_seconds/60)} 分钟</p>`:'<p>没有可核对的共同区间观测点。</p>';
        const select=node.querySelector('#charge-point-select-'+side);if(select)select.value=pointIndex[side];
      }
    }
    function invalidate(){comparisonSerial++;comparing=false;}
    async function load(side){
      if(!owner||!months[side])return;
      invalidate();const identity=owner,token=++listSerial[side],month=months[side];attempted[side]=true;loading[side]=true;listError[side]='';paint();
      try{const result=await request('/api/insights/charge-comparison/options?date='+encodeURIComponent(month+'-01'));
        if(!valid(token,listSerial[side],identity))return;if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');
        choices[side]=result;if(!result.events.some(row=>row.id===selected[side]))selected[side]=result.events.find(row=>row.id!==selected[side==='a'?'b':'a'])?.id||result.events[0]?.id||'';
      }catch(failure){if(valid(token,listSerial[side],identity))listError[side]=failure.message;}
      finally{if(valid(token,listSerial[side],identity)){loading[side]=false;paint();}}
    }
    async function compare(){
      if(!canCompare())return;const identity=owner,token=++comparisonSerial;comparing=true;error='';paint();
      try{const result=await request('/api/insights/charge-comparison?a='+encodeURIComponent(selected.a)+'&b='+encodeURIComponent(selected.b));
        if(!valid(token,comparisonSerial,identity))return;if(result.context!==identity)throw Error('账号或车辆已切换，请重新读取。');data=result;pointIndex={a:0,b:0};
      }catch(failure){if(valid(token,comparisonSerial,identity))error=failure.message;}
      finally{if(valid(token,comparisonSerial,identity)){comparing=false;paint();}}
    }
    function mount(container){
      const changed=owner!==context(),remount=node!==container;node=container;
      if(changed){owner=context();data=null;error='';invalidate();for(const side of ['a','b']){choices[side]=null;selected[side]='';loading[side]=attempted[side]=false;listSerial[side]++;listError[side]='';}}
      if(changed||remount)paint();
    }
    function handle(event){
      if(!active()||!node?.contains(event.target))return false;const el=event.target;
      if(event.type==='input'&&el.id.startsWith('charge-month-')){const side=el.id.endsWith('-a')?'a':'b';if(months[side]!==el.value){months[side]=el.value;listSerial[side]++;choices[side]=null;selected[side]='';loading[side]=attempted[side]=false;listError[side]='';data=null;error='';invalidate();paint();}return true;}
      if(event.type==='change'){
        if(el.id==='charge-temperature'){temperature=el.value;paintCharts();return true;}
        if(el.id.startsWith('charge-point-select-')){const side=el.id.endsWith('-a')?'a':'b';pointIndex[side]=Number(el.value);paintPoints();paintCharts();return true;}
        if(el.id.startsWith('charge-select-')){const side=el.id.endsWith('-a')?'a':'b';selected[side]=el.value;data=null;error='';invalidate();paint();return true;}
      }
      if(event.type!=='click')return false;const target=el.closest('[data-charge-compare]');if(!target||target.disabled)return false;
      const action=target.dataset.chargeCompare,side=target.dataset.side;
      if(action==='load')load(side);else if(action==='compare')compare();else if(action==='point'){pointIndex[side]=Number(target.dataset.index);paintPoints();paintCharts();}
      return true;
    }
    root.addEventListener('resize',()=>{if(active()&&node?.isConnected)paintCharts();});
    return {mount,handle};
  }
  root.ChargeComparisonPage={create};
})(window);
