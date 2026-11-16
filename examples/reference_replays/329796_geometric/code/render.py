"""Render recovered photo layers through the reusable geometric engine.
This executable NEVER opens the original/reference MP4. Use --proof to bind
independent clean plates instead of recovered layers, retaining the mask timing.
"""
import json,sys,subprocess,argparse,hashlib
from pathlib import Path
import cv2,numpy as np
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'engine' if (R/'engine').exists() else R.parent/'motor-v7'))
from visual_fidelity.geometric_replay import mask,compose,VERSION
cv2.setNumThreads(2)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--proof',action='store_true');ap.add_argument('--output',type=Path);args=ap.parse_args()
 data=json.loads((R/'timeline.json').read_text());W,H=data['width'],data['height'];out=args.output or R/'output'/('Prova-Reaplicacao.mp4' if args.proof else 'Moto-Reconstrucao-329796.mp4');out.parent.mkdir(exist_ok=True,parents=True)
 tmp=out.with_name(out.stem+'-silent.mp4')
 cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{W}x{H}','-r',str(data['fps']),'-i','-','-an','-vf','scale=out_color_matrix=bt709:out_range=tv,format=yuv420p','-c:v','libx264','-crf','16','-preset','medium','-threads','3','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-movflags','+faststart',str(tmp)]
 proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
 caps={} if args.proof else {k:cv2.VideoCapture(str(R/data['assets'][k])) for k in ['base','insert','foreground']}
 proof=[cv2.imread(str(R/'assets/plates'/f'clean-{j:03}.png')) for j in [269,271,274,276,279,281,283]]
 used=[]
 for b in data['frame_bindings']:
  i=b['frame'];a=mask(b['mask'],W,H)
  if args.proof:
   # Deliberately different clip bindings prove that geometry is not baked.
   base=proof[(i//97)%len(proof)].copy();insert=proof[(i//3+2)%len(proof)].copy();fg=None
  else:
   layers={}
   for k,c in caps.items():
    ok,im=c.read()
    if not ok:raise RuntimeError(f'Missing layer frame{k}:{i}')
    layers[k]=im
   base,insert=layers['base'],layers['insert'];fg=None
   if b.get('foreground_frame') is not None:
    alpha=cv2.imread(str(R/data['assets']['foreground_masks']/f'{b["foreground_frame"]:04}.png'),cv2.IMREAD_GRAYSCALE)
    if alpha is None:raise RuntimeError(f'Missing foreground mask{i}')
    fg=np.dstack([layers['foreground'],alpha])
  image=compose(base,insert,a,fg)
  if b['mode']=='cyan':
   if args.proof:
    cy=mask({'kind':'bands','axis':'y','intervals':[[.45+(i-97)*.035,1]]},W,H)
   else:cy=cv2.imread(str(R/'assets/cyan_masks'/f'{i:04}.png'),0).astype('float32')/255
   fill=np.full_like(image,(255,255,0))
   if not args.proof:
    shade=cv2.imread(str(R/'assets/cyan_masks'/f'{i:04}-shade.png'),0)
    fill[:,:,2]=shade
   image=compose(image,fill,cy)
  if args.proof:
   cv2.rectangle(image,(0,0),(W,43),(16,16,16),-1)
   cv2.putText(image,'PROVA: NOVAS IMAGENS / MESMAS MASCARAS', (20,29),cv2.FONT_HERSHEY_SIMPLEX,.72,(255,255,255),2,cv2.LINE_AA)
  proc.stdin.write(image.tobytes());used.append(b['shot'])
  if i%90==0:print('render',i,flush=True)
 proc.stdin.close()
 if proc.wait()!=0:raise RuntimeError('Render failed')
 for c in caps.values():c.release()
 subprocess.run(['ffmpeg','-v','error','-y','-i',str(tmp),'-i',str(R/data['assets']['audio']),'-map','0:v:0','-map','1:a:0','-c:v','copy','-af','atrim=end_sample=683200,asetpts=PTS-STARTPTS','-c:a','aac','-b:a','192k','-t',str(data['frames']/data['fps']),'-movflags','+faststart',str(out)],check=True)
 tmp.unlink()
 report={'render':out.name,'frames':data['frames'],'fps':data['fps'],'engine_version':VERSION,'reference_mp4_opened':False,'mode':'independent_clean_plate_rebinding' if args.proof else 'recovered_photographic_layer_recomposition','source_scope':'Visible photographic pixels reused; hidden regions inferred. This is not independent resynthesis of the reference footage.','sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'engine_sha256':hashlib.sha256(Path(sys.modules['visual_fidelity.geometric_replay'].__file__).read_bytes()).hexdigest(),'timeline_sha256':hashlib.sha256((R/'timeline.json').read_bytes()).hexdigest()}
 (out.with_suffix('.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
