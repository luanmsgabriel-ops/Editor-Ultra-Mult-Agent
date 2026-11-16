"""Build measured, editable shot/mask bindings; no video pixels are stored here."""
import json,math
from pathlib import Path
R=Path(__file__).resolve().parents[1]
shots=json.loads((R/'analysis/independent-shots.json').read_text())['shots']
bands={v['frame']:v for v in json.loads((R/'analysis/band-measurements.json').read_text())}
# Geometric measurements are supplied independently from the image recovery pass.
measured={}
p=R/'analysis/measured-masks.json'
if p.exists():
 data=json.loads(p.read_text()); measured={v['frame']:v for v in data['frames'] if v.get('effect')!='none_or_outside_assigned_range'}
for i in range(427):
 pass

def band(a,b):return {'kind':'bands','axis':'y','intervals':[[max(0,a)/720,min(720,b)/720]]}
def shot(i):return next(s for s in shots if s['start_frame']<=i<s['end_frame_exclusive'])
frames=[]
for i in range(427):
 s=shot(i);spec={'kind':'empty'};fg=None;plate=281; mode='photo'
 if i<97:
  # Measured monotonic boundaries. Last three frames are fully open.
  y=npinterp=i
  top=max(0,229-2.42*i);bottom=min(720,491+2.42*i)
  v=bands[i]
  if abs(v['top']-top)<5:top=v['top']
  if abs(v['bottom']-bottom)<5:bottom=v['bottom']
  spec=band(top,bottom);fg=i;plate=281
 elif i<106:
  spec={'kind':'empty'};mode='cyan';plate=106
 elif i<111:plate=106
 elif i<154:
  spec={'kind':'x','center':[.5,.5],'angles':[-29.36,29.36],'width':.22};plate=106
 elif i<168:
  spec={'kind':'full'};fg=i;plate=106
 elif i<216:
  spec={'kind':'linear_gradient','axis':'y','start':.61,'end':.79};fg=i;plate=269;mode='collage'
 elif i<221:plate=216
 elif i<226:
  spec={'kind':'polygon','points':[[.155,1],[.16,.74],[.21,.65],[.21,.44],[.235,.29],[.30,.235],[.39,.25],[.43,.35],[.445,.51],[.405,.63],[.48,.71],[.52,1]]};plate=216
 elif i<268:
  t=i-226
  spec={'kind':'bands','axis':'y','intervals':[[(-52+18.3*t)/720,(60+18.3*t)/720],[(710-19.2*t)/720,(798-19.2*t)/720]]};plate=268
 elif i<285:plate=i
 elif i<336:
  t=i-285;spec={'kind':'x','center':[.48,.49],'angles':[t*11,t*11+52],'width':.12,'opacity':min(1,(t+1)/6)};plate=283
 elif i<350:
  spec={'kind':'polygon','points':[[.409,.018],[.445,.03],[.477,.1],[.505,.2],[.519,.3],[.514,.38],[.49,.45],[.455,.51],[.42,.52],[.37,.49],[.30,.4],[.32,.37],[.355,.29],[.384,.19],[.418,.1]]};plate=283
 elif i<394:
  t=i-350;spec={'kind':'bands','axis':'x','intervals':[[(-64+26.3*t)/1280,(92+26.3*t)/1280],[(1194-26.5*t)/1280,(1350-26.5*t)/1280]]};plate=350
 else:
  v=bands[i];top=v['top'];bottom=720-top
  spec=band(top,bottom);fg=i;plate=281
 if i in measured:
  spec=measured[i]['mask'].copy();spec['opacity']=min(1,(i-284)/6) if 285<=i<291 else measured[i].get('opacity',1)
 if 221<=i<226:spec={'kind':'empty'};fg=i
 frames.append({'frame':i,'shot':s['id'],'mask':spec,'foreground_frame':fg,'fallback_plate':plate,'mode':mode})
manifest={'schema':'geometric-reference-replay/1','reference':'329796','engine':'geometric_replay','engine_version':'1.0.1','fps':30,'frames':427,'width':1280,'height':720,'source_rotation_ccw':90,'reconstruction_method':'Recovered photographic layers from supplied finished MP4, independently parameterized masks and foreground alpha. Hidden imagery is approximate; not original source footage recovery.','original_is_render_input':False,'approval':'pending','assets':{'base':'assets/base.mp4','insert':'assets/insert.mp4','foreground':'assets/foreground.mp4','audio':'audio/reference.wav','foreground_masks':'assets/subject_masks'},'frame_bindings':frames,'shots':[{'id':s['id'],'start':s['start_frame'],'end':s['end_frame_exclusive']} for s in shots]}
(R/'timeline.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print('427 bindings; shots',len(shots))
