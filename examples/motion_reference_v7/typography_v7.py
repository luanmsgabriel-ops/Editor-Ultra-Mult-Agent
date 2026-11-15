"""Reference application of the reusable V7 typesetting primitives.

Montserrat Black is a measured visual substitute, not a positively identified
original font. The name is rebuilt as intact font glyphs, never fragments that
already contain the foreground word's occlusion.
"""
from functools import lru_cache
from pathlib import Path
import math, json
import cv2
import numpy as np
from PIL import Image,ImageFont,ImageDraw,ImageFilter
from visual_fidelity.type_layout import (LetteringLayer,LetteringProvenance,
    compose_layers,text_mask,render_arc)
from visual_fidelity.light_sweep import light_sweep,Sweep

ROOT=Path(__file__).parent
SIZE=(720,1280)

def ease(frame,start,duration):
    p=max(0,min(1,(frame-start)/duration));return p*p*(3-2*p)

@lru_cache(maxsize=12)
def font(name,size,weight=None):
    f=ImageFont.truetype(str(ROOT/'fonts'/name),size)
    if weight is not None:f.set_variation_by_axes([weight])
    return f

def ink(mask,color):
    im=Image.new('RGBA',mask.size,color);im.putalpha(mask);return im

def transform_word(im,center,angle,opacity=1):
    im=im.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True)
    if opacity!=1:im.putalpha(im.getchannel('A').point(lambda v:round(v*opacity)))
    out=Image.new('RGBA',SIZE);out.alpha_composite(im,(round(center[0]-im.width/2),round(center[1]-im.height/2)))
    return out

@lru_cache(maxsize=2)
def name_base(word):
    if word=='Usmonov':
        mask=text_mask(word,font('LiberationSans-BoldItalic.ttf',180),padding=4)
        mask=mask.resize((649,164),Image.Resampling.LANCZOS)
        # Thin bevel outline belongs to the same complete source layer.
        edge=mask.filter(ImageFilter.MaxFilter(3));out=ink(edge,(238,210,207))
        yy,xx=np.mgrid[:mask.height,:mask.width]
        tint=np.empty((mask.height,mask.width,3),np.uint8)
        shade=.72+.28*np.sin(np.pi*yy/max(1,mask.height-1))
        tint[:,:,0]=np.uint8(220*shade);tint[:,:,1]=3;tint[:,:,2]=13
        face=Image.fromarray(tint).convert('RGBA');face.putalpha(mask);out.alpha_composite(face)
        return out
    mask=text_mask(word,font('Montserrat-Variable.ttf',180,900),padding=4)
    p=np.array(mask);h,w=p.shape
    shear=.19;aff=np.float32([[1,-shear,shear*h],[0,1,0]])
    mask=Image.fromarray(cv2.warpAffine(p,aff,(w+math.ceil(shear*h),h),flags=cv2.INTER_CUBIC))
    mask=mask.resize((607,139),Image.Resampling.LANCZOS)
    return ink(mask,(255,251,247))

def men_layer(frame):
    # Keep the previously observed script independently. Its thin traced strokes
    # are not a recovered font and do not alter either complete block word.
    from extra_type_v6 import data
    out=Image.new('RGBA',SIZE)
    for row in data().get(str(frame),[]):
        if row['name']!='Men':continue
        x0,y0,x1,y1=row['box'];m=np.zeros(((y1-y0)*2,(x1-x0)*2),np.uint8)
        for hole,poly in row['paths']:cv2.fillPoly(m,[np.array(poly,np.int32)*2],0 if hole else 255)
        mask=Image.fromarray(m).resize((x1-x0,y1-y0),Image.Resampling.LANCZOS)
        out.alpha_composite(ink(mask,(255,253,247)),(x0,y0))
    return out

def render_name_type(frame):
    if not 646<=frame<679:return Image.new('RGBA',SIZE)
    enter=ease(frame,646,3);front=ease(frame,650,10)
    red=light_sweep(name_base('Usmonov'),(frame-647)/24,Sweep(angle=-12,width=.22,intensity=.76,edge_boost=.16))
    red=transform_word(red,(360,747+26*(1-enter)),7,enter)
    white=transform_word(name_base('Ayyubxon'),(370,853+135*(1-front)),9,.13+.87*front)
    complete=LetteringProvenance('font',True,'Full glyphs reconstructed with disclosed substitute fonts')
    out=compose_layers(SIZE,[LetteringLayer(red,complete,z=0,name='Usmonov'),LetteringLayer(white,complete,z=1,name='Ayyubxon')])
    out.alpha_composite(men_layer(frame))
    if frame>=674:out.putalpha(out.getchannel('A').point(lambda v:round(v*(679-frame)/5)))
    return out

def shadowed_arc(text,size,center,radius,angle,color,tracking=0):
    face=render_arc(SIZE,text,font('Montserrat-Variable.ttf',size,900),center=center,radius=radius,
                    center_angle=angle,tracking=tracking,color=(*color,255))
    out=Image.new('RGBA',SIZE)
    if color[0]>240:
        mask=face.getchannel('A');shadow=mask.filter(ImageFilter.GaussianBlur(3)).point(lambda v:round(v*.55))
        out.alpha_composite(ink(shadow,(45,45,42)),(3,6))
        out.alpha_composite(ink(mask,(163,162,155)),(2,3))
    out.alpha_composite(face);return out

@lru_cache(maxsize=80)
def render_value_arc(frame):
    if not 722<=frame<799:return Image.new('RGBA',SIZE)
    # Measured screen trajectory of the arch; independent of chair recropping.
    p=ease(frame,722,12)
    dy=float(np.interp(frame,[722,734,760,798],[48,0,-132,-132]))
    white=shadowed_arc('davomida',116,(300,615+dy),270,20,(255,255,253),-1.5)
    red=shadowed_arc('shu vaqt',84,(300,627+dy),362,11,(205,0,7),-1.1)
    out=Image.new('RGBA',SIZE);out.alpha_composite(white);out.alpha_composite(red)
    out.putalpha(out.getchannel('A').point(lambda v:round(v*p)))
    return out

