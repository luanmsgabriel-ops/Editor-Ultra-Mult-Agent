"""Portuguese composition binding for reference 329687, 24 fps, 720x1280.

All returned layers are FINAL SCREEN SPACE.  Composite background below the
person and foreground above.  Never run old Uzbek vector_motion/extra_type on
these intervals. This is complete-glyph localized lettering, not identification
of the source fonts. See fonts/PT-font-provenance.json for licensed substitutes.
Scene assets, orbital band and diagonal wall typography belong to the adapter.
"""
from pathlib import Path
from functools import lru_cache
import math
import cv2
import numpy as np
from PIL import Image, ImageFont, ImageFilter
import engine_bootstrap
from visual_fidelity.type_layout import text_mask, render_arc, LetteringLayer, LetteringProvenance, compose_layers
from visual_fidelity.light_sweep import light_sweep, Sweep

ROOT=Path(__file__).resolve().parent
SIZE=(720,1280)
RED=(202,0,12,255); WHITE=(255,252,245,255); CREAM=(251,230,211,255)
FONT_FILES={'condensed':'Anton.ttf','sans':'Montserrat-Variable.ttf','script':'GreatVibes-Regular.ttf','fine_script':'PinyonScript-Regular.ttf','serif':'BodoniModa[opsz,wght].ttf','name':'LiberationSans-BoldItalic.ttf','body_italic':'LiberationSans-Italic.ttf'}


def blank(): return Image.new('RGBA',SIZE)
def ease(f,start,duration):
    p=np.clip((f-start)/duration,0.,1.);return float(p*p*(3-2*p))
def lerp(f,keys):
    if f<=keys[0][0]:return np.asarray(keys[0][1],float)
    for (a,x),(b,y) in zip(keys,keys[1:]):
        if f<=b:
            u=ease(f,a,b-a);return np.asarray(x,float)*(1-u)+np.asarray(y,float)*u
    return np.asarray(keys[-1][1],float)
@lru_cache(maxsize=80)
def font(style,size,weight=900):
    f=ImageFont.truetype(str(ROOT/'fonts'/FONT_FILES[style]),int(size))
    if style=='sans':f.set_variation_by_axes([weight])
    if style=='serif':f.set_variation_by_axes([72,400])
    return f

def ink(mask,color):
    out=Image.new('RGBA',mask.size,color);out.putalpha(mask);return out

@lru_cache(maxsize=100)
def word(text,style='sans',size=120,width=None,height=None,color=WHITE,weight=900,bevel=False,stroke=0):
    # Full shaped word retained, including connecting cursive ligatures.
    m=text_mask(text,font(style,size,weight),padding=8)
    if width is not None and height is not None:m=m.resize((int(width),int(height)),Image.Resampling.LANCZOS)
    elif width is not None:
        factor=min(1.,width/m.width);m=m.resize((max(1,round(m.width*factor)),max(1,round(m.height*factor))),Image.Resampling.LANCZOS)
    # Preserve padding for bevel/stroke; no measured occlusion baked into letters.
    out=Image.new('RGBA',m.size)
    if stroke:out.alpha_composite(ink(m.filter(ImageFilter.MaxFilter(stroke*2+1)),WHITE))
    if bevel:
        out.alpha_composite(ink(m.filter(ImageFilter.MaxFilter(3)),(244,206,198,255)))
        h,w=m.height,m.width; yy=np.arange(h)[:,None]
        shade=.72+.28*np.sin(np.pi*yy/max(1,h-1));a=np.zeros((h,w,4),np.uint8)
        for c in range(3):a[:,:,c]=np.clip(color[c]*shade,0,255)
        a[:,:,3]=np.asarray(m);out.alpha_composite(Image.fromarray(a))
    else:out.alpha_composite(ink(m,color))
    return out

def slant(im,degrees=10):
    # Shear the complete layer, retaining its glyph overhangs and alpha padding.
    slope=math.tan(math.radians(degrees));pad=math.ceil(im.height*abs(slope))
    return im.transform((im.width+pad,im.height),Image.Transform.AFFINE,
                        (1,slope,-pad,0,1,0),resample=Image.Resampling.BICUBIC)

def place(im,center,angle=0,opacity=1,scale=1,shadow=0):
    out=blank()
    if scale!=1:im=im.resize((max(1,round(im.width*scale)),max(1,round(im.height*scale))),Image.Resampling.LANCZOS)
    if angle:im=im.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True)
    im=im.copy();im.putalpha(im.getchannel('A').point(lambda v:round(v*np.clip(opacity,0,1))))
    x,y=round(center[0]-im.width/2),round(center[1]-im.height/2)
    if shadow:
        m=im.getchannel('A').filter(ImageFilter.GaussianBlur(shadow)).point(lambda v:round(v*.5))
        out.alpha_composite(ink(m,(24,20,15,255)),(x+2,y+4))
    out.alpha_composite(im,(x,y));return out

def warp(im,quad):
    # Premultiply before projective filtering to avoid black alpha fringes.
    a=np.asarray(im).astype(np.float32)/255.;a[:,:,:3]*=a[:,:,3:4]
    src=np.float32([[0,0],[im.width-1,0],[im.width-1,im.height-1],[0,im.height-1]])
    mat=cv2.getPerspectiveTransform(src,np.float32(quad))
    b=cv2.warpPerspective(a,mat,SIZE,flags=cv2.INTER_CUBIC)
    b[:,:,:3]=np.divide(b[:,:,:3],b[:,:,3:4],out=np.zeros_like(b[:,:,:3]),where=b[:,:,3:4]>.00001)
    return Image.fromarray(np.uint8(np.clip(b,0,1)*255))

def glint(im,f,start,duration,angle=76,intensity=.5,width=.12):
    return light_sweep(im,(f-start)/duration,Sweep(angle=angle,width=width,intensity=intensity,edge_boost=.08))

def add(out,im):out.alpha_composite(im)

def render_background_type(frame):
    """720x1280 RGBA, below subject, coordinates already camera transformed."""
    f=int(frame);o=blank()
    if 0<=f<102:
        q=lerp(f,[(15,[[139,366],[594,260],[594,657],[140,690]]),(49,[[109,380],[548,332],[564,636],[145,711]]),(61,[[194,147],[758,178],[752,584],[175,600]]),(75,[[-36,100],[637,20],[661,508],[0,626]]),(88,[[-69,100],[590,-5],[640,500],[-60,650]])])
        p=ease(f,5,10);q+=np.array([-74,88])*(1-p)
        title=word('CLARA','condensed',260,640,540,RED,bevel=True)
        title=warp(glint(title,f,21,27),q);title.putalpha(title.getchannel('A').point(lambda v:round(v*p)));add(o,title)
        box=lerp(f,[(15,[485,365]),(49,[465,370]),(61,[650,200]),(75,[510,130]),(88,[485,120])])
        add(o,place(word('criativa','script',180,270,190,WHITE),box,10,ease(f,8,6),shadow=2))
    elif 166<=f<219:
        p=ease(f,166,9);k=1+.16*(1-ease(f,174,18))
        q=np.array([[-18,250],[530,110],[662,625],[114,758]],float);q=(q-[320,720])*k+[320,720];q+=(-42*(1-p),71*(1-p))
        title=warp(glint(word('CRIAR','condensed',280,620,600,RED,bevel=True),f,179,31),q)
        title.putalpha(title.getchannel('A').point(lambda v:round(v*p)));add(o,title)
        add(o,place(word('Para','script',105,220,None,RED),(255,160),13,p))
        add(o,place(word('boas histórias','script',105,420,None,WHITE),(445,400),15,ease(f,187,4),shadow=2))
    elif 102<=f<166:
        p=ease(f,122,10)
        add(o,place(word('Ideias','sans',150,450,155,RED),(390,160),-8,p))
        add(o,place(word('em movimento','script',80,280,None,RED),(470,105),-8,p))
        add(o,place(word('para conectar pessoas','sans',29,435,None,RED,weight=500),(400,252),-8,p))
    elif 232<=f<405:
        p=ease(f,232,7);pos=(360,246)
        add(o,place(slant(word('Sua marca','sans',100,550,None,RED,weight=850),10),pos,0,p))
        add(o,place(word('em cena','script',93,250,None,RED),(422,195),0,p))
    elif 533<=f<646:
        if f<617:
            p=ease(f,533,7)
            add(o,place(word('Ideias','serif',160,490,None,CREAM),(360,220),6,p))
            add(o,place(word('que conectam','fine_script',83,360,None,CREAM),(411,292),6,p))
            add(o,place(word('Criamos','fine_script',79,230,None,CREAM),(380,160),6,p))
        else:
            # The source replaces its serif heading at the laptop beat, f617.
            # Preserve the bold italic + thin connected-script pairing here.
            p=ease(f,617,5);dy=25*(1-p)
            add(o,place(word('VÍDEOS','name',190,550,155,WHITE),(350,306+dy),6,p))
            add(o,place(word('para marcas','script',135,430,None,WHITE),(422,382+dy),6,p))
    elif 722<=f<799:
        p=ease(f,722,12);dy=float(np.interp(f,[722,734,760,798],[48,0,-132,-132]))
        for text,size,radius,angle,color in [('histórias',112,270,20,WHITE),('para contar',65,365,11,RED)]:
            face=render_arc(SIZE,text,font('sans',size),center=(300,615+dy),radius=radius,center_angle=angle,tracking=-1.25,color=color)
            if color==WHITE:
                m=face.getchannel('A');add(o,ink(m.filter(ImageFilter.GaussianBlur(3)).point(lambda v:round(v*.5)),(40,40,35,255)))
                displaced=blank();displaced.alpha_composite(ink(m,(153,152,145,255)),(2,3));add(o,displaced)
            face.putalpha(face.getchannel('A').point(lambda v:round(v*p)));add(o,face)
    elif 799<=f<846:
        p=ease(f,799,6)
        add(o,place(word('Cada corte','script',130,595,None,(232,191,158,255)),(354,235),10,p,shadow=2))
        add(o,place(word('importa','script',103,345,None,(232,191,158,255)),(406,327),8,p,shadow=2))
    elif 679<=f<722:
        p=ease(f,679,5)
        add(o,place(word('VÍDEOS','sans',126,445,None,RED,weight=900),(357,253),0,p))
        add(o,place(word('para marcas','sans',47,365,None,RED,weight=650),(357,349),0,p))
        add(o,place(word('com boas histórias','sans',28,370,None,RED,weight=500),(357,394),0,p))
    elif 920<=f<1135:
        # Original CTA has three successive title beats (not a 9s held card).
        if f<977:
            start,title,script,sub=920,'CRIATIVIDADE','em cada detalhe','edição que conta histórias'
        elif f<1017:
            start,title,script,sub=977,'BOAS HISTÓRIAS','para marcas','com ritmo, intenção e identidade'
        else:
            start,title,script,sub=1017,'EDITORES','Vamos criar','conte histórias com a gente'
        p=ease(f,start,6);dy=22*(1-p)
        add(o,place(glint(word(title,'condensed',190,620,146,RED,stroke=2),f,start+12,32),(360,270+dy),0,p))
        add(o,place(word(script,'script',95,400,None,WHITE),(370,194+dy),0,p,shadow=2))
        add(o,place(word(sub,'sans',25,470,None,RED,weight=500),(360,352+dy),0,p))
    return o


def render_foreground_type(frame):
    """720x1280 RGBA above subject; complete name layers retain occlusion."""
    f=int(frame);o=blank()
    if 57<=f<75:
        p=ease(f,57,5);add(o,place(glint(word('criar','sans',145,420,None,RED,stroke=2),f,50,20),(270,905),-5,p,shadow=2))
    elif 75<=f<102:
        p=ease(f,75,5)
        add(o,place(glint(word('boas histórias','sans',90,630,None,RED,stroke=2),f,78,20),(355,938),8,p,shadow=2))
        add(o,place(word('para marcas','sans',38,365,None,RED,stroke=1),(355,1005),8,p))
    elif 219<=f<232:
        p=ease(f,219,3)
        add(o,place(word('Cada detalhe conta','sans',70,640,None,RED),(360,600),-6,p))
    elif 570<=f<646:
        p=ease(f,570,6)
        for t,st,sz,y in [('conteúdo que','body_italic',46,878),('aproxima','body_italic',46,922),('pessoas','body_italic',46,966),('E MARCAS','sans',53,1022)]:
            add(o,place(word(t,st,sz,440,None,CREAM,weight=900),(380,y),0,p))
    elif 646<=f<679:
        enter=ease(f,646,3);front=ease(f,650,10)
        red=glint(word('Clara','name',245,650,215,RED,weight=800,bevel=True),f,647,24,angle=-12,intensity=.55,width=.22)
        red=place(red,(360,747+26*(1-enter)),7,enter)
        white=place(word('direção criativa','sans',110,640,111,WHITE,weight=900),(370,853+135*(1-front)),9,.13+.87*front,shadow=2)
        prov=LetteringProvenance('font',True,'Complete Portuguese glyphs; disclosed substitute font')
        o=compose_layers(SIZE,[LetteringLayer(red,prov,z=0,name='Clara'),LetteringLayer(white,prov,z=1,name='direção criativa')])
        add(o,place(word('Eu sou','script',185,320,None,WHITE),(445,652),9,enter,shadow=2))
        if f>=674:o.putalpha(o.getchannel('A').point(lambda v:round(v*(679-f)/5)))
    elif 752<=f<799:
        p=ease(f,752,7);dy=110*(1-p)
        group=blank()
        add(group,place(word('PROCURAMOS','condensed',150,610,142,WHITE,stroke=0),(360,867+dy),10,p,shadow=2))
        add(group,place(glint(word('EDITORES','sans',115,610,126,RED,stroke=1),f,755,28),(370,977+dy),10,p,shadow=2))
        add(group,place(word('com boas ideias','sans',58,580,None,WHITE,weight=400),(380,1075+dy),10,p))
        add(o,group)
    elif 883<=f<920:
        p=ease(f,883,6)
        add(o,place(word('Histórias que','script',100,490,None,CREAM),(360,823),8,p))
        add(o,place(word('conectam','script',114,450,None,CREAM),(388,919),8,p))
    return o


def render_all_type(frame):
    o=render_background_type(frame);o.alpha_composite(render_foreground_type(frame));return o
