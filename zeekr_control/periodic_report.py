"""Prebaked WeCom cards and conservative, durable two-part delivery. No scheduler."""
from contextlib import contextmanager
from datetime import datetime
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sqlite3
import struct
import subprocess
import sys
import time
import zlib

from .archive_reader import _private
from .focused_trip_image import ImagePreparationError
from .notifications import DeliveryError
from .snapshot_archive import BEIJING
from .tracks import day_bounds

WIDTH, HEIGHT = 1068, 540
ASSETS = Path(__file__).parent/'assets/periodic-report'
TITLES = {'day':'用车日报','week':'用车周报','month':'用车月报'}
PALETTES = {
    'light':dict(paper='#F4F8F6',ink='#172E35',muted='#4D666C',accent='#146C59',warning='#8A4B0E'),
    'dark':dict(paper='#162329',ink='#EFF6F7',muted='#B3C6CD',accent='#A0DECB',warning='#F0C67D')}
WORKER_TIMEOUT_SECONDS = 45


def report_id(scope,vehicle,period,start_date,end_date):
    return hashlib.sha256(json.dumps([scope,vehicle,period,start_date,end_date]).encode()).hexdigest()


def formatted(value, decimals=1):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1e12:
        return '—'
    if value>=100000:return ('%.1f'%(value/10000)).removesuffix('.0')+'万'
    return ('%.*f'%(decimals,value)).rstrip('0').rstrip('.') if decimals else str(round(value))


def timestamp(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=4102444800000:
        return '未记录'
    return datetime.fromtimestamp(value/1000,BEIJING).strftime('%Y/%m/%d %H:%M')


def report_view(report):
    if not isinstance(report,dict) or report.get('schema_version')!=1 or report.get('period') not in TITLES:
        raise ValueError('报告格式无效')
    for key in ('start_date','end_date'):day_bounds(report[key])
    if report['start_date']>report['end_date']:raise ValueError('报告日期无效')
    metrics, quality = report['metrics'], report['quality']
    # Reject malformed counts instead of displaying a false clean result.
    for key in ('trip_count','charge_count'):
        if type(metrics[key]) is not int or not 0<=metrics[key]<=1000000:raise ValueError('报告计数无效')
    for key in ('observed_days','elapsed_days','partial_event_count','partial_trip_count',
                'missing_distance_count','missing_duration_count','missing_trip_energy_count',
                'missing_charge_energy_count','unpriced_bill_count','pending_charge_bill_count','invalid_event_count'):
        if type(quality[key]) is not int or not 0<=quality[key]<=1000000:raise ValueError('报告质量无效')
    missing = (quality['archive_limited'] or quality['observed_days']<quality['elapsed_days'] or
               any(quality[k]>0 for k in ('partial_event_count','missing_distance_count',
                   'missing_duration_count','missing_trip_energy_count','missing_charge_energy_count','invalid_event_count')))
    unpriced = quality['unpriced_bill_count']>0 or quality['pending_charge_bill_count']>0
    start,end = report['start_date'].replace('-','/'),report['end_date'].replace('-','/')
    date = start if start==end else start+'–'+(end[5:] if start[:4]==end[:4] else end)
    duration = metrics.get('duration_seconds')
    paid = metrics.get('charging_paid_cents')
    notice = '暂无结束记录' if metrics['trip_count']==metrics['charge_count']==0 else '部分数据' if missing else '已结束记录汇总'
    if unpriced:notice += ' · 费用待补录'
    if report.get('demo'):notice = '演示数据 · '+notice
    return dict(title=TITLES[report['period']],date=date,distance=formatted(metrics.get('distance_km')),
        distance_partial=quality['missing_distance_count']>0 or quality['partial_trip_count']>0,
        counts=formatted(metrics['trip_count'],0)+' 趟行程 · '+formatted(metrics['charge_count'],0)+' 次充电',
        values=[formatted(metrics.get('trip_estimated_kwh'))+' kWh',
                formatted(duration/60 if type(duration) in (int,float) else None,0)+' 分钟',
                formatted(metrics.get('charge_estimated_kwh'))+' kWh',
                formatted(paid/100 if type(paid) in (int,float) else None,2)+' 元'],
        partials=[quality['missing_trip_energy_count']>0,quality['missing_duration_count']>0,
                  quality['missing_charge_energy_count']>0,unpriced],notice=notice,warning=bool(missing or unpriced),
        footer='车辆 '+timestamp(report.get('vehicle_updated_at')),
        generated='生成 '+timestamp(report.get('generated_at')),
        coverage='%s/%s 天有采样'%(quality['observed_days'],quality['elapsed_days']))


@functools.lru_cache(maxsize=2)
def atlas(theme):
    packed = zlib.decompress((ASSETS/('glyphs-'+theme+'.zlib')).read_bytes())
    size = struct.unpack('>I',packed[:4])[0]
    return json.loads(packed[4:4+size]),packed[4+size:]


def png(pixels):
    raw = b''.join(b'\0'+pixels[y*WIDTH*3:(y+1)*WIDTH*3] for y in range(HEIGHT))
    def chunk(name,data):
        return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',WIDTH,HEIGHT,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,1))+chunk(b'IEND',b'')


def render_png(report, theme='light'):
    if theme not in PALETTES:raise ValueError('报表主题无效')
    view = report_view(report)
    pixels = bytearray(zlib.decompress((ASSETS/(report['period']+'-'+theme+'.rgb.zlib')).read_bytes()))
    if len(pixels)!=WIDTH*HEIGHT*3:raise ValueError('底图尺寸无效')
    index, glyphs = atlas(theme)
    def width(text,role):return sum(index[role+':'+c][3] for c in text)
    def text(x,y,value,role,bound):
        if width(value,role)>bound:raise ValueError('报表文字超出区域')
        for char in value:
            offset,w,h,advance = index[role+':'+char]
            if y+h>HEIGHT or x+w>WIDTH:raise ValueError('报表文字超出画布')
            for row in range(h):
                target=((y+row)*WIDTH+x)*3;source=offset+row*w*3
                pixels[target:target+w*3]=glyphs[source:source+w*3]
            x+=advance
        return x
    text(1018-width(view['date'],'date'),48,view['date'],'date',620)
    if view['distance_partial']:text(50,130,'部分里程','warning',365)
    role = next((r for r in ('distance','distance_small','distance_tiny') if width(view['distance'],r)<=360),None)
    if role is None:raise ValueError('里程数字过长')
    endx=text(50,171,view['distance'],role,360)
    text(endx+12,232,'km','unit',70)
    text(50,322,view['counts'],'small',410)
    for i,value in enumerate(view['values']):
        x,y=500+(i%2)*267,185+(i//2)*122
        role='value' if width(value,'value')<=240 else 'value_small'
        text(x,y,value,role,240)
        if view['partials'][i]:text(x+145,y-44,'·部分','warning',90)
    text(50,413,view['notice'],'warning' if view['warning'] else 'small',780)
    text(1018-width(view['coverage'],'small'),413,view['coverage'],'small',230)
    text(50,469,view['footer'],'small',570)
    text(1018-width(view['generated'],'small'),469,view['generated'],'small',410)
    return png(pixels)


class ReportImage:
    def render(self,report,theme='light'):
        try:payload=json.dumps(dict(report=report,theme=theme),allow_nan=False).encode()
        except (ValueError,TypeError):raise ImagePreparationError('报表输入无效',retryable=False) from None
        if len(payload)>16384:raise ImagePreparationError('报表输入超限',retryable=False)
        try:
            result=subprocess.run([sys.executable,'-m','zeekr_control.periodic_report','--worker'],
                input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=WORKER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:raise ImagePreparationError('报表图片超时') from None
        if result.returncode:
            if result.returncode in (-signal.SIGXCPU,-signal.SIGKILL):raise ImagePreparationError('报表图片资源超限')
            code=result.stderr.decode('ascii',errors='replace').strip()
            raise ImagePreparationError('报表图片准备失败',retryable=code not in ('input','assets'))
        if not result.stdout.startswith(b'\x89PNG\r\n\x1a\n') or len(result.stdout)>2*1024*1024:
            raise ImagePreparationError('报表图片输出无效')
        return result.stdout


def markdown(report):
    view=report_view(report)
    return '\n'.join(['## '+view['title'],view['date'],
        ('部分里程' if view['distance_partial'] else '里程')+'：'+view['distance']+' km',view['counts'],
        *[label+('（部分）' if partial else '')+'：'+value for label,value,partial in
          zip(('估算耗电','观测时长','估算充入','充电实付'),view['values'],view['partials'])],
        view['notice']+' · '+view['coverage'],view['footer'],view['generated'],
        '按结束日归属；采样天数不代表全天完整。充电实付与耗电成本分开。'])


class PeriodicDelivery:
    """Each operation is claimed before I/O. A crash leaves sending: never auto replay."""
    def __init__(self,path,renderer=None,clock=None):
        self.path=Path(path);self.renderer=renderer or ReportImage()
        self.clock=clock or (lambda:int(time.time()*1000))

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        _private(self.path.parent,directory=True)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
        _private(self.path)
        db=sqlite3.connect(self.path,timeout=5)
        db.row_factory=sqlite3.Row
        try:
            with db:db.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY,payload TEXT,theme TEXT,text TEXT,image TEXT,text_attempts INTEGER,image_attempts INTEGER,next_at INTEGER)')
            yield db
        finally:db.close()

    def deliver(self,scope,vehicle,report,sender,theme='light'):
        report_view(report)
        if report.get('demo'):raise ValueError('演示报告不可发送')
        if theme not in PALETTES:raise ValueError('报表主题无效')
        key=report_id(scope,vehicle,report['period'],report['start_date'],report['end_date'])
        now=self.clock()
        with self.connect() as db:
            with db:
                db.execute('INSERT OR IGNORE INTO reports VALUES (?,?,?,?,?,?,?,?)',
                    (key,json.dumps(report,allow_nan=False),theme,'pending','pending',0,0,0))
            row=dict(db.execute('SELECT * FROM reports WHERE id=?',(key,)).fetchone())
        report=json.loads(row['payload']);theme=row['theme']
        if now<row['next_at'] or row['text'] in ('sending','unknown','failed'):return self.status(key)
        content=None
        # Preparation claims also serialize concurrent invocations, before any sends.
        if row['image'] in ('pending','retry') and row['image_attempts']<3:
            if self.claim(key,'image',row['image']):
                try:content=self.renderer.render(report,theme)
                except ImagePreparationError as error:
                    self.finish(key,'image','failed' if not error.retryable or row['image_attempts']>=2 else 'retry',now+120000)
                except Exception:
                    self.finish(key,'image','failed',now+120000)
                else:self.finish(key,'image','ready',0)
            else:return self.status(key)
        elif row['image'] in ('sending','unknown'):return self.status(key)
        if row['text'] in ('pending','retry'):
            if not self.claim(key,'text',row['text']):return self.status(key)
            self.send(key,'text',lambda:sender.send_markdown(markdown(report)),now)
        state=self.status(key)
        if state['text']=='sent' and state['image']=='ready':
            # Ready with no in-memory content means a prior process stopped before send:
            # regenerate safely; sending itself is always claimed durably first.
            if content is None:
                try:content=self.renderer.render(report,theme)
                except Exception:
                    self.finish(key,'image','failed',0);return self.status(key)
            if self.claim(key,'image','ready',increment=False):
                self.send(key,'image',lambda:sender.send_image(content),now)
        return self.status(key)

    def claim(self,key,part,expected,increment=True):
        with self.connect() as db,db:
            result=db.execute('UPDATE reports SET '+part+'=\'sending\','+part+'_attempts='+part+'_attempts+? WHERE id=? AND '+part+'=?',
                (int(increment),key,expected))
            return result.rowcount==1

    def finish(self,key,part,state,next_at):
        with self.connect() as db,db:
            db.execute('UPDATE reports SET '+part+'=?,next_at=MAX(next_at,?) WHERE id=?',(state,next_at,key))

    def send(self,key,part,action,now):
        try:action()
        except DeliveryError as error:
            attempts=self.status(key)[part+'_attempts']
            state='unknown' if error.ambiguous else 'failed' if error.permanent or attempts>=3 else 'retry'
            self.finish(key,part,state,now+120000)
        except Exception:self.finish(key,part,'unknown',0)
        else:self.finish(key,part,'sent',0)

    def status(self,key):
        with self.connect() as db:
            row=db.execute('SELECT text,image,text_attempts,image_attempts,next_at FROM reports WHERE id=?',(key,)).fetchone()
            return dict(row)

    def lookup(self,scope,vehicle,period,start_date,end_date):
        if not self.path.exists():return None
        with self.connect() as db:
            row=db.execute('SELECT text,image,next_at FROM reports WHERE id=?',
                           (report_id(scope,vehicle,period,start_date,end_date),)).fetchone()
            return dict(row) if row else None


def demo_report(period='day'):
    values={'day':('2026-10-07','2026-10-07',38.6,3,0,3480,7.8,0,0,1),
            'week':('2026-10-05','2026-10-11',186.4,12,1,15840,35.4,42.1,3620,7),
            'month':('2026-10-01','2026-10-31',428.7,29,3,39060,83.2,112.4,9810,31)}
    start,end,distance,trips,charges,duration,energy,charged,paid,days=values[period]
    return dict(schema_version=1,period=period,start_date=start,end_date=end,demo=True,
        generated_at=day_bounds(end)[1]+8*3600000,vehicle_updated_at=day_bounds(end)[1]-60000,
        metrics=dict(distance_km=distance,trip_count=trips,charge_count=charges,duration_seconds=duration,
                     trip_estimated_kwh=energy,charge_estimated_kwh=charged,charging_paid_cents=paid),
        quality=dict(observed_days=days,elapsed_days=days,archive_limited=False,partial_event_count=0,
                     partial_trip_count=0,missing_distance_count=0,missing_duration_count=0,
                     missing_trip_energy_count=0,missing_charge_energy_count=0,unpriced_bill_count=0,
                     pending_charge_bill_count=0,invalid_event_count=0))


def worker():
    import resource
    try:
        os.nice(10);resource.setrlimit(resource.RLIMIT_CPU,(6,6))
        if sys.platform=='linux':resource.setrlimit(resource.RLIMIT_AS,(128*1024*1024,128*1024*1024))
        raw=sys.stdin.buffer.read(16385)
        if len(raw)>16384:raise ValueError('limit')
        data=json.loads(raw)
        sys.stdout.buffer.write(render_png(data['report'],data['theme']))
    except (ValueError,TypeError,KeyError):sys.stderr.write('input');sys.exit(1)
    except OSError:sys.stderr.write('assets');sys.exit(1)
    except Exception:sys.stderr.write('worker');sys.exit(1)


if __name__=='__main__' and sys.argv[1:]==['--worker']:worker()
