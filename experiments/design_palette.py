"""Experimental design-oriented selection. No per-image parameters or hue quotas."""
import argparse
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import warnings
import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps

Image.MAX_IMAGE_PIXELS = 20_000_000
warnings.simplefilter('error', Image.DecompressionBombWarning)


# Reuse the production decoder and platform-specific input safeguards.
import importlib.util
_spec = importlib.util.spec_from_file_location('huecue_core', Path(__file__).resolve().parents[1] / 'scripts/extract.py')
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)
load_image = _core.load_image


def lab(rgb):
    v = np.asarray(rgb, dtype=float)/255
    v = np.where(v <= .04045, v/12.92, ((v+.055)/1.055)**2.4)
    xyz = v @ np.array([[.4124564,.2126729,.0193339],[.3575761,.7151522,.119192],[.1804375,.072175,.9503041]])
    xyz /= np.array([.95047,1,1.08883])
    f = np.where(xyz > .008856, np.cbrt(xyz), 7.787*xyz+16/116)
    return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],axis=-1)


def extract(im, mode='content', count=None):
    sample = im.copy()
    sample.thumbnail((640,640), Image.Resampling.NEAREST)
    rgba = np.asarray(sample)
    visible = rgba[:,:,3] >= 128
    if not visible.any(): raise ValueError('No visible pixels')
    rgb = rgba[:,:,:3].copy()
    # Hidden RGB must not consume quantizer capacity.
    rgb[~visible] = rgb[visible][0]
    quant = Image.fromarray(rgb).quantize(colors=128 if mode=='content' else 256, method=Image.Quantize.MEDIANCUT)
    ids = np.asarray(quant)
    centers = np.array(quant.getpalette(),dtype=np.uint8).reshape(-1,3)
    hist = np.bincount(ids[visible],minlength=len(centers)).astype(float)
    used = np.flatnonzero(hist)
    representatives = []
    for i in used:
        values, freq = np.unique(rgb[(ids==i)&visible],axis=0,return_counts=True)
        if mode=='ui': chosen = np.argmax(freq)
        else: chosen = np.argmin(np.sum((lab(values)-lab(centers[i]))**2,axis=1))
        representatives.append(values[chosen])
    reps = np.array(representatives)
    coords = lab(reps)
    pop = hist[used]/hist.sum()
    # Neighborhood support discounts isolated pixels and quantization noise.
    supported = np.zeros(ids.shape,bool)
    local = np.zeros(ids.shape,float)
    image_lab = lab(rgb)
    for dy,dx in [(0,1),(1,0),(0,-1),(-1,0)]:
        other = np.roll(image_lab,(dy,dx),(0,1))
        valid = visible & np.roll(visible,(dy,dx),(0,1))
        if dy==1: valid[0]=False
        if dy==-1: valid[-1]=False
        if dx==1: valid[:,0]=False
        if dx==-1: valid[:,-1]=False
        delta=np.linalg.norm(image_lab-other,axis=2)
        supported |= valid & (delta<8)
        local += np.where(valid, np.minimum(delta,40),0)/4
    support=np.array([supported[(ids==i)&visible].mean() for i in used])
    contrast=np.array([local[(ids==i)&visible].mean() for i in used])
    chroma=np.linalg.norm(coords[:,1:],axis=1)
    d=np.linalg.norm(coords[:,None,:]-coords[None,:,:],axis=2)
    if mode=='content':
        # Facility-location objective: cover both pixel area and salient colors.
        interest=pop**.25 * np.minimum(chroma/60,1.5)**2 * support * (1+np.minimum(contrast/20,1))
        interest[(pop<.0003)|(chroma<18)]=0
        # Normalize within hue families: many green/gray bins must not outvote
        # a coherent red accent simply because quantization split them more.
        hue=(np.degrees(np.arctan2(coords[:,2],coords[:,1]))+360)%360
        # Continuous circular hue density avoids hard color-family boundaries.
        angle=np.abs(hue[:,None]-hue[None,:])
        angle=np.minimum(angle,360-angle)
        affinity=np.exp(-.5*(angle/12)**2)
        density=affinity @ interest
        balanced=interest/np.maximum(density,1e-12)**.75
        weights=.50*pop+.50*balanced/max(balanced.sum(),1e-12)
        similarity=np.exp(-(d/18)**2)
        min_distance=10
        limit=count or 8
    else:
        # Exact repeated fills matter even when neutral and visually close.
        interest=np.sqrt(pop)*support*(1+np.minimum(chroma/40,2))
        weights=.35*pop+.65*interest/max(interest.sum(),1e-12)
        similarity=np.exp(-(d/4)**2)
        min_distance=2
        limit=count or 16
    selected=[]; coverage=np.zeros(len(used)); gains=[]
    eligible=(pop>=.0003)&(support>=.2)
    if not eligible.any():eligible[:]=True
    for _ in range(min(limit,len(used))):
        gain=((np.maximum(coverage[None,:],similarity)-coverage)*weights).sum(axis=1)
        gain[~eligible]=-1
        if selected:
            gain[np.min(d[:,selected],axis=1)<min_distance]=-1
        j=int(gain.argmax())
        if gain[j]<=0:break
        if mode=='ui' and count is None and selected and gain[j]<.008:break
        selected.append(j);gains.append(float(gain[j]));coverage=np.maximum(coverage,similarity[j])
    assignments=np.argmin(d[:,selected],axis=1)
    result=[]
    for k,j in enumerate(selected):
        c=tuple(map(int,reps[j]))
        result.append({'hex':'#%02X%02X%02X'%c,'rgb':c,'group_percent':round(float(pop[assignments==k].sum()*100),2),'candidate_percent':round(float(pop[j]*100),3),'selection_gain':round(gains[k],5)})
    return result


def render(im, colors, title):
    height=max(800,150+len(colors)*78)
    canvas=Image.new('RGB',(1200,height),'#F8F7FC');draw=ImageDraw.Draw(canvas)
    draw.text((32,24),title,font=ImageFont.load_default(size=26),fill='#25223B')
    source=im.copy();source.thumbnail((640,min(height-140,820)))
    canvas.paste(source,(32+(640-source.width)//2,100+(height-140-source.height)//2),source)
    step=(height-140)/len(colors)
    for i,c in enumerate(colors):
        y=100+i*step
        draw.rounded_rectangle((720,y,816,y+min(64,step-12)),radius=10,fill=c['hex'])
        draw.text((838,y+4),c['hex'],font=ImageFont.load_default(size=22),fill='#25223B')
        draw.text((838,y+35),'RGB '+', '.join(map(str,c['rgb'])),font=ImageFont.load_default(size=15),fill='#656176')
    return canvas


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image',type=Path);p.add_argument('--mode',choices=['content','ui'],default='content');p.add_argument('--colors',type=int,choices=range(2,17));p.add_argument('--output-root',type=Path,required=True)
    a=p.parse_args();im=load_image(a.image);colors=extract(im,a.mode,a.colors)
    out=Path(tempfile.mkdtemp(prefix='design-',dir=a.output_root.resolve(strict=True)))
    render(im,colors,'DESIGN PALETTE / EXPERIMENT').save(out/'palette.png')
    (out/'palette.json').write_text(json.dumps({'mode':a.mode,'colors':colors},indent=2))
    print(json.dumps({'folder':str(out),'colors':colors}))
if __name__=='__main__':main()
