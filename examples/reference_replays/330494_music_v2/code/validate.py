from pathlib import Path
import json,hashlib,subprocess,cv2
R=Path(__file__).resolve().parents[1]
reports=[]
for name in ['Moto-330494-V2-Ritmo-e-Cenas.mp4','Comparacao-V1-V2-330494.mp4']:
 p=R/'output'/name
 meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(p)]));v=next(s for s in meta['streams'] if s['codec_type']=='video');a=next(s for s in meta['streams'] if s['codec_type']=='audio')
 cap=cv2.VideoCapture(str(p));n=0;black=[]
 while True:
  ok,im=cap.read()
  if not ok:break
  if im.max()<8:black.append(n)
  n+=1
 cap.release();assert n==240;assert not black;assert v['r_frame_rate']=='24/1';assert abs(float(v['duration'])-10)<.001;assert abs(float(a['duration'])-10)<.03
 reports.append({'name':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'frames':n,'fps':24,'width':v['width'],'height':v['height'],'duration':v['duration'],'audio_duration':a['duration'],'black_frames':black})
x={'exports':reports,'tests':'see tests-v2.log','visual_scope':'New raw, four generated complementary views and generated clean plate; no reference photographic pixels.','approval':'pending','perceptual_audio_review':False}
(R/'analysis/validation.json').write_text(json.dumps(x,indent=2));print(json.dumps(x))
