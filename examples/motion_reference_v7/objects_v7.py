"""Reference binding for reusable Blender target/arrow and metal aperture rigs.

The Blender source is in visual_fidelity.blender_motion_objects. PNGs are physical
Cycles renders, not generated illustrations. Compositing preserves real alpha.
The approved engraving is reused unchanged and clipped by the aperture mask.
"""
from pathlib import Path
from functools import lru_cache
import json,math,sys
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFilter
import arte as a
import efeitos as fx
ROOT=Path(__file__).resolve().parent
ASSETS=ROOT/'hybrid/v7-objects'
ENGINE=ROOT/'engine'
if not ENGINE.exists():ENGINE=ROOT.parent/'motor-v7'
sys.path.insert(0,str(ENGINE))
from visual_fidelity.blender_motion_objects import keyhole_outline

@lru_cache(maxsize=100)
def render_asset(kind,index):
    image=Image.open(ASSETS/kind/f'{index:04d}.png').convert('RGBA')
    # Mild spatial denoise of premultiplied radiance; no opaque black fringe.
    p=np.asarray(image,dtype=np.float32)/255;alpha=p[:,:,3:4];p[:,:,:3]*=alpha
    p=cv2.GaussianBlur(p,(3,3),.5)
    p[:,:,:3]/=np.maximum(p[:,:,3:4],1e-5)
    return Image.fromarray(np.uint8(np.clip(p,0,1)*255))

def target_layer(frame, *, center=None, scale=1., angle=0.):
    """Target and arrow keep independent internal motion; this is their group transform."""
    out=Image.new('RGBA',(720,1280))
    if not 752<=frame<799:return out
    index=frame-752+1
    p=a.progress(frame,751,6)
    cx,cy=center or a.pose(frame,[(752,354,774),(765,357,771),(783,359,776),(798,358,776)])
    a.put(out,render_asset('target',index),cx,cy,scale*(.72+.18*p),angle=angle,alpha=p)
    return out

@lru_cache(maxsize=1)
def aperture_mask():
    recipe=json.loads((ASSETS/'keyhole/recipe.json').read_text())
    pts=recipe['_aperture'];w,h=recipe['resolution'];ortho=recipe['ortho_scale']
    # Orthographic camera's vertical span in this portrait raster.
    pix=[(w/2+x*h/ortho,h/2-y*h/ortho)for x,y in pts]
    im=Image.new('L',(w*3,h*3));ImageDraw.Draw(im).polygon([(round(x*3),round(y*3))for x,y in pix],fill=255)
    im=im.resize((800,1100),Image.Resampling.LANCZOS)
    full=Image.new('L',(720,1280));full.paste(im,(-40,50));return full

def render_keyhole(frame,ev):
    plate=fx.studio((17,12,6),(7,5,3)).copy()
    x,y,scale=a.pose(frame,[(846,356,700,1.15),(853,358,640,1.02),(866,347,700,.95),(875,373,1390,.75),(883,456,1800,.65)])
    image=a.spatial_asset('engraving-vector.png').resize((720,1280),fx.LANCZOS).copy()
    mask=aperture_mask();alpha=np.array(image.getchannel('A'),dtype=np.float32)*np.array(mask,dtype=np.float32)/255
    image.putalpha(Image.fromarray(np.uint8(alpha)))
    ring=render_asset('keyhole',min(37,max(1,frame-846+1))).copy()
    # Match the reference's grazing side/base illumination; retain the animated physical reflection.
    pixels=np.asarray(ring,dtype=np.float32).copy();yy,xx=np.mgrid[:ring.height,:ring.width]
    side=np.abs((xx-ring.width/2)/(ring.width/2))
    envelope=np.clip(.18+.7*side**2+.9*np.exp(-((yy/ring.height-.95)/.05)**2),0,1)
    pixels[:,:,3]*=envelope
    ring=Image.fromarray(np.uint8(pixels)).resize((800,1100),fx.LANCZOS).filter(ImageFilter.GaussianBlur(3.2))
    # Gold reflections come from the animated physical area light; modest bloom is optical finish.
    aura=ring.filter(ImageFilter.GaussianBlur(20));aura.putalpha(aura.getchannel('A').point(lambda v:round(v*.85)))
    image.alpha_composite(aura,(-40,50));image.alpha_composite(ring,(-40,50))
    opacity=1-a.progress(frame,ev.get('saida',879),7)
    a.put(plate,image,x,y,scale,alpha=opacity,blur=max(0,(frame-ev.get('queda',866))*.22))
    return plate
