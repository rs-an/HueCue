from pathlib import Path
import json,importlib.util,tempfile
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from design_palette import load_image,extract,render,lab
import argparse
p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,required=True);p.add_argument('--extra-image',type=Path);args=p.parse_args()
repo=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('old',repo/'scripts/extract.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
out=Path(tempfile.mkdtemp(prefix='palette-benchmark-',dir=args.output_root.resolve(strict=True)));report=[];tiles=[]
cases=[('landscape',repo/'examples/inputs/landscape.png','content'),('portrait',repo/'examples/inputs/portrait.png','content'),('illustration',repo/'examples/inputs/illustration.jpg','content'),('interface',repo/'examples/inputs/interface.png','ui')]
if args.extra_image: cases.append(('extra',args.extra_image,'content'))
for name,path,mode in cases:
 im=load_image(path);colors=extract(im,mode)
 # Equal-size baseline: selection quality, not a larger palette budget.
 baseline=old.extract(path,len(colors),mode='ui' if mode=='ui' else 'general')
 render(im,colors,name.upper()+' / NEW').save(out/f'{name}-new.png')
 render(im,baseline,name.upper()+' / CURRENT').save(out/f'{name}-old.png')
 reduced=im.resize((round(im.width*.8),round(im.height*.8)),Image.Resampling.LANCZOS)
 other=extract(reduced,mode,count=len(colors))
 d=np.linalg.norm(lab([c['rgb'] for c in colors])[:,None,:]-lab([c['rgb'] for c in other])[None,:,:],axis=2)
 matched=[];rest=d.copy()
 for _ in range(min(d.shape)):
  i,j=np.unravel_index(np.argmin(rest),rest.shape);matched.append(float(rest[i,j]));rest[i,:]=np.inf;rest[:,j]=np.inf
 report.append({'case':name,'mode':mode,'colors':colors,'baseline':baseline,'resize_mean_deltaE76_greedy':round(float(np.mean(matched)),2),'resize_max_deltaE76_greedy':round(max(matched),2)})
 tile=Image.new('RGB',(1200,390),'#F8F7FC');dr=ImageDraw.Draw(tile)
 thumb=im.copy();thumb.thumbnail((360,300));tile.paste(thumb,(20,60+(300-thumb.height)//2),thumb)
 dr.text((20,15),name.upper(),font=ImageFont.load_default(size=24),fill='#25223B')
 for row,(label,items) in enumerate([('CURRENT',baseline),('EXPERIMENT',colors)]):
  y=70+row*150;dr.text((410,y-26),label,font=ImageFont.load_default(size=17),fill='#656176')
  for i,c in enumerate(items):
   x=410+i*760/len(items);w=760/len(items)-5
   dr.rectangle((x,y,x+w,y+75),fill=c['hex']);dr.text((x,y+84),c['hex'],font=ImageFont.load_default(size=12),fill='#25223B')
 tiles.append(tile);print(name,len(colors),report[-1]['resize_mean_deltaE76_greedy'],flush=True)
board=Image.new('RGB',(1200,len(tiles)*390),'#F8F7FC')
for i,t in enumerate(tiles):board.paste(t,(0,i*390))
board.save(out/'comparison.png');(out/'results.json').write_text(json.dumps(report,indent=2));print(out)
