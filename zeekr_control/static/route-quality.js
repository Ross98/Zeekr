(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.RouteQuality=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  // Display thresholds, not GPS accuracy or gateway rate limits.
  const MAX_INTERVAL=10,MAX_DISTANCE=100,MAX_TIME=32503680000000;
  const timestamp=value=>Number.isFinite(value)&&value>0&&value<=MAX_TIME;
  const drawable=point=>point?.trusted===true&&point.plottable===true&&
    Number.isFinite(point.latitude)&&Math.abs(point.latitude)<=90&&
    Number.isFinite(point.longitude)&&Math.abs(point.longitude)<=180&&
    (point.latitude!==0||point.longitude!==0);
  function distance(a,b){
    const radians=Math.PI/180,lat1=a.latitude*radians,lat2=b.latitude*radians;
    const h=Math.sin((lat2-lat1)/2)**2+Math.cos(lat1)*Math.cos(lat2)*Math.sin((b.longitude-a.longitude)*radians/2)**2;
    return 6371008.8*2*Math.asin(Math.sqrt(Math.max(0,Math.min(1,h))));
  }
  function stats(values){
    if(!values.length)return {count:0,median:null,max:null};
    const sorted=[...values].sort((a,b)=>a-b),middle=Math.floor(sorted.length/2);
    return {count:sorted.length,median:sorted.length%2?sorted[middle]:(sorted[middle-1]+sorted[middle])/2,max:sorted.at(-1)};
  }
  function interval(a,b,key){
    return timestamp(a?.[key])&&timestamp(b?.[key])&&b[key]>a[key]?(b[key]-a[key])/1000:null;
  }
  function analyze(points,segments,timeKey){
    const times=[],distances=[],parts=[];
    let edgeCount=0,sparseEdges=0;
    for(let i=1;i<points.length;i++){
      const seconds=interval(points[i-1],points[i],timeKey);
      if(seconds!==null)times.push(seconds);
    }
    for(const segment of segments){
      let part=null;
      for(let i=1;i<segment.length;i++){
        const a=segment[i-1],b=segment[i],seconds=interval(a,b,timeKey);
        if(!drawable(a)||!drawable(b)||seconds===null){part=null;continue;}
        const meters=distance(a,b),sparse=seconds>MAX_INTERVAL||meters>MAX_DISTANCE;
        distances.push(meters);edgeCount++;if(sparse)sparseEdges++;
        if(part&&part.sparse===sparse)part.points.push(b);
        else {part={points:[a,b],sparse};parts.push(part);}
      }
    }
    return {sampleCount:points.length,trustedCount:points.filter(drawable).length,
      intervals:stats(times),distances:stats(distances),edgeCount,sparseEdges,parts};
  }
  const number=value=>Number.isFinite(value)?String(Number(value.toFixed(1))):'未知';
  const seconds=value=>Number.isFinite(value)?`${number(value)} 秒`:'未知';
  const meters=value=>Number.isFinite(value)?value>=1000?`${number(value/1000)} km`:`${number(value)} 米`:'未知';
  function summary(value,hasRoads=false){
    return `<div class="route-density" data-sparse-edges="${value.sparseEdges}"><div class="route-density-stats">
      <div><span>相邻采样时间</span><strong>中位 ${seconds(value.intervals.median)} · 最长 ${seconds(value.intervals.max)}</strong></div>
      <div><span>可信连线跨度 · 直线距离</span><strong>中位 ${meters(value.distances.median)} · 最长 ${meters(value.distances.max)}</strong></div>
      </div><p class="subtle">时间仅统计相邻且递增的源时间；不是 GPS 定位精度。跨度只统计可信片段内部，不跨缺口，不作行驶里程。</p>
      <p class="route-density-note">${value.sparseEdges&&hasRoads?`${value.sparseEdges} 段采样较稀疏；路网形状是算法推断，仍需核对实际走法。`:value.sparseEdges?`<span class="route-line-key" aria-hidden="true"></span>${value.sparseEdges} 段稀疏示意线：采样间隔超过 ${MAX_INTERVAL} 秒或跨度超过 ${MAX_DISTANCE} 米。拐角与实际经过的道路可能不同。`:value.edgeCount?'连线仅连接采样点，不保证实际道路形状。':'暂无可统计的可信连线；保留已返回采样点。'}</p></div>`;
  }
  function lineOptions(part){
    return {color:part.sparse?'#99621d':'#20776e',weight:part.sparse?3:4,
      dashArray:part.sparse?'7 7':null,smoothFactor:0,className:part.sparse?'route-sparse-line':'route-sample-line'};
  }
  function display(result,density){
    const match=result.road_matching;
    if(!match||!['matched','partial'].includes(match.status)||match.coordinate_system!=='WGS84')
      return {roads:[],fallback:density.parts};
    const roads=(match.lines||[]).filter(line=>Array.isArray(line)&&line.length>=2&&line.every(p=>
      Array.isArray(p)&&p.length===2&&Number.isFinite(p[0])&&Math.abs(p[0])<=180&&Number.isFinite(p[1])&&Math.abs(p[1])<=85));
    const observations=result.observations,covered=new Set();
    for(const [start,end] of match.spans||[]){
      if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end<=start||end>=observations.length)continue;
      for(let i=start;i<end;i++)covered.add(i);
    }
    const key=p=>JSON.stringify([p.state_time,p.observed_time,p.longitude,p.latitude]);
    const indices=new Map(observations.map((p,i)=>[key(p),i]));
    const fallback=[];
    for(const part of density.parts){
      let current=null;
      for(let i=1;i<part.points.length;i++){
        const a=part.points[i-1],b=part.points[i],start=indices.get(key(a)),end=indices.get(key(b));
        if(end===start+1&&covered.has(start)){current=null;continue;}
        if(current)current.points.push(b);
        else {current={points:[a,b],sparse:true,unmatched:true};fallback.push(current);}
      }
    }
    return {roads,fallback};
  }
  function matchSummary(match){
    if(!match||match.status==='empty')return '';
    const reasons={unavailable:'本段暂无可用路网',unmatched:'本段未找到可匹配道路',
      timeout:'路网推断超时',busy:'路网推断正在处理其他路线',error:'路网推断暂不可用',limit:'本段超出当前推断范围'};
    if(reasons[match.status])return `<p class="subtle route-match-status">${reasons[match.status]}，保留采样点连线。</p>`;
    if(!['matched','partial'].includes(match.status))return '';
    const count=Array.isArray(match.matched_indices)?match.matched_indices.length:0;
    const total=Number.isInteger(match.eligible_points)?match.eligible_points:0;
    const issues=Number.isInteger(match.issues)?match.issues:0;
    return `<p class="subtle route-match-status">路网路线 · 算法推断，未经实走确认。源点匹配 ${count}/${total}${issues?` · ${issues} 处道路未连通`:''}。${match.status==='partial'?'未匹配或未连通部分保留采样点虚线。':''}道路：© OpenStreetMap contributors。</p>`;
  }
  return {analyze,summary,lineOptions,display,matchSummary};
});
