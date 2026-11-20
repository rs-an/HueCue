"""Offline raster palette extraction. No network, shell, browser or executable exports."""
import argparse
import io
import json
import colorsys
from collections import Counter
import os
from pathlib import Path
import stat
import tempfile
import warnings
from PIL import Image, ImageDraw, ImageFont, ImageOps

MAX_BYTES = 25 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000
warnings.simplefilter('error', Image.DecompressionBombWarning)


def lab(rgb):
    c = [v / 255 for v in rgb]
    r, g, b = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in c]
    xyz = [(r*.4124564+g*.3575761+b*.1804375)/.95047,
           r*.2126729+g*.7151522+b*.072175,
           (r*.0193339+g*.119192+b*.9503041)/1.08883]
    x,y,z = [v ** (1/3) if v > .008856 else 7.787*v+16/116 for v in xyz]
    return (116*y-16,500*(x-y),200*(y-z))


def distance(a,b):
    return sum((x-y)**2 for x,y in zip(a,b))


def ui_palette(pixels, count):
    histogram = Counter(pixels)
    # Exact sampled colors preserve flat UI surfaces instead of averaging them.
    candidates = [(n, rgb, lab(rgb)) for rgb,n in histogram.items()
                  if n >= max(3, len(pixels)*.00002)]
    candidates.sort(key=lambda v:(-v[0],v[1]))
    neutral = [v for v in candidates if (v[2][1]**2+v[2][2]**2)**.5 < 12]
    chosen = []
    for v in neutral:
        if all(distance(v[2],c[2]) > 2.0**2 for c in chosen):
            chosen.append(v)
        if len(chosen) >= min(2,count): break
    # Keep a text/contrasting neutral when enough slots are available.
    if count >= 5 and chosen:
        contrast = [v for v in neutral if min(distance(v[2],c[2]) for c in chosen)>25**2]
        if contrast: chosen.append(max(contrast,key=lambda v:v[0]))
    hues = {}
    for v in candidates:
        h,sat,value = colorsys.rgb_to_hsv(*(c/255 for c in v[1]))
        chroma=(v[2][1]**2+v[2][2]**2)**.5
        if chroma < 14 or sat < .18: continue
        bucket=int(h*12)%12
        # Prefer flat saturated accents to dark badge backgrounds and antialiasing.
        score=v[0]**.5*chroma*value
        if bucket not in hues or score>hues[bucket][0]: hues[bucket]=(score,v)
    for _,v in sorted(hues.values(),key=lambda x:-x[0]):
        if len(chosen)>=count: break
        if all(distance(v[2],c[2])>10**2 for c in chosen): chosen.append(v)
    for v in candidates:
        if len(chosen)>=count: break
        if all(distance(v[2],c[2])>8**2 for c in chosen): chosen.append(v)
    if not chosen: chosen=[(len(pixels),pixels[0],lab(pixels[0]))]
    populations=[0]*len(chosen)
    # Cache by exact sampled RGB; percentages describe nearest-color groups.
    for rgb,n in histogram.items():
        coord=lab(rgb)
        j=min(range(len(chosen)),key=lambda i:distance(coord,chosen[i][2]))
        populations[j]+=n
    return sorted([{'hex':'#%02X%02X%02X'%v[1], 'rgb':v[1],
                    'percent':round(100*n/len(pixels),2)}
                   for v,n in zip(chosen,populations)],key=lambda v:-v['percent'])


def extract(path, count, *, include_source=False, mode="general"):
    # Open once, reject symlinks, devices and oversized input before decoding.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            raise ValueError('Input must be a regular image file, at most 25 MiB')
        raw = f.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:
        raise ValueError('Image exceeds 25 MiB')
    with Image.open(io.BytesIO(raw), formats=['JPEG','PNG','WEBP']) as src:
        if getattr(src,'n_frames',1) != 1:
            raise ValueError('Animated images are not supported')
        src.load()
        # Respect embedded ICC profiles instead of silently treating them as sRGB.
        icc = src.info.get('icc_profile')
        im = ImageOps.exif_transpose(src).convert('RGBA')
        if icc:
            from PIL import ImageCms
            alpha = im.getchannel('A')
            im = ImageCms.profileToProfile(im.convert('RGB'),ImageCms.ImageCmsProfile(io.BytesIO(icc)),ImageCms.createProfile('sRGB'),outputMode='RGB').convert('RGBA')
            im.putalpha(alpha)
        source_preview = im.copy() if include_source else None
        if source_preview is not None:
            source_preview.thumbnail((640,640), Image.Resampling.LANCZOS)
        im.thumbnail((768,768) if mode == "ui" else (256,256),
                     Image.Resampling.NEAREST if mode == "ui" else Image.Resampling.LANCZOS)
        pixels = [(r,g,b) for r,g,b,a in im.get_flattened_data() if a>=128]
    if not pixels:
        raise ValueError('No visible pixels')
    if mode == 'ui':
        colors = ui_palette(pixels, count)
        return (colors, source_preview) if include_source else colors
    strip = Image.new('RGB',(len(pixels),1)); strip.putdata(pixels)
    q = strip.quantize(colors=256,method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    bins = [(n,tuple(pal[i*3:i*3+3])) for n,i in q.getcolors()]
    bins.sort(key=lambda x:(-x[0],x[1]))
    coords = [lab(rgb) for _,rgb in bins]
    chosen = [0]
    # Weighted perceptual diversity retains small, distinctive accents.
    while len(chosen)<min(count,len(bins)):
        scores = [(min(distance(c,coords[j]) for j in chosen)*bins[i][0]**.35,i)
                  for i,c in enumerate(coords) if i not in chosen]
        score,i = max(scores)
        if score < 1e-9: break
        chosen.append(i)
    centers = [coords[i] for i in chosen]
    for _ in range(20):
        groups = [[] for _ in centers]
        for i,item in enumerate(bins):
            j = min(range(len(centers)),key=lambda j:distance(coords[i],centers[j]))
            groups[j].append(item)
        updated = []
        for j,group in enumerate(groups):
            n = sum(p for p,_ in group)
            updated.append(tuple(sum(p*lab(c)[k] for p,c in group)/n for k in range(3)) if n else centers[j])
        if max(distance(a,b) for a,b in zip(centers,updated)) < .001: break
        centers = updated
    result=[]
    for group in groups:
        if not group: continue
        n=sum(p for p,_ in group)
        rgb=tuple(round(sum(p*c[k] for p,c in group)/n) for k in range(3))
        result.append({'hex':'#%02X%02X%02X'%rgb,'rgb':rgb,'percent':round(100*n/len(pixels),2)})
    colors = sorted(result,key=lambda v:-v['percent'])
    return (colors, source_preview) if include_source else colors


def preview(colors, source):
    im = Image.new('RGB', (1200, 800), '#F8F7FC')
    d = ImageDraw.Draw(im)
    title = ImageFont.load_default(size=27)
    font = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=16)
    d.text((32, 24), 'IMAGE / PALETTE', font=title, fill='#25223B')
    d.text((720, 68), f'{len(colors)} EXTRACTED COLORS', font=small, fill='#656176')
    # Checkerboard only under actual transparent pixels, never in margins.
    panel = Image.new('RGB', source.size, '#F8F7FC')
    if source.getchannel('A').getextrema()[0] < 255:
        checker = ImageDraw.Draw(panel)
        for y in range(0,source.height,20):
            for x in range(0,source.width,20):
                if (x//20+y//20)%2: checker.rectangle((x,y,x+19,y+19),fill='#EEEAF3')
    panel.paste(source,(0,0),source)
    im.paste(panel,(32+(640-source.width)//2,100+(640-source.height)//2))
    row_h = 640 / len(colors)
    for i,c in enumerate(colors):
        y = 100 + i*row_h
        swatch_h = min(76, row_h-16)
        d.rounded_rectangle((720,y,816,y+swatch_h),radius=10,fill=c['hex'])
        d.text((836,y+3),c['hex'],font=font,fill='#25223B')
        d.text((1168,y+5),f"{c['percent']:.2f}%",font=small,fill='#656176',anchor='ra')
        d.text((836,y+34),'RGB '+', '.join(map(str,c['rgb'])),font=small,fill='#656176')
    return im


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image',type=Path);p.add_argument('--colors',type=int,default=None,choices=range(2,9))
    p.add_argument('--mode',choices=['general','ui'],default='general')
    p.add_argument('--output-root',type=Path,required=True)
    a=p.parse_args()
    colors, source = extract(a.image,a.colors or (8 if a.mode == "ui" else 6), include_source=True, mode=a.mode)
    root=a.output_root.resolve(strict=True)
    if not root.is_dir(): raise ValueError('Output root must be an existing directory')
    out=Path(tempfile.mkdtemp(prefix='palette-',dir=root))
    data={'mode':a.mode,'method':('UI neutral surfaces and hue accents; nearest Lab shares' if a.mode == 'ui' else '256-bin median cut, weighted Lab clustering, diversity initialization'),'approximate':True,'alpha_threshold':128,'colors':colors}
    (out/'palette.json').write_text(json.dumps(data,indent=2)+'\n')
    (out/'palette.css').write_text(':root {\n'+''.join(f"  --palette-{i+1}: {c['hex']};\n" for i,c in enumerate(colors))+'}\n')
    preview(colors, source).save(out/'palette.png')
    print(json.dumps({'folder':str(out),**data},indent=2))

if __name__=='__main__':
    try: main()
    except (ValueError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as e:
        raise SystemExit(f'Palette error: {e}')
