"""Generated transparent glass panels with independent animated magnifier.

A measured 2.5D composition; these images are not recovered 3D meshes.
Reference pixels are used for measurement only, never read by this renderer.
"""
from pathlib import Path
from functools import lru_cache
import math,json
import numpy as np
from PIL import Image,ImageDraw,ImageFilter,ImageFont
import arte as a
import efeitos as fx
ROOT=Path(__file__).parent;ASSETS=ROOT/'hybrid/panels';W,H=720,1280
LENS_KEYS=[(232,429,804),(247,261,693),(266,435,687),(283,459,699),(295,360,777),(306,324,789),(320,375,792),(338,249,561),(355,312,585),(365,480,663),(390,348,762),(404,345,762)]

@lru_cache(maxsize=5)
def asset(kind):
 path=ROOT/'localized'/f'{kind}.png'
 if not path.exists():path=ASSETS/(kind+'.png')
 im=Image.open(path).convert('RGBA')
 # Ignore faint distant bloom when normalizing the object footprint.
 box=im.getchannel('A').point(lambda x:255 if x>110 else 0).getbbox()
 return im.crop(box)

@lru_cache(maxsize=1)
def background():
 return fx.studio((250,239,234),(241,228,223)).copy()

@lru_cache(maxsize=2)
def foliage(which):
 im=Image.open(ASSETS/'foliage.png').convert('RGBA')
 if which:
  im=im.resize((540,590),fx.LANCZOS).rotate(180).filter(ImageFilter.GaussianBlur(5.5))
  out=Image.new('RGBA',(W,H));out.alpha_composite(im,(250,710));return out
 im=im.resize((330,390),fx.LANCZOS)
 out=Image.new('RGBA',(W,H));out.alpha_composite(im,(-25,-12));return out

@lru_cache(maxsize=3)
def panel(kind):
 im=asset(kind).resize((452,490),fx.LANCZOS)
 return im

def subtitle(plate,text,x,y,size=23):
 if not text:return
 font=ImageFont.truetype(str(ASSETS/'DejaVuSans.ttf'),size)
 d=ImageDraw.Draw(plate);d.multiline_text((x,y),text,font=font,fill=(110,96,92),anchor='ma',align='center',spacing=3)

def magnifier(under,cx,cy,radius=106):
 lens=fx.lens(under,round(cx),round(cy),radius,1.28)
 mask=Image.new('L',(W*2,H*2));ImageDraw.Draw(mask).ellipse(((cx-radius-5)*2,(cy-radius-5)*2,(cx+radius+5)*2,(cy+radius+5)*2),fill=255)
 mask=mask.resize((W,H),fx.LANCZOS);out=Image.composite(lens,under,mask)
 angle=math.radians(26);u=np.array([math.cos(angle),math.sin(angle)]);n=np.array([-u[1],u[0]])
 start=np.array([cx,cy])+u*(radius*1.01);neck=start+u*42;end=np.array([cx,cy])+u*(radius*3.45)
 layer=Image.new('RGBA',(W,H));d=ImageDraw.Draw(layer)
 d.line([tuple(neck+[7,12]),tuple(end+[7,12])],fill=(57,49,44,135),width=39)
 out.alpha_composite(layer.filter(ImageFilter.GaussianBlur(8)))
 layer=Image.new('RGBA',(W,H));d=ImageDraw.Draw(layer)
 d.line([tuple(start),tuple(neck)],fill=(38,40,38),width=25)
 d.line([tuple(start-n*7),tuple(neck-n*7)],fill=(240,239,232),width=5)
 for t in (8,15,22,29):
  p=start+u*t;d.line([tuple(p-n*12),tuple(p+n*12)],fill=(125,125,121),width=2)
 d.line([tuple(neck),tuple(end)],fill=(16,17,18),width=32)
 d.line([tuple(neck-n*11),tuple(end-n*11)],fill=(171,175,175),width=3)
 d.line([tuple(neck-n*8),tuple(end-n*8)],fill=(243,242,231),width=2)
 d.line([tuple(neck+n*9),tuple(end+n*9)],fill=(70,72,70),width=3)
 out.alpha_composite(layer);return out

def render_panels(frame,ev):
 kind='audit'if frame<ev['funil']else'funnel'if frame<ev['fluxo']else'flow'
 out=background().copy();out.alpha_composite(foliage(0))
 p=panel(kind);mask=Image.new('L',(W,H));mask.paste(p.getchannel('A'),(133,425));mask=mask.filter(ImageFilter.GaussianBlur(18)).point(lambda v:round(v*.18));shadow=Image.new('RGBA',(W,H),(104,74,61));shadow.putalpha(mask);out.alpha_composite(shadow)
 # One cutout per editorial panel, positioned against measured screen bounds.
 out.alpha_composite(p,(126,402))
 if kind=='audit':
  subtitle(out,'cada detalhe'+(' da edição'if frame>=265 else''),360,284,30)
 elif kind=='funnel':
  text='uma narrativa que conecta'
  if frame>=315:text+='\ndo início ao fim'
  subtitle(out,text,360,971,22)
 else:
  text='do roteiro à tela'
  if frame>=370:text+='\ncada etapa faz parte'
  if frame>=389:text+='\nda sua história'
  subtitle(out,text,360,971,21)
 x,y=a.pose(frame,LENS_KEYS)
 out=magnifier(out,x,y)
 # Defocused foreground foliage properly occludes the magnifier handle.
 out.alpha_composite(foliage(1))
 return out


# Preserve all reference calendar projective keys; replace text-localized asset only.
import cv2
from opening_assets_v6 import trim_box, warp, controls
@lru_cache(maxsize=1)
def calendar_asset():
 return Image.open(ROOT/'localized/calendar.png').convert('RGBA')
def calendar_layer(frame,opacity=1):
 image=calendar_asset();x0,y0,x1,y1=trim_box(image);rx0,ry0,rx1,ry1=controls()['reference_box'];sx=(rx1-rx0)/(x1-x0);sy=(ry1-ry0)/(y1-y0);G=np.array([[sx,0,rx0-sx*x0],[0,sy,ry0-sy*y0],[0,0,1.]])
 item=controls()['rows'].get(str(frame),{});H=item.get('H')
 if H is None:
  x,y,angle=a.pose(frame,[(18,-175,820,42),(24,208,742,23),(32,323,785,0),(40,586,855,-24),(46,909,904,-35)])
  M=cv2.getRotationMatrix2D((323,785),angle,1.);M[:,2]+=[x-323,y-785];H=np.vstack([M,[0,0,1]])
 out=warp(image,np.array(H)@G)
 if opacity<1:out.putalpha(out.getchannel('A').point(lambda v:round(v*opacity)))
 return out
