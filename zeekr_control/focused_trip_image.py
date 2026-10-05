"""Route-first WeCom artwork, standard library only; offline unlabeled road context."""
import functools,json,math,struct,zlib,sqlite3,subprocess,sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .road_matching_core import EARTH

WIDTH,HEIGHT=1068,886
BG=(16,26,29);INK=(239,245,243);MUTED=(178,194,191);PAPER=(245,247,245)


def build_geometry(route,network_dir=None):
    source=route.get('segments') if isinstance(route,dict) else None
    if not isinstance(source,list) or not source or len(source)>32:
        raise ValueError('没有可绘制的可信轨迹')
    if sum(len(s) for s in source)>1500:raise ValueError('轨迹点数超过上限')
    systems=set();raw=[]
    for segment in source:
        if not isinstance(segment,list) or len(segment)<2:raise ValueError('轨迹片段点数不足')
        line=[]
        for p in segment:
            if not isinstance(p,dict) or p.get('trusted') is not True:raise ValueError('轨迹不可信')
            system=p.get('coordinate_system');systems.add(system)
            if system not in ('WGS84（社区解释）','GCJ-02（社区解释）'):raise ValueError('坐标系未知')
            lon,lat=p.get('longitude'),p.get('latitude')
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (lon,lat)) or not -180<=lon<=180 or not -85<=lat<=85 or (lon,lat)==(0,0):raise ValueError('轨迹坐标无效')
            line.append((lon,lat))
        raw.append(line)
    if len(systems)!=1:raise ValueError('轨迹坐标系混杂')
    flat=[p for s in raw for p in s]
    def project(lon,lat):return ((lon+180)/360,(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2)
    projected=[project(*p) for p in flat];xs,ys=zip(*projected)
    if max(xs)-min(xs)>.5:raise ValueError('暂不支持跨日期变更线')
    cx=(min(xs)+max(xs))/2;cy=(min(ys)+max(ys))/2
    world=256*2**12
    def pixel(lon,lat):
        x,y=project(lon,lat);return [(x-cx)*world,(y-cy)*world]
    lines=[[pixel(*p) for p in s] for s in raw]
    roads=[];seen=set();vertices=0;truncated=False
    if network_dir is not None and systems=={'WGS84（社区解释）'}:
        lons,lats=zip(*flat);pad=max(.025,max(max(lons)-min(lons),max(lats)-min(lats))*.15)
        box=(min(lons)-pad,min(lats)-pad,max(lons)+pad,max(lats)+pad)
        for path in sorted(Path(network_dir).glob('*.sqlite3'))[:8]:
            if path.is_symlink() or path.stat().st_size>64*1024*1024:continue
            try:
                with sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True,timeout=1) as db:
                    meta=dict(db.execute('SELECT key,value FROM meta'));lon0=float(meta['lon0']);lat0=float(meta['lat0'])
                    scale=EARTH*math.cos(math.radians(lat0))*math.pi/180;yscale=EARTH*math.pi/180
                    a=(box[0]-lon0)*scale;c=(box[2]-lon0)*scale;b=(box[1]-lat0)*yscale;d=(box[3]-lat0)*yscale
                    # No label/name columns are read: there is no background text layer.
                    rows=db.execute('SELECT r.f,r.t,r.coords FROM roads r JOIN road_index i ON i.id=r.id WHERE i.maxx>=? AND i.minx<=? AND i.maxy>=? AND i.miny<=? LIMIT 10001',(a,c,b,d))
                    for f,t,encoded in rows:
                        if (f,t) in seen:continue
                        coords=json.loads(encoded)
                        if len(roads)>=10000 or vertices+len(coords)>60000:truncated=True;break
                        seen.add((f,t));vertices+=len(coords)
                        roads.append([pixel(lon0+x/scale,lat0+y/yscale) for x,y in coords])
            except (sqlite3.Error,ValueError,KeyError,OSError,TypeError):continue
            if truncated:break
    return {'segments':lines,'roads':roads,'network_available':bool(roads),'background_limited':truncated}


def fit_geometry(segments,rotate=True):
    points=[p for s in segments for p in s];best=None
    for degrees in range(-90,91) if rotate else [0]:
        a=math.radians(degrees);co,si=math.cos(a),math.sin(a)
        xy=[(x*co-y*si,x*si+y*co) for x,y in points];xs,ys=zip(*xy)
        bounds=(min(xs),min(ys),max(xs),max(ys));scale=min(840/max(1,bounds[2]-bounds[0]),400/max(1,bounds[3]-bounds[1]),20)
        if best is None or scale>best['scale']+1e-7:best={'angle':degrees,'scale':scale,'co':co,'si':si,'bounds':bounds}
    x0,y0,x1,y1=best['bounds'];cx,cy=(x0+x1)/2,(y0+y1)/2
    def transform(point):
        x,y=point;return (478+(x*best['co']-y*best['si']-cx)*best['scale'],260+(x*best['si']+y*best['co']-cy)*best['scale'])
    best['segments']=[[transform(p) for p in s] for s in segments];best['transform']=transform
    return best


@functools.lru_cache(maxsize=1)
def _atlas():
    content=zlib.decompress((Path(__file__).parent/'assets/trip-font/glyphs.zlib').read_bytes())
    length=struct.unpack('>I',content[:4])[0]
    return json.loads(content[4:4+length]),content[4+length:]


class Surface:
    def __init__(self,width,height,color):self.width=width;self.height=height;self.data=bytearray(bytes(color)*(width*height))
    def rect(self,x,y,w,h,color):
        lo,hi=max(0,int(x)),min(self.width,int(x+w));top,bottom=max(0,int(y)),min(self.height,int(y+h))
        if lo>=hi or top>=bottom:return
        row=bytes(color)*(hi-lo)
        for yy in range(top,bottom):self.data[(yy*self.width+lo)*3:(yy*self.width+hi)*3]=row
    def blend(self,x,y,color,alpha):
        x,y=int(x),int(y)
        if not 0<=x<self.width or not 0<=y<self.height:return
        i=(y*self.width+x)*3
        for j in range(3):self.data[i+j]=round(self.data[i+j]*(1-alpha)+color[j]*alpha)
    def circle(self,x,y,r,color):
        for yy in range(max(0,int(y-r-1)),min(self.height,int(y+r+2))):
            half=math.sqrt(max(0,(r+.5)**2-(yy-y)**2))
            for xx in range(max(0,int(x-half-1)),min(self.width,int(x+half+2))):
                a=max(0,min(1,r+.5-math.hypot(xx-x,yy-y)))
                if a:self.blend(xx,yy,color,a)
    def line(self,a,b,color,width=1):
        # Clip before stepping: long routes/region edges must not cause unbounded loops.
        x,y=a;dx,dy=b[0]-x,b[1]-y;low,high=0.,1.;pad=width
        for p,q in ((-dx,x+pad),(dx,self.width+pad-x),(-dy,y+pad),(dy,self.height+pad-y)):
            if p==0:
                if q<0:return
            elif p<0:low=max(low,q/p)
            else:high=min(high,q/p)
        if low>high:return
        a=(x+dx*low,y+dy*low);b=(x+dx*high,y+dy*high)
        steps=max(1,math.ceil(max(abs(b[0]-a[0]),abs(b[1]-a[1]))))
        for n in range(steps+1):
            t=n/steps;xx=a[0]+(b[0]-a[0])*t;yy=a[1]+(b[1]-a[1])*t
            if width<=1:
                ix,iy=math.floor(xx),math.floor(yy);fx,fy=xx-ix,yy-iy
                for ox,oy,alpha in ((0,0,(1-fx)*(1-fy)),(1,0,fx*(1-fy)),(0,1,(1-fx)*fy),(1,1,fx*fy)):
                    if alpha:self.blend(ix+ox,iy+oy,color,alpha)
            else:self.circle(xx,yy,width/2,color)
    def text_width(self,text,size):
        index,_=_atlas();return sum(index.get(str(size)+':'+c,index[str(size)+':?'])[3] for c in str(text))
    def text(self,x,y,text,size,color,max_width=None):
        index,masks=_atlas();cursor=x
        for char in str(text):
            offset,w,h,advance=index.get(str(size)+':'+char,index[str(size)+':?'])
            if max_width is not None and cursor+advance>x+max_width:break
            for yy in range(h):
                for xx in range(w):
                    alpha=masks[offset+yy*w+xx]/255
                    if alpha:self.blend(round(cursor)+xx,round(y)+yy,color,alpha)
            cursor+=advance
        return cursor
    def png(self):
        raw=b''.join(b'\0'+self.data[y*self.width*3:(y+1)*self.width*3] for y in range(self.height))
        def chunk(name,value):return struct.pack('>I',len(value))+name+value+struct.pack('>I',zlib.crc32(name+value)&0xffffffff)
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',self.width,self.height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,6))+chunk(b'IEND',b'')


def _number(value):return '—' if type(value) not in (float,int) or not math.isfinite(value) else ('%.1f'%value).rstrip('0').rstrip('.')


def render_focused_trip_png(report,route,geometry,start_name=None):
    fitted=fit_geometry(geometry['segments']);surface=Surface(WIDTH,HEIGHT,BG)
    surface.text(56,35,'行程结束',40,INK)
    try:
        start=datetime.fromtimestamp(report['start_time']/1000,ZoneInfo('Asia/Shanghai'));end=datetime.fromtimestamp(report['end_time']/1000,ZoneInfo('Asia/Shanghai'))
        when=('%s  %s — %s'%(start.strftime('%m月%d日'),start.strftime('%H:%M'),end.strftime('%H:%M'))) if start.date()==end.date() else '%s — %s'%(start.strftime('%m/%d %H:%M'),end.strftime('%m/%d %H:%M'))
        surface.text(1012-surface.text_width(when,21),53,when,21,MUTED)
    except (KeyError,TypeError,ValueError,OverflowError):surface.text(760,53,'时间未记录',21,MUTED)
    if report.get('partial'):surface.text(56,85,'记录片段',18,(242,182,87))
    # Half-size context, interpolated back up: gentle blur, no labels or icons.
    context=Surface(478,260,PAPER)
    for road in geometry['roads']:
        for a,b in zip(road,road[1:]):
            aa,bb=fitted['transform'](a),fitted['transform'](b)
            context.line((aa[0]/2,aa[1]/2),(bb[0]/2,bb[1]/2),(205,213,208))
    map_surface=Surface(956,520,PAPER)
    for y in range(520):
        sy=y/2;y0=int(sy);y1=min(259,y0+1);fy=sy-y0
        for x in range(956):
            sx=x/2;x0=int(sx);x1=min(477,x0+1);fx=sx-x0;target=(y*956+x)*3
            for j in range(3):
                top=context.data[(y0*478+x0)*3+j]*(1-fx)+context.data[(y0*478+x1)*3+j]*fx
                bottom=context.data[(y1*478+x0)*3+j]*(1-fx)+context.data[(y1*478+x1)*3+j]*fx
                map_surface.data[target+j]=round(top*(1-fy)+bottom*fy)
    for color,width in (((255,255,255),9),((0,102,80),5)):
        for segment in fitted['segments']:
            for a,b in zip(segment,segment[1:]):map_surface.line(a,b,color,width)
    for letter,point,color in (('A',fitted['segments'][0][0],(0,102,80)),('B',fitted['segments'][-1][-1],(175,91,17))):
        x,y=point;map_surface.circle(x,y,14,(255,255,255));map_surface.circle(x,y,11,color);map_surface.text(x-4.5,y-6,letter,13,(255,255,255))
    name=' '.join(str(start_name or '起点名称未记录').split())[:100]
    while map_surface.text_width(name,18)>500:name=name[:-2]+'…' if len(name)>2 else name[:1]
    x,y=fitted['segments'][0][0];labelx=min(920-map_surface.text_width(name,18),max(20,x+20));labely=max(20,y-34)
    map_surface.rect(labelx-4,labely-3,map_surface.text_width(name,18)+8,25,PAPER);map_surface.text(labelx,labely,name,18,(23,62,50))
    a=math.radians(fitted['angle']);dx,dy=math.sin(a),-math.cos(a);x,y=890,63
    map_surface.line((x-dx*15,y-dy*15),(x+dx*16,y+dy*16),(51,76,67),2)
    tip=(x+dx*16,y+dy*16)
    for sign in (-1,1):map_surface.line(tip,(tip[0]-dx*9+sign*dy*5,tip[1]-dy*9-sign*dx*5),(51,76,67),2)
    map_surface.text(x+dx*32-7,y+dy*32-7,'北',15,(51,76,67));map_surface.text(855,101,'地图已旋转',13,(86,112,103))
    if geometry['roads']:map_surface.text(680,496,'© OpenStreetMap contributors',12,(86,112,103))
    else:map_surface.text(700,496,'本区域无道路背景',13,(86,112,103))
    for y in range(520):surface.data[((y+114)*WIDTH+56)*3:((y+114)*WIDTH+1012)*3]=map_surface.data[y*956*3:(y+1)*956*3]
    surface.circle(65,663,9,(0,120,99));surface.text(84,650,'A 首个采样',18,MUTED);surface.circle(245,663,9,(175,91,17));surface.text(264,650,'B 末个采样',18,MUTED)
    if geometry['roads']:surface.text(869,650,'OpenStreetMap',17,MUTED)
    surface.rect(56,696,956,1,(51,67,72))
    metrics=report.get('metrics',{});left=report.get('start',{});right=report.get('end',{});duration=metrics.get('duration_seconds')
    cards=[('行程里程',_number(metrics.get('distance_km')),'km'),('观测时长',_number(duration/60 if type(duration) in (float,int) else None),'分钟'),('电量','%s → %s'%(_number(left.get('soc')),_number(right.get('soc'))),'%'),('估算能耗',_number(metrics.get('estimated_kwh_100km')),'kWh/100km')]
    for i,(label,value,unit) in enumerate(cards):
        x=56+i*239;surface.text(x,720,label,21,MUTED);size=42 if surface.text_width(value,42)<175 else 35
        endx=surface.text(x,758,value,size,INK,175)
        if endx+8+surface.text_width(unit,17)<=x+220:surface.text(endx+8,778,unit,17,MUTED)
        else:surface.text(x,806,unit,17,MUTED)
        if i:surface.rect(x-18,724,1,85,(51,67,72))
    count=route.get('count');count=count if type(count) is int and 0<=count<=20000 else 0
    gaps=len(route.get('gaps',[]));footer='云端缓存采样 · %s 个位置点'%count+(' · %s 处采样间断'%gaps if gaps else '')+' · 连线不代表实走道路'
    surface.text(56,842,footer,17,MUTED,956);content=surface.png()
    if len(content)>2*1024*1024:raise ValueError('图片超过2MB')
    return content


class FocusedTripImage:
    def __init__(self,network_dir):self.network_dir=Path(network_dir)
    def render_trip(self,report,route,start_name=None):
        payload=json.dumps({'report':report,'route':route,'start_name':start_name},allow_nan=False).encode()
        if len(payload)>1500000:raise ValueError('轨迹输入超过上限')
        try:
            result=subprocess.run([sys.executable,'-m','zeekr_control.focused_trip_image','--worker',str(self.network_dir)],input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8)
        except subprocess.TimeoutExpired:raise ValueError('行程图片超时') from None
        if result.returncode or len(result.stdout)>2*1024*1024 or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('行程图片准备失败')
        return result.stdout


def _worker():
    import os,resource
    try:
        os.nice(10);resource.setrlimit(resource.RLIMIT_CPU,(6,6))
        if sys.platform=='linux':resource.setrlimit(resource.RLIMIT_AS,(256*1024*1024,256*1024*1024))
        raw=sys.stdin.buffer.read(1500001)
        if len(raw)>1500000:raise ValueError('input limit')
        data=json.loads(raw);geometry=build_geometry(data['route'],sys.argv[2]);image=render_focused_trip_png(data['report'],data['route'],geometry,data.get('start_name'));sys.stdout.buffer.write(image)
    except Exception:sys.exit(1)

if __name__=='__main__' and len(sys.argv)==3 and sys.argv[1]=='--worker':_worker()
