"""Reference binding: shared parent for amount, complete captions and 3D rig."""
import engine_bootstrap
from pathlib import Path
from functools import lru_cache
import math
from PIL import Image,ImageFont,ImageFilter
import arte as a
from typography_v7 import render_value_arc
from objects_v7 import target_layer
from visual_fidelity.type_layout import text_mask
from visual_fidelity.motion_layers import compose_group,Transform
from visual_fidelity.light_sweep import light_sweep,Sweep
ROOT=Path(__file__).parent
SIZE=(720,1280)

@lru_cache(maxsize=10)
def font(kind,size):
    if kind=='number':return ImageFont.truetype(str(ROOT/'fonts/Anton.ttf'),size)
    f=ImageFont.truetype(str(ROOT/'fonts/Montserrat-Variable.ttf'),size)
    f.set_variation_by_axes([800 if kind=='bold' else 450]);return f

def label(word,kind,dimensions,color,center,angle,opacity=1,sweep_phase=None):
    mask=text_mask(word,font(kind,150),padding=3).resize(dimensions,Image.Resampling.LANCZOS)
    im=Image.new('RGBA',dimensions,color);im.putalpha(mask)
    if sweep_phase is not None:im=light_sweep(im,sweep_phase,Sweep(width=.16,intensity=.48))
    im=im.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True)
    out=Image.new('RGBA',SIZE)
    if opacity<1:im.putalpha(im.getchannel('A').point(lambda v:round(v*opacity)))
    out.alpha_composite(im,(round(center[0]-im.width/2),round(center[1]-im.height/2)))
    return out

def render_value(frame,ev):
    plate=a.spatial_asset('room_cream.png').copy()
    a.put(plate,a.chair(),371,882,1.79)
    # Dark lower region remains on the plate, never over the white captions.
    from cenas import floor
    plate.alpha_composite(floor())
    plate=a.camera(plate,1+.09*a.progress(frame,722,10),-23*a.progress(frame,725,12),0,8*(1-a.progress(frame,722,10)))
    plate.alpha_composite(render_value_arc(frame))
    p=a.progress(frame,ev['numero'],15)
    number='$'+f'{round(1000000*p):,}'.replace(',','.')
    layers=[]
    if p:
        layers.append((label(number,'number',(min(674,80*len(number)),151),(255,255,253),(355,902),10,p),Transform()))
    for word,kind,dim,pos,start in [
        ('reklama','bold',(504,98),(386,996),753),
        ('budjetini','regular',(462,85),(410,1078),761),
        ('boshqarganman','regular',(501,58),(411,1157),781)]:
        alpha=a.progress(frame,start,7)
        if alpha:layers.append((label(word,kind,dim,(215,0,9)if kind=='bold'else(255,255,253),pos,10,alpha,
                                     (frame-757)/27 if kind=='bold'else None),Transform()))
    layers.append((target_layer(frame,center=(345,800),scale=1.25),Transform()))
    # All children inherit the same subtle group motion; the arrow has its own rig.
    parent=Transform(x=-4*math.sin((frame-752)/14),y=2*math.sin((frame-752)/11),
                     angle=.8*math.sin((frame-752)/18),pivot=(360,920))
    plate.alpha_composite(compose_group(SIZE,layers,parent))
    flash=1-a.progress(frame,721,3)
    return Image.blend(plate,Image.new('RGBA',SIZE,'white'),flash*.95) if flash else plate
