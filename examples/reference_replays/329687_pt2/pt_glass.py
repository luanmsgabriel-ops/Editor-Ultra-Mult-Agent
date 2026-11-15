"""Hybrid glass sequence: generated RGBA icons, measured 2D motion, no text.

This is compositing of images, not a recovered volumetric model. The optional
measurement CLI reads the source; render_glass never opens that source video.
"""
from pathlib import Path
from functools import lru_cache
import json,math,argparse
import cv2,numpy as np
from PIL import Image,ImageFilter,ImageDraw
import arte as a
import efeitos as fx
ROOT=Path(__file__).resolve().parent
W,H=720,1280

@lru_cache(maxsize=1)
def controls():
 return json.loads((ROOT/'hybrid/glass_motion.json').read_text())
@lru_cache(maxsize=1)
def report_controls():
 d=json.loads((ROOT/'hybrid/report-motion.json').read_text())
 return d,{r['frame']:r for r in d['measurements']}
@lru_cache(maxsize=3)
def image_asset(kind):
 # No foreign text occurs in these icons: preserve the original generated assets byte-for-byte.
 p=ROOT/'hybrid'/({'report':'icone-relatorio-gerado.png','gift':'gift.png','computer':'computer.png'}[kind])
 return Image.open(p).convert('RGBA') if p.exists() else None

def premultiplied_warp(im,matrix):
 pix=np.asarray(im).astype(np.float32)/255;pix[:,:,:3]*=pix[:,:,3,None]
 out=cv2.warpPerspective(pix,np.asarray(matrix,float),(W,H),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_CONSTANT)
 al=np.clip(out[:,:,3],0,1);out[:,:,:3]/=np.maximum(al[:,:,None],1e-5);out[:,:,3]=al
 return Image.fromarray(np.uint8(np.clip(out,0,1)*255))

@lru_cache(maxsize=1)
def bg_basis():
 d,_=report_controls();y,x=np.mgrid[:H,:W];xn=x/719*2-1;yn=y/1279*2-1
 return np.stack([xn**i*yn**j for i,j in d['background_powers']],axis=-1).astype(np.float32)
@lru_cache(maxsize=3)
def background(frame):
 d=controls();keys=sorted(int(k)for k in d['background'])
 lo=max((k for k in keys if k<=frame),default=keys[0]);hi=min((k for k in keys if k>=frame),default=keys[-1])
 u=0 if lo==hi else(frame-lo)/(hi-lo);co=(1-u)*np.array(d['background'][str(lo)])+u*np.array(d['background'][str(hi)])
 rgb=np.uint8(np.clip(bg_basis()@co,0,255));return Image.fromarray(rgb).convert('RGBA')

@lru_cache(maxsize=1)
def report_foreground():
 # Only the chart panel is visible as an out-of-focus foreground echo.
 # Crop is compositing of the generated asset, not a source-video raster.
 source=image_asset('report').copy();panel=Image.new('L',source.size);ImageDraw.Draw(panel).polygon([(645,366),(1227,424),(1155,993),(565,930)],fill=255)
 source.putalpha(Image.fromarray(np.minimum(np.asarray(source.getchannel('A')),np.asarray(panel))))
 im=source.crop((550,340,1254,1050)).resize((790,797),Image.Resampling.LANCZOS)
 im=im.rotate(-4,expand=True,resample=Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(17))
 im.putalpha(im.getchannel('A').point(lambda v:round(v*.75)))
 return im

def report_layer(frame):
 d,rows=report_controls();G=np.array(d['generated_to_anchor']);item=rows[frame];opacity=1.
 if item['H'] is not None:transform=np.array(item['H'])@G
 elif frame<541:
  p=max(0,min(1,(frame-537)/4));opacity=p
  transform=np.array([[1,0,(1-p)*390],[0,1,(1-p)*150],[0,0,1]])@np.array(rows[541]['H'])@G
 else:
  transform=np.array(rows[577]['H'])@G;opacity=max(0,(580-frame)/3)
 sprite=premultiplied_warp(image_asset('report'),transform)
 blur=max(0,(544-frame)*.9)if frame<544 else max(0,(frame-569)*.5)
 if blur:sprite=sprite.filter(ImageFilter.GaussianBlur(blur))
 if opacity<1:sprite.putalpha(sprite.getchannel('A').point(lambda p:round(p*opacity)))
 return sprite

@lru_cache(maxsize=4)
def asset_to_anchor(kind):
 im=image_asset(kind);alpha=np.asarray(im.getchannel('A'));yy,xx=np.where(alpha>180)
 bbox=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)]
 r=controls()['icons'][kind]['anchor_bbox'];sx=(r[2]-r[0])/(bbox[2]-bbox[0]);sy=(r[3]-r[1])/(bbox[3]-bbox[1])
 return np.array([[sx,0,r[0]-sx*bbox[0]],[0,sy,r[1]-sy*bbox[1]],[0,0,1]])

def fallback_view(kind,frame,row):
 """Existing explicit Blender views remain a documented fallback if no image exists."""
 tag='presente'if kind=='gift'else'computador';yaw=-12+15*math.sin((frame-580)/15)
 stamp=a.glass_yaw(tag,yaw);box=row['bbox'];stamp=stamp.crop(stamp.getchannel('A').getbbox())
 stamp=stamp.resize((max(1,round(box[2]-box[0])),max(1,round(box[3]-box[1]))),Image.Resampling.LANCZOS)
 layer=Image.new('RGBA',(W,H));layer.alpha_composite(stamp,(round(box[0]),round(box[1])));return layer

def render_glass(frame,ev):
 if not 533<=frame<646:raise ValueError('glass frame outside533:646')
 plate=background(frame).copy()
 if frame<580:
  # Foreground position drifts gently while the main graphic is tracked separately.
  opacity=1-a.progress(frame,571,9)
  if opacity>0:
   echo=report_foreground().copy();echo.putalpha(echo.getchannel('A').point(lambda v:round(v*opacity)))
   plate.alpha_composite(echo,(395+round(8*math.sin((frame-540)/18)),1010+round(2*(frame-558))))
  plate.alpha_composite(report_layer(frame))
  if frame>=572:a.light(plate,(370,580),(130,125),(255,150,60),min(.50,(frame-571)*.06))
 else:
  kind='gift'if frame<617 else'computer';d=controls()['icons'][kind];row=d['frames'][str(frame)]
  if image_asset(kind) is not None:
   if row['homography'] is not None:M=np.asarray(row['homography'])@asset_to_anchor(kind)
   else:
    b=row['bbox'];r=d['anchor_bbox'];sx=(b[2]-b[0])/(r[2]-r[0]);sy=(b[3]-b[1])/(r[3]-r[1]);M=np.array([[sx,0,b[0]-sx*r[0]],[0,sy,b[1]-sy*r[1]],[0,0,1]])@asset_to_anchor(kind)
   layer=premultiplied_warp(image_asset(kind),M)
  else:layer=fallback_view(kind,frame,row)
  blur=row.get('blur',0)
  if blur:layer=layer.filter(ImageFilter.GaussianBlur(blur))
  plate.alpha_composite(layer)
  if 596<=frame<617:
   b=row['bbox'];a.light(plate,(round((b[0]+b[2])/2),round((b[1]+b[3])/2)),(27,29),(255,146,55),.45)
 return plate

