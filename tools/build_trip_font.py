from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
import json,zlib,struct,shutil
import argparse
parser=argparse.ArgumentParser(description='Offline Noto Sans SC glyph atlas builder; Pillow required only here.')
parser.add_argument('--font',required=True)
parser.add_argument('--license',required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parent.parent/'zeekr_control/assets/trip-font';root.mkdir(parents=True,exist_ok=True);fontpath=Path(args.font)
labels='里.:,?…时间区域无©行程结束记录片段月日观测时长分钟电量估算能耗云端缓存采样个位置点处间断连线不代表实走道路首末起名称未北地图已旋转背景无本区域版权贡献者名称待确认路网推断虚线为采样连线·→—：，。%/0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ()'
index={};raw=bytearray()
for size in [12,13,15,17,18,21,35,40,42]:
 f=ImageFont.truetype(str(fontpath),size);f.set_variation_by_axes([650 if size==40 else 550 if size in (35,42) else 400]);chars=set(labels)
 if size==18:chars.update(chr(c) for c in range(0x4e00,0xa000));chars.update(chr(c) for c in range(0x3000,0x3040));chars.update(chr(c) for c in range(0xff01,0xff60))
 for char in sorted(chars):
  bbox=f.getbbox(char,anchor='lt');w=max(1,bbox[2]-bbox[0]);h=max(1,bbox[3]-bbox[1]);im=Image.new('L',(w,h));ImageDraw.Draw(im).text((-bbox[0],-bbox[1]),char,font=f,fill=255,anchor='lt');mask=im.tobytes();index[str(size)+':'+char]=[len(raw),w,h,round(f.getlength(char),2)];raw.extend(mask)
 meta=json.dumps(index,ensure_ascii=False,separators=(',',':')).encode();payload=struct.pack('>I',len(meta))+meta+raw
(root/'glyphs.zlib').write_bytes(zlib.compress(payload,9));shutil.copy(args.license,root/'OFL.txt');(root/'README.md').write_text('Noto Sans SC glyph masks. SIL OFL 1.1; see OFL.txt.\nSource: https://github.com/google/fonts/tree/main/ofl/notosanssc\nGenerated offline with Pillow; runtime uses Python standard library only.\n18px supports CJK U+4E00..U+9FFF and common punctuation. Other sizes cover fixed report text and numbers.\n')
print('ATLAS',len(index),'glyphs',len(payload),'raw bytes', (root/'glyphs.zlib').stat().st_size,'compressed bytes')
