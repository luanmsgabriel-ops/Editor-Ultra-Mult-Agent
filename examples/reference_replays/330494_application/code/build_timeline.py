from pathlib import Path
import json,copy,shutil
R=Path(__file__).resolve().parents[1]
reference=json.loads((R/'assets/reference-motion.json').read_text())['frame_bindings']
def mapped(f,a,b,ra,rb):return copy.deepcopy(reference[round(ra+(rb-ra)*(f-a)/max(1,b-a-1))]['mask'])
def src(f,view=[.5,.5,1]):return {'source':'raw','frame':min(239,max(0,int(f))),'view':view}
def fg(f,box=[0,0,1,1]):return {**src(f),'matte':f'assets/subject_masks/{f:04}.png','box':box}
def variant(f,k):
 choices=[src(f,[.27,.70,2.1]),src(72+f%24,[.56,.39,2.0]),{'source':'clean','view':[.40,.55,1.55]},src(192+f%36,[.57,.53,1.4]),src(f,[.30,.68,1.65])]
 return choices[k%len(choices)]
shots=[('establish',0,12),('band_behind_subject',12,52),('crossing_diagonals',52,84),('portrait_collage',84,104),('cyan_gesture',104,108),('countermoving_horizontal',108,144),('rotating_bands',144,168),('vertical_bands',168,188),('visor_portal',188,216),('detail_cuts',216,228),('closing_band',228,240)]
frames=[]
for i in range(240):
 shot=next(s for s in shots if s[1]<=i<s[2]);b={'frame':i,'shot':shot[0],'base':src(i),'mask':{'kind':'empty'}}
 if 12<=i<52:
  b.update(insert=variant(i,(i-12)//4),mask=mapped(i,12,52,0,96),foreground=fg(i))
 elif 52<=i<84:
  b.update(base=src(i,[.55,.49,1.18]),insert=variant(i,(i-52)//4),mask=mapped(i,52,84,111,153))
 elif 84<=i<104:
  b.update(base={'source':'clean'},insert=src(i,[.56,.38,2.05]),mask={'kind':'linear_gradient','axis':'y','start':.43,'end':.65},foreground=fg(i,[.125,.25,.75,.75]))
 elif 104<=i<108:
  b['tint']={'matte':f'assets/subject_masks/{i:04}.png','mask':{'kind':'bands','axis':'y','intervals':[[.52+(i-104)*.10,1]]},'rgb':[0,244,244],'opacity':.90}
 elif 108<=i<144:
  b.update(base=src(i,[.56,.49,1.35]),insert=variant(i,(i-108)//4),mask=mapped(i,108,144,226,267))
 elif 144<=i<168:
  b.update(base=src(i,[.56,.49,1.35]),insert=variant(i,(i-144)//3),mask=mapped(i,144,168,285,335))
 elif 168<=i<188:
  b.update(insert=variant(i,(i-168)//4),mask=mapped(i,168,188,350,393))
 elif 188<=i<216:
  # Reanchor to this helmet. Source and matte receive the identical viewport.
  b.update(base=src(i,[.57,.39,2.1]),insert=variant(i,(i-188)//5),mask_file=f'assets/visor_masks/{i:04}.png',fit_insert_to_mask=True)
 elif 216<=i<228:
  b['base']=variant(i,(i-216)//4)
 elif i>=228:
  u=(i-228)/11;half=.50*(1-u)
  b.update(insert=variant(i,0),mask={'kind':'bands','axis':'y','intervals':[[.5-half,.5+half]]},foreground=fg(i))
 frames.append(b)
data={'schema':'geometric-video-edit/1','reference_motion':'329796','source':'330494','video_engine':'1.0.1','mask_engine':'1.0.1','frames':240,'fps':24,'width':720,'height':1280,'photography_policy':'New raw footage only; generated clean plate used in collage and inserts. No photographic pixels from reference329796.','assets':{'raw':{'kind':'video','path':'media/source.mp4'},'clean':{'kind':'image','path':'assets/clean-plate-generated.png'}},'audio':{'path':'audio/reference-mix.wav','start':0,'speed':1,'provenance':'Mix from the provided reference; first 10 seconds at original speed for private comparison. No publication rights inferred.'},'shots':[{'id':s[0],'start':s[1],'end':s[2]} for s in shots],'frame_bindings':frames}
(R/'timeline.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
print('240 frames,11 shots,explicit fresh source and mask bindings')
