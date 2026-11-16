"""Reviewed musical cues + semantic asset coverage applied to the frozen V1."""
from pathlib import Path
import sys,json,copy,hashlib,math
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'engine'))
from visual_fidelity.music_sync import schedule_events,retime_binding_schedule
from visual_fidelity.edit_contract import validate_edit
old=json.loads((R/'timeline-v1.json').read_text())
review=json.loads((R/'analysis/music-review-v2.json').read_text())
cues={}
for c in review['intro_provisional_pulse']+review['selected_cues']+review['secondary_subdivision_cues']:
 f=c['frame_24fps'];cues[f]={'id':f'cue-{f}','time':c['time_seconds'],'strength':1,
 'kind':'reviewed_signal_accent','evidence':c.get('evidence',c)}
targets=[(11,'opening_start','start'),(23,'opening_image2','cut'),(34,'opening_image3','cut'),
 (46,'opening_image4','cut'),(57,'opening_image5','cut'),(69,'opening_image6','cut'),
 (77,'x_start','start'),(80,'x_hit2','apex'),(84,'x_hit3','apex'),
 (88,'collage_reveal','reveal'),(104,'collage_environment2','cut'),(119,'collage_environment3','cut'),
 (130,'cyan_prepare','start'),(134,'cyan_impact','apex'),(138,'horizontal_start','start'),
 (150,'horizontal_change','cut'),(157,'rotation_start','start'),(169,'rotation_change','cut'),
 (180,'vertical_reveal','reveal'),(188,'vertical_change','cut'),(195,'portal_start','start'),
 (203,'portal_reveal','reveal'),(211,'portal_change','cut'),(215,'detail1','cut'),
 (219,'detail2','cut'),(222,'detail3','cut'),(226,'closing_start','start'),
 (230,'closing_change','cut'),(234,'clean_resolve','resolve')]
events=schedule_events([{'id':n,'role':role,'target_time':f/24,'max_shift':.025,'cue_id':cues[f]['id']}
 for f,n,role in targets],list(cues.values()),24,240)
anchors=[(0,0),(11,12),(77,52),(88,84),(130,104),(138,108),(157,144),(180,168),
 (195,188),(215,216),(226,228),(234,239),(240,240)]
bindings=retime_binding_schedule(old['frame_bindings'],
 [{'output_frame':a,'source_frame':b} for a,b in anchors],240)
def photo(key,u=0,view=None):return {'source':key,'view':view or [.5,.58,1.02+.06*max(0,min(1,u))]}
def source(f,view=None):return {'source':'raw','frame':f,'view':view or [.5,.5,1]}
def phase(i,a,b):return max(0,min(1,(i-a)/max(1,b-a)))
for i,b in enumerate(bindings):
 b['music_events']=[]
 if 11<=i<77:
  starts=[11,23,34,46,57,69];j=max(k for k,v in enumerate(starts) if i>=v)
  b['insert']=photo(['rear','coast','forest','industrial','coast','rear'][j],phase(i,starts[j],starts[j]+10))
  half=.06+.44*phase(i,11,76);b['mask']={'kind':'bands','axis':'y','intervals':[[.5-half,.5+half]]}
 elif 77<=i<88:
  j=0 if i<80 else 1 if i<84 else 2;start=[77,80,84][j]
  b['insert']=photo(['industrial','coast','forest'][j],view=[.5,.60,1.20])
  b['mask']={'kind':'x','center':[.5,.5],'width':.16+.10*math.exp(-(i-start)/2),'angles':[-40,40]}
 elif 88<=i<130:
  key='coast' if i<104 else 'forest' if i<119 else 'rear'
  b['base']={'source':'clean'}
  if i<104:b['insert']['view']=[.56,.38,2.05+.06*phase(i,88,103)]
  elif i<119:b['insert']=photo('industrial',view=[.68,.30,2.3])
  else:b['insert']=photo('rear',view=[.46,.40,3.0])
 elif 130<=i<138:
  q=104+i-130;b['base']=source(q);b.pop('insert',None);b['mask']={'kind':'empty'}
  a=max(0,1-(134-i)/4) if i<=134 else max(0,1-(i-134)/3)
  b['tint']={'matte':f'assets/subject_masks/{q:04}.png','mask':{'kind':'bands','axis':'y','intervals':[[.44,1]]},'rgb':[0,244,244],'opacity':.86*a}
 elif 138<=i<157:
  b['base']=photo('industrial',phase(i,138,156),[.54,.58,1.12])
  b['insert']=photo('coast' if i<150 else 'rear',phase(i,138,156))
 elif 157<=i<180:
  b['base']=photo('industrial',phase(i,157,179),[.55,.59,1.28])
  b['insert']=photo('forest' if i<169 else 'coast',phase(i,157,179))
 elif 180<=i<195:
  b['base']=photo('forest',phase(i,180,194));b['insert']=photo('rear' if i<188 else 'coast',phase(i,180,194))
 elif 195<=i<215:
  b['insert']=photo('coast' if i<211 else 'forest',phase(i,195,214),[.5,.61,1.10]);b['mask_opacity']=phase(i,195,203)**4
 elif 215<=i<226:
  b['base']=photo('industrial' if i<219 else 'rear' if i<222 else 'forest',phase(i,215,225))
 elif 226<=i<234:
  b['base']=source(i);b['foreground']={**source(i),'matte':f'assets/subject_masks/{i:04}.png','box':[0,0,1,1]}
  b['insert']=photo('coast' if i<230 else 'rear',phase(i,226,233));half=.5*(1-phase(i,226,234))
  b['mask']={'kind':'bands','axis':'y','intervals':[[.5-half,.5+half]]}
 elif i>=234:
  b.clear();b.update(frame=i,shot='clean_resolve',base=source(i),mask={'kind':'empty'},music_events=[])
for e in events:bindings[e['frame']]['music_events'].append(e['event_id'])
data=copy.deepcopy(old);data.update(video_engine='1.1.0',revision=2,frame_bindings=bindings)
for k in ['coast','forest','industrial','rear']:
 data['assets'][k]={'kind':'image','path':f'assets/{k}-generated.png','origin':'generated','provenance':f'assets/{k}-provenance.json'}
data['music_sync']={'mode':'reviewed_cues','engine':'1.0.1','audio_sha256':hashlib.sha256((R/data['audio']['path']).read_bytes()).hexdigest(),
 'clock':{'start':0,'speed':1},'cue_review':'analysis/music-review-v2.json','events':events,
 'limitations':'Measured signal accents with editorial assignment; no perceptual audio approval or asserted BPM.'}
slots=[('coast','Coastal motorcycle and rider','329796 frames84,156-192,226-267',[11,234],20),
 ('forest','Frontal motorcycle and forest','329796 frames48-72,350-393',[11,226],15),
 ('industrial','Low-angle rider, bike detail and industrial scene','329796 frames216-225 and285-335',[11,226],25),
 ('rear','Rear rider and motorcycle in open field','329796 frames0-96,192-204',[11,234],15),
 ('raw','Live subject, hand gesture and visor','330494 frames0-239; reference collage168-215/portal336-349',[0,240],100)]
data['asset_plan']={'schema':'visual-asset-coverage/1','analysis':'analysis/asset-needs.json',
 'semantic_author':'Visual reference review by editor; not an automatic semantic classifier.',
 'slots':[{'id':k,'role':role,'evidence':evidence,'interval':interval,'min_visible_frames':minimum,
 'asset_ids':[k],'status':'ready','semantic_review':'reviewed for role; generated identity approximate' if k!='raw' else 'source footage'}
 for k,role,evidence,interval,minimum in slots]}
data['shots']=[]
for b in bindings:
 if not data['shots'] or data['shots'][-1]['id']!=b['shot']:data['shots'].append({'id':b['shot'],'start':b['frame'],'end':b['frame']+1})
 else:data['shots'][-1]['end']=b['frame']+1
data['photography_policy']='New raw + four generated complementary views; no reference photographic pixels. Generated views are2D stills animated by crops/masks.'
(R/'timeline.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
check=validate_edit(data,R);(R/'analysis/edit-contract.json').write_text(json.dumps(check,indent=2));print(json.dumps(check))
