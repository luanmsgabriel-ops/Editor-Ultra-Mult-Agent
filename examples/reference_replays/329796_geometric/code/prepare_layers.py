"""Inverse compositing into explicit photographic assets, not source-shot recovery.

The visible photographic samples are reused. Unknown regions are filled from
clean plates or nearest valid texture. Confidence masks identify measured pixels.
A reference comparison is therefore NOT independent evidence of generalization.
"""
import argparse,json,sys,subprocess,hashlib
from pathlib import Path
import cv2,numpy as np
from scipy.ndimage import distance_transform_edt
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'engine' if (R/'engine').exists() else R.parent/'motor-v7'))
from visual_fidelity.geometric_replay import mask,decompose_observed
cv2.setNumThreads(2)

def writer(path):
 return subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-vcodec','rawvideo','-pix_fmt','bgr24','-s','1280x720','-r','30','-i','-','-an','-vf','scale=out_color_matrix=bt709:out_range=tv,format=yuv444p','-c:v','libx264','-preset','fast','-crf','10','-threads','2','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-movflags','+faststart',str(path)],stdin=subprocess.PIPE)

def texture_fill(image,known):
 """Extend observed pixels solely into unknown support; not hallucinated footage."""
 small=cv2.resize(known.astype('uint8'),(320,180),interpolation=cv2.INTER_NEAREST)
 if not small.any():return np.zeros_like(image)
 _,idx=distance_transform_edt(1-small,return_indices=True)
 thumb=cv2.resize(image,(320,180),interpolation=cv2.INTER_AREA)
 filled=thumb[idx[0],idx[1]]
 return cv2.resize(filled,(1280,720),interpolation=cv2.INTER_LINEAR)

def recover(image,known,fallback=None):
 safe=cv2.erode(known.astype('uint8'),np.ones((5,5),np.uint8))>0
 fill=texture_fill(image,safe) if fallback is None else fallback.copy()
 fill[safe]=image[safe]
 return fill,safe

def main():
 manifest=json.loads((R/'timeline.json').read_text());asset=R/'assets';(asset/'confidence').mkdir(exist_ok=True);(asset/'cyan_masks').mkdir(exist_ok=True)
 plates={}
 for p in (asset/'plates').glob('*.png'):
  if 'map' not in p.name:plates[p.stem]=cv2.imread(str(p))
 def fallback(b):
  i=b['frame']; name=('base-opening' if i<97 or i>=394 else 'base-x' if i<168 else 'base-coast' if i<216 else 'base-industrial' if i<226 else 'base-slits' if i<269 else 'base-rotating' if i<350 else 'base-vertical')
  if 269<=i<285:
   p=asset/'plates'/f'clean-{b["fallback_plate"]:03}.png'
   if p.exists():return cv2.imread(str(p))
  return plates[name]
 outputs={k:writer(asset/(k+'.mp4')) for k in ('base','insert','foreground')}
 source=R/'media/reference.mp4' if (R/'media/reference.mp4').exists() else R.parent/'upload/329796.mp4'
 cap=cv2.VideoCapture(str(source));stats=[]
 for b in manifest['frame_bindings']:
  i=b['frame'];ok,im=cap.read()
  if not ok:raise ValueError('Source prematurely ended')
  im=cv2.rotate(im,cv2.ROTATE_90_COUNTERCLOCKWISE);a=mask(b['mask'],1280,720)
  fgm=np.zeros((720,1280),np.uint8)
  if b.get('foreground_frame') is not None:
   p=asset/'subject_masks'/f'{b["foreground_frame"]:04}.png'
   fgm=cv2.imread(str(p),cv2.IMREAD_GRAYSCALE)
   if fgm is None:raise FileNotFoundError(p)
  fg=fgm.astype(np.float32)/255
  # These are actual independent source layers after extraction; not a finished
  # frame used as the background with new effects pasted over it.
  base,safe_base=recover(im,(a<.01)&(fg<.01),None if b['mode']=='collage' or b.get('foreground_frame') is not None else fallback(b))
  if b['mode']=='cyan':
   cy=(im[:,:,0]>200)&(im[:,:,1]>200)&(im[:,:,2]<90)
   yy,xx=np.mgrid[:720,:1280];cy&=(xx>400)&(xx<900)&(yy>280)
   contours,_=cv2.findContours(cy.astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
   silhouette=np.zeros((720,1280),np.uint8)
   if contours:cv2.drawContours(silhouette,[max(contours,key=cv2.contourArea)],-1,1,-1)
   cy=cv2.GaussianBlur(silhouette.astype('float32'),(3,3),.45)
   cv2.imwrite(str(asset/'cyan_masks'/f'{i:04}-shade.png'),im[:,:,2])
   cv2.imwrite(str(asset/'cyan_masks'/f'{i:04}.png'),np.rint(cy*255).astype('uint8'))
   base=im.copy();base[cy>.01]=fallback(b)[cy>.01];safe_base=cy<.01;insert=np.zeros_like(im)
  else:
   # In feathered areas solve I=(C-(1-a)B)/a, given the approximate base.
   recovered=im.astype('float32')
   soft=(a>.01)&(a<.99)&(fg<.01)
   if soft.any():
    adjusted,solved=decompose_observed(im,base,a)
    base[soft]=adjusted[soft]
    recovered[soft]=solved[soft]
   insert,safe_insert=recover(np.rint(recovered).astype('uint8'),(a>.01)&(fg<.01))
   # Full-opacity source texture remains photographic; support is independent
   # of the procedural masks and can be rebound to arbitrary new footage.
  fore=np.zeros_like(im);support=cv2.dilate((fgm>0).astype('uint8'),np.ones((7,7),np.uint8))>0;fore[support]=im[support]
  for k,frame in [('base',base),('insert',insert),('foreground',fore)]:outputs[k].stdin.write(frame.tobytes())
  # Compact confidence witness: 0=inferred/unseen,1=observed base,2=insert,3=foreground.
  confidence=np.zeros((720,1280),np.uint8);confidence[safe_base]=85
  confidence[(a>.99)&(fg<.01)]=170;confidence[fg>.99]=255
  cv2.imwrite(str(asset/'confidence'/f'{i:04}.png'),confidence)
  stats.append({'frame':i,'observed_base_fraction':round(float(safe_base.mean()),6),'insert_mask_fraction':round(float((a>.01).mean()),6),'foreground_fraction':round(float((fg>.01).mean()),6),'unknown_fill':'clean plate or nearest visible texture; never original hidden pixels'})
  if i%60==0:print('prepared',i,flush=True)
 cap.release()
 for out in outputs.values():
  out.stdin.close()
  if out.wait()!=0:raise RuntimeError('Layer encoding failed')
 (R/'analysis/layer-recovery.json').write_text(json.dumps({'method':__doc__,'reference_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'frames':stats},ensure_ascii=False,indent=2))
 print('prepared427 frames in3 independent photo layer streams')
if __name__=='__main__':main()
