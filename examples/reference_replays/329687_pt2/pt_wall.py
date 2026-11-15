"""Portuguese wall lettering projected with the exact camera of the architecture."""
import engine_bootstrap
from pathlib import Path
from functools import lru_cache
import json, numpy as np, cv2
from PIL import Image,ImageFont
import arte as a
from visual_fidelity.type_layout import text_mask
from visual_fidelity.reference_replay import camera_plane_homography,warp_rgba
ROOT=Path(__file__).parent
@lru_cache(maxsize=1)
def data():return json.loads((ROOT/'hybrid/camera-fit.json').read_text())
def H(frame):
 d=data();r=d['frames'][frame-405];dx=d['fixed_geometry_shape']['white_wall_seam_dx_per_minus4_y']
 return camera_plane_homography(r['R_cv'],r['parameters'][3:6],1000,(360,300),(0,0,0),(dx/4,-1,0),(0,0,1))
@lru_cache(maxsize=1)
def lines():
 font=ImageFont.truetype(str(ROOT/'fonts/Anton.ttf'),140)
 words=['CRIAMOS','vídeos para marcas','com boas histórias','ritmo em cada corte','do roteiro até a tela','ideias que conectam']
 dims=[(640,185),(640,76),(640,105),(640,100),(640,82),(640,125)]
 starts=[509,494,471,447,422,407]
 y=0;out=[]
 for text,dim,start in zip(words,dims,starts):
  mask=text_mask(text,font,padding=2).resize(dim,Image.Resampling.LANCZOS)
  im=Image.new('RGBA',dim,(177,1,11));im.putalpha(mask);out.append((im,y,start));y+=dim[1]+13
 return out,y
@lru_cache(maxsize=1)
def anchor():
 _,height=lines()
 src=np.float32([[0,0],[640,0],[640,height],[0,height]])
 dst=np.float32([[35,20],[386,113],[386,416],[35,538]])
 return cv2.getPerspectiveTransform(src,dst)
def render_wall(frame):
 rows,height=lines();im=Image.new('RGBA',(640,height))
 for glyph,y,start in rows:
  p=a.progress(frame,start,8)
  if p:
   glyph=glyph.copy();glyph.putalpha(glyph.getchannel('A').point(lambda v:round(v*p)));im.alpha_composite(glyph,(0,y))
 return warp_rgba(im,H(frame)@np.linalg.inv(H(530))@anchor(),(720,1280))
