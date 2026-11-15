"""Revision PT2: replay preserved shot layouts with Portuguese type and real matte.
No reference video pixels are loaded at render time. All clocks are explicit.
"""
import engine_bootstrap
from pathlib import Path
import json,math
from functools import lru_cache
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
import arte as a, efeitos as fx, cenas as legacy
from pt_typography import render_background_type,render_foreground_type
from pt_panels import render_panels,calendar_layer
from pt_glass import render_glass
from pt_wall import render_wall
from opening_assets_v6 import people_layer
from spatial_v6 import background as architecture,CHAIR_KEYS
from objects_v7 import render_keyhole,target_layer
from target_v6 import render_target
from visual_fidelity.reference_replay import SourceClock,MatteFootage,compose_bound_layers
from visual_fidelity.motion_layers import Transform,transform_layer
from visual_fidelity.orbit_type import OrbitSpec,render_orbit_type,composite_orbit
ROOT=Path(__file__).parent;SIZE=(720,1280)
BIND=json.loads((ROOT/'subject-bindings.json').read_text())
# Media is separate from immutable reference assets. Relative paths travel with package.
MEDIA=ROOT/'media'
VIDEO=MEDIA/'source.mp4' if (MEDIA/'source.mp4').exists() else ROOT.parent/'upload/329271.mp4'
MASKS=MEDIA/'mattes' if (MEDIA/'mattes').exists() else ROOT.parent/'test-pt/mattes'
SOURCE=MatteFootage(VIDEO,MASKS,edge_decontamination=4)

def blank():return Image.new('RGBA',SIZE)
@lru_cache(maxsize=2)
def foreground_asset(name,width):
 im=Image.open(ROOT/'localized'/name).convert('RGBA')
 return im.resize((width,round(im.height*width/im.width)),Image.Resampling.LANCZOS)
def subject(frame,scene,opacity=1,shadow=False):
 cfg=BIND['scenes'][scene];clock=SourceClock(*cfg['out'],cfg['source_start_frame'],cfg['speed'])
 keys=cfg['keys'];s,tx,ty=a.pose(frame,[(k['reference_frame'],k['scale'],k['tx'],k['ty']) for k in keys])
 if scene=='abertura':
  if frame<24:s,tx,ty=.7942238,81.5794,126.3177
  dx=a.pose(frame,[(0,0),(49,0),(61,65),(75,0),(101,-15)])[0];tx+=dx
 if scene=='diagonal':
  x,y,sc,roll=a.pose(frame,CHAIR_KEYS);x0,y0,sc0,_=a.pose(460,CHAIR_KEYS)
  ratio=sc/sc0;s*=ratio;tx=(tx-360)*ratio+360+x-x0;ty=(ty-750)*ratio+750+y-y0
 roll=12 if scene=='omad' else 0
 layer=SOURCE.layer(clock,frame,Transform(x=tx,y=ty,scale=s,opacity=opacity),SIZE)
 if roll:layer=transform_layer(layer,Transform(angle=roll,pivot=(420,810)),SIZE)
 if shadow:
  sh=blank();bottom=s*1155+ty;cx=s*360+tx
  ImageDraw.Draw(sh).ellipse((cx-190*s,bottom-26*s,cx+190*s,bottom+18*s),fill=(28,23,20,round(67*opacity)))
  sh=sh.filter(ImageFilter.GaussianBlur(15));sh.alpha_composite(layer);layer=sh
 return layer

def common(frame,scene,bg,shadow=False):
 return compose_bound_layers(SIZE,['environment','background_type','subject'],{
 'environment':lambda f:bg.copy(),'background_type':render_background_type,
 'subject':lambda f:subject(f,scene,shadow=shadow)},frame)

def opening(frame,ev):
 out=common(frame,'abertura',legacy.neutral(),True)
 p=a.progress(frame,18,5)*(1-a.progress(frame,34,12))
 if p:out=out.filter(ImageFilter.GaussianBlur(p*5));out.alpha_composite(calendar_layer(frame,p))
 out.alpha_composite(render_foreground_type(frame))
 if frame<5:out=a.camera(out,2.2-1.16*a.progress(frame,0,5),y=-176*(1-a.progress(frame,0,5))).filter(ImageFilter.GaussianBlur((5-frame)*2.8))
 shift=a.progress(frame,98,4)
 if shift:
  plate=legacy.neutral();a.put(plate,out,360-720*shift,640,blur=8*shift);out=plate
 return out

def orbit(frame,ev):
 bg=legacy.neutral();bg.alpha_composite(people_layer(frame));bg.alpha_composite(render_background_type(frame))
 sub=subject(frame,'orbita',a.progress(frame,101,4),True)
 p=a.progress(frame,102,5)
 spec=OrbitSpec(center=(355,680),radius_x=410,radius_z=320,camera_distance=1450,
 tilt_deg=-17+2*math.sin((frame-108)/20),pitch_deg=7,phase=.90+(frame-154)*.020,
 font_size=195,gap=130,repeats=4,thickness=6,highlight_phase=.48-.018*(frame-108))
 rear,front=render_orbit_type('CRIAR',ROOT/'fonts/Anton.ttf',spec)
 for im in(rear,front):im.putalpha(im.getchannel('A').point(lambda v:round(v*p)))
 out=composite_orbit(bg,sub,rear,front);zoom=a.pose(frame,[(102,.86),(120,.88),(132,1.0),(156,1.06)])[0];out=a.camera(out,zoom,y=125*(1-zoom));out.alpha_composite(render_foreground_type(frame))
 if frame>=157:
  p=a.progress(frame,157,8);out=Image.blend(out.filter(ImageFilter.GaussianBlur(12*p)),Image.new('RGBA',SIZE,(255,248,242)),.92*p)
 return out

def omad(frame,ev):
 out=common(frame,'omad',legacy.neutral(),True);out.alpha_composite(render_foreground_type(frame))
 p=a.progress(frame,215,4)
 if p:out=Image.blend(out,Image.new('RGBA',SIZE,'white'),p*.8)
 return out

def deadline(frame,ev):
 out=legacy.blush();a.light(out,(359,660),(304,140),(253,29,31),.36)
 a.soft_box(out,(63,531,655,720),50,(255,243,235),(234,157,153),(255,250,244),8)
 out.alpha_composite(render_foreground_type(frame))
 p=1-a.progress(frame,219,4)
 if p:out=Image.blend(out,Image.new('RGBA',SIZE,'white'),.87*p)
 if frame>=227:
  nxt=render_panels(232,{'funil':287,'fluxo':333});nxt.alpha_composite(render_foreground_type(232))
  out=fx.strip_scene(frame/24,{'start_s':226/24,'duration_s':.375,'delays':[.27,0,.16]},out,nxt)
 return out

def panels(frame,ev):
 out=render_panels(frame,ev);out.alpha_composite(render_background_type(frame));out.alpha_composite(render_foreground_type(frame));return out

def diagonal(frame,ev):
 out=architecture(frame).copy();out.alpha_composite(render_wall(frame));out.alpha_composite(subject(frame,'diagonal',shadow=True));return out

def glass(frame,ev):
 out=render_glass(frame,ev);out.alpha_composite(render_background_type(frame));out.alpha_composite(render_foreground_type(frame));return out

def name(frame,ev):
 bg=a.gradient(SIZE,(251,12,17),(139,6,12));ImageDraw.Draw(bg).polygon([(0,310),(720,-35),(720,348),(0,698)],fill=(245,246,229))
 out=common(frame,'nome',bg);out.alpha_composite(legacy.floor());out.alpha_composite(render_foreground_type(frame))
 p=a.progress(frame,673,6)
 if p:out=Image.blend(out,Image.new('RGBA',SIZE,'white'),p*.74)
 return out

def blue(frame,ev):
 out=legacy.blue_background().copy()
 for name,col,x,y,r in [('EDIÇÃO',(85,164,244),88,169,11),('RITMO',(219,117,51),640,113,-10),('COR',(250,194,64),105,511,16),('MOTION',(131,194,236),632,511,-17)]:a.put(out,legacy.placard(name,col),x,y,1,r)
 p=a.progress(frame,682,9);a.put(out,a.paper(),357,300,.90+.1*p,angle=-6)
 out.alpha_composite(render_background_type(frame));out.alpha_composite(subject(frame,'azul'))
 y=760+310*(1-a.progress(frame,688,13));out.alpha_composite(foreground_asset('desk-laptop.png',800),(-40,round(y)))
 out.alpha_composite(render_foreground_type(frame))
 enter=1-a.progress(frame,679,11);shake=a.progress(frame,716,6)
 out=a.camera(out,1+.24*enter+.40*shake,46*enter-45*shake,-40*enter,12*enter-30*shake)
 p=a.progress(frame,718,3)
 if p:out=Image.blend(out,Image.new('RGBA',SIZE,'white'),p*.91)
 return out

def value(frame,ev):
 out=common(frame,'valor',legacy.neutral());out.alpha_composite(legacy.floor());out.alpha_composite(render_foreground_type(frame))
 out.alpha_composite(target_layer(frame,center=(345,800),scale=1.25))
 flash=1-a.progress(frame,721,3)
 if flash:out=Image.blend(out,Image.new('RGBA',SIZE,'white'),flash*.95)
 return out

def chess(frame,ev):
 out=common(frame,'xadrez',a.wood_room());p=a.progress(frame,807,14)
 table=foreground_asset('chess-table.png',820);a.put(out,table,360,680+table.height/2+240*(1-p),alpha=p)
 out.alpha_composite(render_foreground_type(frame));return out

def target(frame,ev):
 out=render_target(frame,ev);out.alpha_composite(render_foreground_type(frame));return out

def cta(frame,ev):
 out=common(frame,'cta',legacy.neutral());out.alpha_composite(legacy.floor());out.alpha_composite(render_foreground_type(frame))
 p=a.progress(frame,1065,8)*(1-a.progress(frame,1109,11))
 if p:
  cx,cy=a.pose(frame,[(1065,290,710),(1085,403,791),(1109,377,721)]);cy+=200;a.light(out,(round(cx),round(cy)),(133,154),(243,29,40),.60*p)
  marks=blank();d=ImageDraw.Draw(marks)
  for i in range(3):
   yy=cy+30*i;d.line([(cx-59,yy-26),(cx,yy+19),(cx+59,yy-25)],fill=(255,65,70,round(223*p*(1-i*.14))),width=19,joint='curve')
  out.alpha_composite(marks)
 return out

SHOTS={'abertura':opening,'orbita':orbit,'omad':omad,'deadline':deadline,'lupa':panels,'diagonal':diagonal,'vidro':glass,'nome':name,'azul':blue,'valor':value,'xadrez':chess,'olho':render_keyhole,'mira':target,'cta':cta}
