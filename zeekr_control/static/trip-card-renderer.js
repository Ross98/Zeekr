(function(root,factory){
  const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.TripCardRenderer=api;
})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  const clean=(value,limit)=>typeof value==='string'?Array.from(value.replace(/\s+/g,' ').trim()).slice(0,limit).join(''):'';
  const numeric=value=>typeof value==='number'&&Number.isFinite(value);
  const number=value=>numeric(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value):'未知';
  const time=value=>numeric(value)?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)):'未知';
  const soc=value=>numeric(value)?number(value)+'%':'未知';
  function describe(trip,charge,settings){
    const metrics=[];
    if(settings.showDistance)metrics.push({label:'行程里程',value:number(trip.distance_km),unit:numeric(trip.distance_km)?'km':''});
    if(settings.showTime)metrics.push({label:'观测时长',value:number(numeric(trip.duration_seconds)?trip.duration_seconds/60:null),unit:numeric(trip.duration_seconds)?'分钟':''});
    if(settings.showSoc)metrics.push({label:'起止 SOC',value:soc(trip.start_soc)+' → '+soc(trip.end_soc),unit:''});
    let attached=null;
    if(settings.showCharge&&charge?.kind==='charge_end')attached={title:'另附充电记录',lines:[
      ...(settings.showTime?[time(charge.end_time)]:[]),
      ({ac:'交流',dc:'直流'}[charge.charge_mode]||'类型未知')+' · '+soc(charge.start_soc)+' → '+soc(charge.end_soc),
      'SOC 电量估算 '+number(charge.estimated_kwh)+(numeric(charge.estimated_kwh)?' kWh':''),
      charge.partial?'充电观测片段':'独立充电记录，与行程不作归因']};
    return {title:clean(settings.title,60)||'一段用车记录',metrics,
      period:settings.showTime?'开始 '+time(trip.start_time)+'\n结束 '+time(trip.end_time):'',
      note:clean(settings.note,400),location:settings.showLocation?clean(settings.location,80):'',charge:attached,
      quality:trip.partial===false?'完整行程记录':'观测片段 · 起止或过程可能缺失',
      footnote:settings.showSoc||attached?'本地观测摘录 · SOC 电量非电表计量':'本地观测摘录'};
  }
  function imageSize(input){
    const b=input instanceof Uint8Array?input:new Uint8Array(input);
    if(b.length>8*1024*1024)throw Error('照片不得超过 8 MiB。');
    const view=new DataView(b.buffer,b.byteOffset,b.byteLength);
    const ascii=(at,length)=>String.fromCharCode(...b.slice(at,at+length));
    const finish=(width,height,type)=>{
      if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width>12000||height>12000||width*height>24000000)throw Error('照片尺寸超过限制：最长边 12000，最多 2400 万像素。');
      return {width,height,type};
    };
    if(b.length>=24&&b[0]===137&&ascii(1,7)==='PNG\r\n\x1a\n'&&ascii(12,4)==='IHDR')return finish(view.getUint32(16),view.getUint32(20),'image/png');
    if(b.length>=4&&b[0]===255&&b[1]===216){
      let at=2;
      while(at+3<b.length){
        if(b[at++]!==255)break;while(b[at]===255)at++;const marker=b[at++];
        if(marker===217||marker===218)break;
        if(marker===1||marker>=208&&marker<=215)continue;
        if(at+2>b.length)break;const size=view.getUint16(at);if(size<2||at+size>b.length)break;
        if([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(marker)&&size>=7)return finish(view.getUint16(at+5),view.getUint16(at+3),'image/jpeg');
        at+=size;
      }
    }
    if(b.length>=30&&ascii(0,4)==='RIFF'&&ascii(8,4)==='WEBP'){
      const kind=ascii(12,4),uint24=at=>b[at]+b[at+1]*256+b[at+2]*65536;
      if(kind==='VP8X')return finish(uint24(24)+1,uint24(27)+1,'image/webp');
      if(kind==='VP8 '&&b[23]===157&&b[24]===1&&b[25]===42)return finish(view.getUint16(26,true)&16383,view.getUint16(28,true)&16383,'image/webp');
      if(kind==='VP8L'&&b[20]===47)return finish(1+b[21]+((b[22]&63)<<8),1+(b[22]>>6)+(b[23]<<2)+((b[24]&15)<<10),'image/webp');
    }
    throw Error('请选择有效的 PNG、JPEG 或 WebP 照片。');
  }
  const palettes={light:{background:'#f0f5f3',surface:'#ffffff',soft:'#e5f0eb',ink:'#183a34',secondary:'#47645d',accent:'#1c6b59',line:'#c6d8cf'},dark:{background:'#0f191d',surface:'#1b2a30',soft:'#253c37',ink:'#edf5f2',secondary:'#bfcec8',accent:'#8ad7bc',line:'#456358'}};
  const family='"PingFang SC", "Microsoft YaHei", sans-serif';
  function wrap(ctx,text,width){
    const lines=[];
    const segmenter=typeof Intl.Segmenter==='function'?new Intl.Segmenter('zh-CN',{granularity:'grapheme'}):null;
    for(const paragraph of String(text).split('\n')){
      let line='';const symbols=segmenter?[...segmenter.segment(paragraph)].map(s=>s.segment):Array.from(paragraph);
      for(const ch of symbols){if(line&&ctx.measureText(line+ch).width>width){lines.push(line);line=ch;}else line+=ch;}
      lines.push(line);
    }
    return lines;
  }
  function draw(canvas,model,{theme='light',photo=null}={}){
    const p=palettes[theme]||palettes.light,ctx=canvas.getContext('2d');
    const width=720,padding=36,inner=width-padding*2,blocks=[];let y=38;
    const font=(size,weight=400)=>`${weight} ${size}px ${family}`;
    function text(value,size=28,color=p.ink,weight=400,gap=18){
      ctx.font=font(size,weight);const lines=wrap(ctx,value,inner),lineHeight=Math.ceil(size*1.4);
      blocks.push({kind:'text',lines,size,color,weight,lineHeight,y,height:lines.length*lineHeight});y+=lines.length*lineHeight+gap;
    }
    text('用车记录',24,p.accent,650,16);text(model.title,42,p.ink,650,18);
    text(model.quality,24,p.secondary,400,22);
    if(model.period)text(model.period,26,p.secondary,400,22);
    if(photo){const height=Math.min(500,Math.max(240,inner*photo.height/photo.width));blocks.push({kind:'photo',y,height});y+=height+24;}
    if(model.metrics.length){
      const height=Math.ceil(model.metrics.length/2)*150-14;
      blocks.push({kind:'metrics',y,height,items:model.metrics});y+=height+26;
    }
    if(model.charge){text(model.charge.title,28,p.accent,650,8);text(model.charge.lines.join('\n'),26,p.secondary,400,26);}
    if(model.note){text('随手记',26,p.accent,650,8);text(model.note,28,p.ink,400,26);}
    if(model.location){text('地点 · 手动填写',24,p.accent,650,8);text(model.location,28,p.ink,400,26);}
    const footerY=Math.max(840,y+20),height=footerY+115;
    canvas.width=width*2;canvas.height=Math.ceil(height*2);ctx.scale(2,2);ctx.textBaseline='top';
    ctx.fillStyle=p.background;ctx.fillRect(0,0,width,height);
    ctx.fillStyle=p.surface;ctx.fillRect(18,18,width-36,height-36);
    for(const block of blocks){
      if(block.kind==='text'){
        ctx.fillStyle=block.color;ctx.font=font(block.size,block.weight);
        block.lines.forEach((line,i)=>ctx.fillText(line,padding,block.y+i*block.lineHeight,inner));
      }else if(block.kind==='photo'){
        ctx.fillStyle=p.soft;ctx.fillRect(padding,block.y,inner,block.height);
        const scale=Math.min(inner/photo.width,block.height/photo.height),w=photo.width*scale,h=photo.height*scale;
        ctx.drawImage(photo,padding+(inner-w)/2,block.y+(block.height-h)/2,w,h);
      }else{
        block.items.forEach((metric,i)=>{
          const w=(inner-14)/2,x=padding+(i%2)*(w+14),top=block.y+Math.floor(i/2)*150;
          ctx.fillStyle=p.soft;ctx.fillRect(x,top,w,136);ctx.fillStyle=p.secondary;ctx.font=font(24);ctx.fillText(metric.label,x+18,top+17,w-36);
          const value=metric.value+(metric.unit?' '+metric.unit:'');let size=42;ctx.font=font(size,650);
          while(size>26&&ctx.measureText(value).width>w-36){size--;ctx.font=font(size,650);}
          ctx.fillStyle=p.ink;ctx.fillText(value,x+18,top+62,w-36);
        });
      }
    }
    ctx.strokeStyle=p.line;ctx.beginPath();ctx.moveTo(padding,footerY);ctx.lineTo(width-padding,footerY);ctx.stroke();
    ctx.font=font(23);ctx.fillStyle=p.secondary;ctx.fillText(model.footnote,padding,footerY+20,inner);
    ctx.font=font(22);ctx.fillText('用车研究 · 浏览器本地生成',padding,footerY+58,inner);
    return {width,height,pixelWidth:canvas.width,pixelHeight:canvas.height,blocks:blocks.map(b=>({y:b.y,height:b.height}))};
  }
  return {describe,imageSize,draw,wrap,palettes};
});
