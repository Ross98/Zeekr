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
    def image(self,x1,y1,x2,y2,image):
        width,height,pixels=_decode_png(image)
        for y in range(y1,y2):
            sy=min(height-1,int((y-y1)*height/(y2-y1)))
            for x in range(x1,x2):
                sx=min(width-1,int((x-x1)*width/(x2-x1)))
                source=(sy*width+sx)*3;target=(y*WIDTH+x)*3
                self.data[target:target+3]=pixels[source:source+3]
    def png(self):
        raw=b''.join(b'\0'+bytes(self.data[y*WIDTH*3:(y+1)*WIDTH*3]) for y in range(HEIGHT))
        def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',WIDTH,HEIGHT,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,9))+chunk(b'IEND',b'')

def _number(value,suffix=''):
    return '--' if type(value) not in (int,float) else ('%.1f'%value).rstrip('0').rstrip('.')+suffix

def _decode_png(content):
    if not isinstance(content,bytes) or not content.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('真实地图不是有效 PNG')
    offset=8;compressed=b'';header=None;palette=None
    while offset+12<=len(content):
        length=struct.unpack('>I',content[offset:offset+4])[0];name=content[offset+4:offset+8]
        data=content[offset+8:offset+8+length];offset+=12+length
        if name==b'IHDR':header=struct.unpack('>IIBBBBB',data)
        elif name==b'PLTE':palette=data
        elif name==b'IDAT':compressed+=data
        elif name==b'IEND':break
    if not header:
        raise ValueError('真实地图缺少 PNG 头')
    width,height,depth,color,compression,filtering,interlace=header
    if not 0<width<=2048 or not 0<height<=2048 or depth!=8 or color not in (2,3,6) or compression or filtering or interlace:
        raise ValueError('真实地图 PNG 格式不支持')
    if color==3 and (not palette or len(palette)%3 or len(palette)>768):
        raise ValueError('真实地图 PNG 调色板无效')
    channels=3 if color==2 else 4 if color==6 else 1;stride=width*channels
    try:raw=zlib.decompress(compressed)
    except zlib.error:raise ValueError('真实地图 PNG 数据损坏') from None
    if len(raw)!=(stride+1)*height:raise ValueError('真实地图 PNG 尺寸不符')
    result=bytearray(height*stride);previous=bytearray(stride)
    for y in range(height):
        kind=raw[y*(stride+1)];source=raw[y*(stride+1)+1:(y+1)*(stride+1)];row=bytearray(stride)
        for i,value in enumerate(source):
            left=row[i-channels] if i>=channels else 0;up=previous[i];upper_left=previous[i-channels] if i>=channels else 0
            if kind==0:predictor=0
            elif kind==1:predictor=left
            elif kind==2:predictor=up
            elif kind==3:predictor=(left+up)//2
            elif kind==4:
                p=left+up-upper_left;pa,pb,pc=abs(p-left),abs(p-up),abs(p-upper_left)
                predictor=left if pa<=pb and pa<=pc else up if pb<=pc else upper_left
            else:raise ValueError('真实地图 PNG 滤镜不支持')
            row[i]=(value+predictor)&255
        result[y*stride:(y+1)*stride]=row;previous=row
    if color==2:return width,height,result
    rgb=bytearray(width*height*3)
    if color==6:
        for index in range(width*height):rgb[index*3:index*3+3]=result[index*4:index*4+3]
    else:
        for index,value in enumerate(result):
            start=value*3
            if start+3>len(palette):raise ValueError('真实地图 PNG 调色板索引无效')
            rgb[index*3:index*3+3]=palette[start:start+3]
    return width,height,rgb

def render_trip_png(report,route,map_image):
    canvas=Canvas();canvas.text(56,42,'TRIP REPORT',7,COLORS['white'])
    if report.get('partial'):canvas.text(820,52,'PARTIAL',4,COLORS['orange'])
    try:canvas.image(56,118,1012,420,map_image)
    except ValueError as exc:raise ValueError('真实地图不可用：%s'%exc) from None
    metrics,start,end=report.get('metrics',{}),report.get('start',{}),report.get('end',{})
    duration=metrics.get('duration_seconds');cards=[('DISTANCE',_number(metrics.get('distance_km'),' KM')),('DURATION',_number(duration/60 if type(duration) in (int,float) else None,' MIN')),('SOC','%s-%s'%(_number(start.get('soc'),'%'),_number(end.get('soc'),'%'))),('ENERGY',_number(metrics.get('estimated_kwh_100km'),' KWH/100KM'))]
    for index,(label,value) in enumerate(cards):
        x=56+index*239;canvas.rect(x,454,x+224,652,COLORS['card']);canvas.text(x+20,480,label,3,COLORS['muted']);canvas.text(x+20,545,value,2 if len(value)>12 else 5,COLORS['white'])
    canvas.text(56,682,'CLOUD CACHE - VALID SAMPLES ONLY',3,COLORS['muted']);content=canvas.png()
    if len(content)>2*1024*1024:raise ValueError('行程图片超过2MB')
    return content
