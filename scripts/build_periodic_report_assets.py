"""Build only: Pillow + supplied licensed font. Runtime uses premixed RGB glyphs."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import zlib

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from zeekr_control.periodic_report import WIDTH, HEIGHT, PALETTES, TITLES

ROLES = {'date':(33,'muted'), 'small':(30,'muted'), 'warning':(27,'warning'),
         'distance':(120,'accent'), 'distance_small':(90,'accent'), 'distance_tiny':(66,'accent'),
         'unit':(36,'muted'), 'value':(42,'ink'), 'value_small':(30,'ink')}
CHARACTERS = ''.join(sorted(set('0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ/–—:.% ·万元分钟趟行程次充电部分里估算耗观测时长入实付车辆未记录生成天有采样暂无已结束汇总数据费用待补录演示')))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font',required=True,type=Path)
    parser.add_argument('--font-index',default=0,type=int)
    parser.add_argument('--output',default=Path('zeekr_control/assets/periodic-report'),type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    def font(size):
        face=ImageFont.truetype(str(args.font),size,index=args.font_index)
        if args.font.name=='NotoSansSC.ttf':face.set_variation_by_axes([500])
        return face
    manifest=dict(version=1,width=WIDTH,height=HEIGHT,font_sha256=hashlib.sha256(args.font.read_bytes()).hexdigest(),
                  font_index=args.font_index,roles=ROLES,files={})
    def save(name,data):
        (args.output/name).write_bytes(data);manifest['files'][name]=hashlib.sha256(data).hexdigest()
    for theme,palette in PALETTES.items():
        index={};pixels=bytearray()
        for role,(size,color) in ROLES.items():
            face=font(size)
            # Preserve a shared baseline: trimming each glyph independently lifts
            # decimal points and dashes to the top of a numeral.
            _,top,_,bottom=face.getbbox(CHARACTERS,anchor='la')
            height=bottom-top+2
            for char in CHARACTERS:
                advance=math.ceil(face.getlength(char))
                glyph=Image.new('RGB',(advance,height),palette['paper'])
                ImageDraw.Draw(glyph).text((0,-top),char,font=face,fill=palette[color],anchor='la')
                raw=glyph.tobytes();index[role+':'+char]=[len(pixels),advance,height,advance];pixels.extend(raw)
        encoded=json.dumps(index,separators=(',',':')).encode()
        save('glyphs-'+theme+'.zlib',zlib.compress(struct.pack('>I',len(encoded))+encoded+pixels,9))
        for period,title in TITLES.items():
            canvas=Image.new('RGB',(WIDTH,HEIGHT),palette['paper']);draw=ImageDraw.Draw(canvas)
            draw.text((50,48),title,font=font(44),fill=palette['ink'],anchor='lt')
            for i,label in enumerate(('估算耗电','观测时长','估算充入','充电实付')):
                draw.text((500+(i%2)*267,141+(i//2)*122),label,font=font(33),fill=palette['muted'],anchor='lt')
            save(period+'-'+theme+'.rgb.zlib',zlib.compress(canvas.tobytes(),9))
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
