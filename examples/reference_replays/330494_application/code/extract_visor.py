"""Manual dense visor contour tracking; original source raster, no magnification."""
from pathlib import Path
import json,hashlib
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'assets/visor_masks';OUT.mkdir(parents=True,exist_ok=True);QA=OUT/'qa';QA.mkdir(exist_ok=True)
KEYS={
188:[[344,400],[360,400],[380,400],[400,399],[415,396],[420,396],[416,400],[414,406],[415,413],[419,419],[426,422],[433,422],[429,429],[418,438],[404,446],[388,453],[370,459],[352,464],[337,468],[331,468],[330,460],[329,449],[329,437],[330,424],[333,412],[338,404]],
192:[[343,400],[360,399],[380,399],[405,400],[426,398],[442,396],[437,401],[435,407],[436,414],[440,419],[447,422],[453,421],[448,431],[439,440],[425,449],[408,457],[388,464],[366,469],[347,472],[333,470],[330,461],[329,449],[329,436],[330,423],[333,412],[338,404]],
196:[[344,399],[360,398],[382,398],[407,400],[431,400],[458,396],[454,400],[452,407],[454,414],[458,419],[465,421],[468,420],[464,431],[455,441],[440,450],[420,460],[399,468],[376,474],[353,475],[338,472],[335,463],[333,451],[333,438],[334,424],[337,412],[341,404]],
200:[[347,399],[365,399],[389,398],[415,400],[439,401],[466,398],[462,402],[460,408],[462,416],[466,421],[471,422],[474,421],[470,433],[460,444],[444,454],[423,465],[400,473],[377,478],[355,476],[342,472],[339,463],[337,451],[337,438],[338,425],[341,414],[344,405]],
204:[[352,400],[370,399],[394,399],[420,402],[445,403],[472,400],[468,404],[467,411],[468,418],[472,423],[477,424],[479,423],[474,437],[465,449],[448,459],[425,470],[401,478],[378,480],[356,477],[346,472],[343,464],[341,452],[341,438],[342,426],[345,414],[348,405]],
208:[[355,400],[374,400],[397,399],[423,402],[448,404],[476,402],[472,406],[470,413],[472,420],[476,424],[480,425],[482,425],[478,438],[468,449],[451,461],[428,472],[403,479],[380,481],[359,478],[348,472],[346,464],[344,452],[344,438],[345,426],[348,414],[351,405]],
212:[[356,400],[375,400],[398,400],[424,402],[449,404],[478,402],[474,407],[472,414],[474,421],[478,425],[482,426],[484,425],[479,439],[470,450],[453,461],[430,472],[405,479],[382,481],[360,478],[349,472],[347,464],[345,452],[345,438],[346,426],[349,414],[352,405]],
215:[[356,400],[375,400],[398,400],[424,402],[449,404],[479,402],[475,407],[473,414],[475,421],[479,425],[483,426],[485,425],[480,439],[471,450],[454,461],[431,472],[406,479],[383,481],[361,478],[350,472],[348,464],[346,452],[346,438],[347,426],[350,414],[353,405]]}
# Keep the shiny bottom seal and black chin bar outside the replacement area.
for pts in KEYS.values():
 for j in range(13,20):pts[j][1]-=4

def contour(frame):
 kk=sorted(KEYS);lo=max(k for k in kk if k<=frame);hi=min(k for k in kk if k>=frame);u=0 if lo==hi else (frame-lo)/(hi-lo)
 pts=(1-u)*np.array(KEYS[lo],float)+u*np.array(KEYS[hi],float)
 # Two Chaikin corner-cutting passes provide a dense smooth contour; no overshoot.
 for _ in range(2):
  nxt=np.roll(pts,-1,axis=0);q=np.empty((len(pts)*2,2));q[0::2]=.75*pts+.25*nxt;q[1::2]=.25*pts+.75*nxt;pts=q
 return pts
def render_mask(points):
 # 4x rasterization produces subpixel edges; 0.6 source-pixel feather.
 s=4;m=np.zeros((1280*s,720*s),np.uint8);cv2.fillPoly(m,[np.int32(np.round(points*s))],255)
 m=cv2.GaussianBlur(m,(0,0),.6*s)
 return cv2.resize(m,(720,1280),interpolation=cv2.INTER_AREA)

def main():
 c=cv2.VideoCapture(str(ROOT/'media/source.mp4'));c.set(1,188);rows=[];qc=[]
 for f in range(188,216):
  ok,a=c.read();assert ok and a.shape[:2]==(1280,720);pts=contour(f);m=render_mask(pts);cv2.imwrite(str(OUT/f'{f:04}.png'),m)
  overlay=a.copy();t=m.astype(float)/255*.45;overlay=np.uint8(overlay*(1-t[:,:,None])+np.array([0,40,255])*t[:,:,None]);cv2.polylines(overlay,[np.int32(np.round(pts))],True,(255,0,255),1,cv2.LINE_AA)
  crop=overlay[370:490,310:505];crop=cv2.resize(crop,(585,360),interpolation=cv2.INTER_NEAREST);cv2.putText(crop,str(f),(10,25),0,.8,(255,255,255),2)
  cv2.imwrite(str(QA/f'qc-{f:04}.jpg'),crop,[cv2.IMWRITE_JPEG_QUALITY,96])
  if f in KEYS:qc.append(crop)
  rows.append({'frame':f,'polygon_source_pixels':pts.tolist(),'mask_filename':f'{f:04}.png','alpha_nonzero_bbox':[int(v) for v in cv2.boundingRect((m>5).astype(np.uint8))],'alpha_area_equivalent_px':float(m.sum()/255)})
 cv2.imwrite(str(OUT/'visor-mask-QC.jpg'),np.vstack([np.hstack(qc[:4]),np.hstack(qc[4:])]),[cv2.IMWRITE_JPEG_QUALITY,95])
 source=ROOT/'media/source.mp4';h=hashlib.sha256(source.read_bytes()).hexdigest()
 report={'source_relative_path':'media/source.mp4','source_sha256':h,'raster':[720,1280],'fps':24,'frame_indexing':'zero-based','range_inclusive':[188,215],'method':'manual26control-vertex contours in8keyframes, linear temporal interpolation and2Chaikin passes to104vertices in original raster','feather_sigma_source_pixels':.6,'supersampling':4,'exclusions':['helmet shell','black lateral pivot/seal','bottom visor rim and chin bar'],'provenance':'Contours independently traced on330494; no329796 visor coordinates reused. Manual conservative glass-region selection, not neural segmentation.','expected_boundary_uncertainty_px':2,'usage':'Use grayscale PNG as alpha,255inside,0outside. Apply photo+mask transform together only after compositing in source coordinates. Do not reinterpret these as magnified coordinates.','frames':rows,'keyframes':KEYS}
 (OUT/'provenance.json').write_text(json.dumps(report,indent=2));print('Wrote28masks, original720x1280')
if __name__=='__main__':main()
