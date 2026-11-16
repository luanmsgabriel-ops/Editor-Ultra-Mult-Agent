"""Technical export checks; these do not certify visual similarity."""
from pathlib import Path
import json,hashlib,subprocess
import cv2,numpy as np
R=Path(__file__).resolve().parents[1]
reports=[]
for name in ['Moto-Reconstrucao-329796.mp4','Prova-Reaplicacao.mp4','Comparativo-329796.mp4']:
 p=R/'output'/name
 meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))
 cap=cv2.VideoCapture(str(p));frames=0;black=[];min_mean=255
 while True:
  ok,im=cap.read()
  if not ok:break
  avg=float(im.mean());min_mean=min(min_mean,avg)
  if im.max()<8:black.append(frames)
  frames+=1
 cap.release();assert frames==427,(name,frames);assert not black,(name,black)
 v=next(s for s in meta['streams'] if s['codec_type']=='video');a=next(s for s in meta['streams'] if s['codec_type']=='audio')
 assert v['r_frame_rate']=='30/1';assert abs(float(v['duration'])-427/30)<.001
 assert abs(float(a['duration'])-427/30)<.03
 reports.append({'file':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'decoded_frames':frames,'fps':v['r_frame_rate'],'width':v['width'],'height':v['height'],'video_duration':v['duration'],'audio_duration':a['duration'],'audio_rate':a['sample_rate'],'audio_channels':a['channels'],'black_frames':black,'minimum_frame_mean':min_mean})
report={'technical_checks':reports,'unit_tests':'11 passed; see tests.log','visual_scope':'Recovered photographic layers, not independent source-footage reconstruction. No fidelity percentage inferred.','playback':'Kdenlive playback reached frame 426 on preceding revision dd6443. Final revision changes soft-alpha color decomposition only, checked in critical frame crops. No confirmed perceptual audio audition.','approval':'pending user review'}
(R/'analysis/export-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(reports,ensure_ascii=False,indent=2))
