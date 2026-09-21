"""Dependency-free, bounded trip summary PNG for WeCom."""
import struct
import zlib

WIDTH, HEIGHT = 1068, 720
COLORS = {'background':(11,17,24),'panel':(23,32,43),'card':(21,30,40),'white':(255,255,255),
          'muted':(142,160,181),'green':(0,214,180),'orange':(255,177,78)}
FONT = {
 'A':('01110','10001','10001','11111','10001','10001','10001'),'C':('01111','10000','10000','10000','10000','10000','01111'),
 'D':('11110','10001','10001','10001','10001','10001','11110'),'E':('11111','10000','10000','11110','10000','10000','11111'),
 'G':('01111','10000','10000','10111','10001','10001','01111'),'I':('11111','00100','00100','00100','00100','00100','11111'),
 'H':('10001','10001','10001','11111','10001','10001','10001'),
 'K':('10001','10010','10100','11000','10100','10010','10001'),'L':('10000','10000','10000','10000','10000','10000','11111'),
 'M':('10001','11011','10101','10101','10001','10001','10001'),'N':('10001','11001','10101','10011','10001','10001','10001'),
 'O':('01110','10001','10001','10001','10001','10001','01110'),'P':('11110','10001','10001','11110','10000','10000','10000'),
 'R':('11110','10001','10001','11110','10100','10010','10001'),'S':('01111','10000','10000','01110','00001','00001','11110'),
 'T':('11111','00100','00100','00100','00100','00100','00100'),'U':('10001','10001','10001','10001','10001','10001','01110'),
 'V':('10001','10001','10001','10001','10001','01010','00100'),'Y':('10001','10001','01010','00100','00100','00100','00100'),
 '0':('01110','10001','10011','10101','11001','10001','01110'),'1':('00100','01100','00100','00100','00100','00100','01110'),
 '2':('01110','10001','00001','00010','00100','01000','11111'),'3':('11110','00001','00001','01110','00001','00001','11110'),
 '4':('00010','00110','01010','10010','11111','00010','00010'),'5':('11111','10000','10000','11110','00001','00001','11110'),
 '6':('01110','10000','10000','11110','10001','10001','01110'),'7':('11111','00001','00010','00100','01000','01000','01000'),
 '8':('01110','10001','10001','01110','10001','10001','01110'),'9':('01110','10001','10001','01111','00001','00001','01110'),
 '.':('00000','00000','00000','00000','00000','00110','00110'),'-':('00000','00000','00000','11111','00000','00000','00000'),
 '%':('11001','11010','00100','01000','10110','00110','00000'),'/':('00001','00010','00100','01000','10000','00000','00000'),' ':('00000',)*7}

class Canvas:
    def __init__(self): self.data=bytearray(COLORS['background']*(WIDTH*HEIGHT))
    def rect(self,x1,y1,x2,y2,color):
        x1,x2=max(0,int(x1)),min(WIDTH,int(x2));y1,y2=max(0,int(y1)),min(HEIGHT,int(y2));row=bytes(color)*(x2-x1)
        for y in range(y1,y2):
            offset=(y*WIDTH+x1)*3;self.data[offset:offset+len(row)]=row
    def circle(self,cx,cy,r,color):
        for y in range(int(cy-r),int(cy+r+1)):
            width=int(max(0,r*r-(y-cy)*(y-cy))**.5);self.rect(cx-width,y,cx+width+1,y+1,color)
    def line(self,a,b,color,width=7):
        x1,y1=a;x2,y2=b;steps=max(1,int(max(abs(x2-x1),abs(y2-y1))))
        for i in range(steps+1):
            ratio=i/steps;self.circle(x1+(x2-x1)*ratio,y1+(y2-y1)*ratio,width/2,color)
    def text(self,x,y,value,scale,color):
        cursor=int(x)
        for character in str(value).upper():
            for row,bits in enumerate(FONT.get(character,FONT[' '])):
                for column,bit in enumerate(bits):
                    if bit=='1':self.rect(cursor+column*scale,y+row*scale,cursor+(column+1)*scale,y+(row+1)*scale,color)
            cursor+=6*scale
    def png(self):
        raw=b''.join(b'\0'+bytes(self.data[y*WIDTH*3:(y+1)*WIDTH*3]) for y in range(HEIGHT))
        def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',WIDTH,HEIGHT,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,9))+chunk(b'IEND',b'')

def _number(value,suffix=''):
    return '--' if type(value) not in (int,float) else ('%.1f'%value).rstrip('0').rstrip('.')+suffix

def _route(canvas,route,box):
    segments=[];points=[]
    for segment in route.get('segments',[]):
        valid=[(p.get('longitude'),p.get('latitude')) for p in segment if type(p.get('longitude')) in (int,float) and type(p.get('latitude')) in (int,float)]
        if valid:segments.append(valid);points.extend(valid)
    canvas.rect(*box,COLORS['panel'])
    if len(points)<2:return
    left,top,right,bottom=box;xs=[p[0] for p in points];ys=[p[1] for p in points];dx=max(xs)-min(xs) or 1;dy=max(ys)-min(ys) or 1;margin=42
    def xy(p):return (left+margin+(p[0]-min(xs))/dx*(right-left-2*margin),bottom-margin-(p[1]-min(ys))/dy*(bottom-top-2*margin))
    for segment in segments:
        for a,b in zip(segment,segment[1:]):canvas.line(xy(a),xy(b),COLORS['green'])
    canvas.circle(*xy(points[0]),12,COLORS['white']);canvas.circle(*xy(points[-1]),14,COLORS['orange'])

def render_trip_png(report,route):
    canvas=Canvas();canvas.text(56,42,'TRIP REPORT',7,COLORS['white'])
    if report.get('partial'):canvas.text(820,52,'PARTIAL',4,COLORS['orange'])
    _route(canvas,route,(56,118,1012,420));metrics,start,end=report.get('metrics',{}),report.get('start',{}),report.get('end',{})
    duration=metrics.get('duration_seconds');cards=[('DISTANCE',_number(metrics.get('distance_km'),' KM')),('DURATION',_number(duration/60 if type(duration) in (int,float) else None,' MIN')),('SOC','%s-%s'%(_number(start.get('soc'),'%'),_number(end.get('soc'),'%'))),('ENERGY',_number(metrics.get('estimated_kwh_100km'),' KWH/100KM'))]
    for index,(label,value) in enumerate(cards):
        x=56+index*239;canvas.rect(x,454,x+224,652,COLORS['card']);canvas.text(x+20,480,label,3,COLORS['muted']);canvas.text(x+20,545,value,2 if len(value)>12 else 5,COLORS['white'])
    canvas.text(56,682,'CLOUD CACHE - VALID SAMPLES ONLY',3,COLORS['muted']);content=canvas.png()
    if len(content)>2*1024*1024:raise ValueError('行程图片超过2MB')
    return content
