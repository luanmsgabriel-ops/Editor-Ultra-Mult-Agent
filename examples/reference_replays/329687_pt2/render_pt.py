import argparse,json,subprocess,time
from pathlib import Path
import cv2
from pt_scenes import SHOTS,SOURCE,ROOT
P=argparse.ArgumentParser();P.add_argument('output',type=Path);P.add_argument('--frames',nargs='*',type=int);P.add_argument('--start',type=int,default=0);P.add_argument('--end',type=int,default=1135);args=P.parse_args()
cv2.setNumThreads(2);tl=json.loads((ROOT/'timeline.json').read_text())
def render(f):
 shot=next(s for s in tl['shots'] if s['start']<=f<s['end']);return SHOTS[shot['id']](f,shot['events']).convert('RGB')
if args.frames:
 args.output.mkdir(parents=True,exist_ok=True)
 for f in args.frames:render(f).save(args.output/f'{f:04d}.jpg',quality=95);print('Still',f,flush=True)
else:
 args.output.parent.mkdir(parents=True,exist_ok=True)
 cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pixel_format','rgb24','-video_size','720x1280','-framerate','24','-i','pipe:0','-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p','-threads','4','-movflags','+faststart',str(args.output)]
 start=time.time()
 with subprocess.Popen(cmd,stdin=subprocess.PIPE) as p:
  for f in range(args.start,args.end):
   p.stdin.write(render(f).tobytes())
   if f%48==0:print(f'{f}/{args.end} elapsed {time.time()-start:.1f}s',flush=True)
  p.stdin.close()
  if p.wait():raise RuntimeError('Encoder failed')
SOURCE.close()
