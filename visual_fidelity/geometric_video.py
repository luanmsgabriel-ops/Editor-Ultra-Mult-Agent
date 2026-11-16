"""Render declarative geometric edits from NEW footage and independently bound mattes.

Each frame declares its source clock, crop, masks, foreground and optional tint.
No reference photography or reference-specific coordinates are embedded here.
"""
from pathlib import Path
from collections import OrderedDict
from fractions import Fraction
import argparse,hashlib,json,subprocess
import cv2,numpy as np
from .geometric_replay import mask,compose,VERSION as MASK_VERSION
from .edit_contract import validate_edit
from .music_sync import edited_audio_filter
VERSION='1.2.0'

def viewport(image,view,width,height):
    """Aspect-preserving crop with center in normalized input coordinates and zoom>=1."""
    ih,iw=image.shape[:2];cx,cy,z=view
    if z<1 or not np.isfinite(view).all():raise ValueError('Invalid viewport')
    cropw=min(iw,ih*width/height)/z;croph=cropw*height/width
    cx=np.clip(cx*iw,cropw/2,iw-cropw/2);cy=np.clip(cy*ih,croph/2,ih-croph/2)
    transform=np.array([[width/cropw,0,width/2-cx*width/cropw],[0,height/croph,height/2-cy*height/croph]],np.float32)
    return cv2.warpAffine(image,transform,(width,height),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)

def place_foreground(rgb,alpha,box,width,height):
    """Scale straight RGBA with premultiplied interpolation; transparent outside box."""
    x,y,w,h=box
    if w<=0 or h<=0:raise ValueError('Foreground box must have positive size')
    rgba=np.dstack([rgb.astype(np.float32)/255,alpha.astype(np.float32)/255])
    rgba[:,:,:3]*=rgba[:,:,3:4]
    ih,iw=rgba.shape[:2];M=np.array([[w*width/iw,0,x*width],[0,h*height/ih,y*height]],np.float32)
    out=cv2.warpAffine(rgba,M,(width,height),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0,0))
    out[:,:,:3]=np.divide(out[:,:,:3],out[:,:,3:4],out=np.zeros_like(out[:,:,:3]),where=out[:,:,3:4]>1e-6)
    return np.rint(np.clip(out,0,1)*255).astype(np.uint8)

class Sources:
    def __init__(self,root,assets):self.root=root;self.assets=assets;self.caps={};self.cache=OrderedDict();self.hashes={}
    def path(self,key):return self.root/self.assets[key]['path']
    def frame(self,binding):
        key=binding['source'];index=binding.get('frame',0);cachekey=(key,index)
        if cachekey in self.cache:
            self.cache.move_to_end(cachekey);return self.cache[cachekey]
        p=self.path(key)
        if key not in self.hashes:self.hashes[key]=hashlib.sha256(p.read_bytes()).hexdigest()
        if self.assets[key]['kind']=='image':image=cv2.imread(str(p))
        else:
            if key not in self.caps:self.caps[key]=cv2.VideoCapture(str(p))
            cap=self.caps[key]
            if int(cap.get(cv2.CAP_PROP_POS_FRAMES))!=index:cap.set(cv2.CAP_PROP_POS_FRAMES,index)
            ok,image=cap.read()
            if not ok:raise ValueError(f'Cannot decode {key}:{index}')
        if image is None:raise FileNotFoundError(p)
        self.cache[cachekey]=image
        while len(self.cache)>24:self.cache.popitem(last=False)
        return image
    def close(self):
        for c in self.caps.values():c.release()

def fit_insert(image,view,coverage):
    """Fit a source crop to a portal's visible bounds, preserving image aspect."""
    H,W=coverage.shape;result=np.zeros((H,W,3),np.uint8)
    ys,xs=np.where(coverage>.001)
    if len(xs):
        x0,x1=int(xs.min()),int(xs.max())+1;y0,y1=int(ys.min()),int(ys.max())+1
        result[y0:y1,x0:x1]=viewport(image,view,x1-x0,y1-y0)
    return result

def compose_layers(base, foreground, layers):
    """Compose independent masked inserts in subject-relative depth order."""
    image = base
    for depth in ('behind_subject', 'in_front_of_subject'):
        if depth == 'in_front_of_subject':
            image = compose(image, foreground, np.ones(image.shape[:2], np.float32))
        for position, insert, coverage in layers:
            if position == depth:
                image = compose(image, insert, coverage)
    return image

def render(manifest,output):
    manifest=Path(manifest);root=manifest.parent;data=json.loads(manifest.read_text());W,H=data['width'],data['height'];fps=data['fps'];frames=data['frames']
    duration=float(frames/Fraction(str(fps)))
    if len(data['frame_bindings'])!=frames or [b['frame'] for b in data['frame_bindings']]!=list(range(frames)):raise ValueError('Frame bindings must cover output exactly')
    contract=validate_edit(data,root)
    sources=Sources(root,data['assets']);cv2.setNumThreads(2);output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);silent=output.with_name(output.stem+'-silent.mp4')
    cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{W}x{H}','-r',str(fps),'-i','-','-an','-vf','scale=out_color_matrix=bt709:out_range=tv,format=yuv420p','-c:v','libx264','-preset','medium','-crf','17','-threads','3','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-movflags','+faststart',str(silent)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    def layer(b):return viewport(sources.frame(b),b.get('view',[.5,.5,1]),W,H)
    for b in data['frame_bindings']:
        base = layer(b['base'])
        fg=None
        if b.get('foreground'):
            f=b['foreground'];rgb=sources.frame(f);alpha=cv2.imread(str(root/f['matte']),0)
            if alpha is None:raise FileNotFoundError(f['matte'])
            if rgb.shape[:2]!=alpha.shape:raise ValueError('Matte must match source raster')
            view=f.get('view',[.5,.5,1]);rgb=viewport(rgb,view,W,H);alpha=viewport(alpha,view,W,H)
            fg=place_foreground(rgb,alpha,f.get('box',[0,0,1,1]),W,H)
        if 'layers' in b:
            rendered_layers = [
                (item['depth'], layer(item['insert']), mask(item['mask'], W, H, frame=b['frame']))
                for item in b['layers']
            ]
            image = compose_layers(base, fg, rendered_layers)
        else:
            if 'mask_file' in b:
                alpha = cv2.imread(str(root / b['mask_file']), 0)
                if alpha is None:
                    raise FileNotFoundError(b['mask_file'])
                alpha = viewport(alpha, b['base'].get('view', [.5, .5, 1]), W, H).astype(np.float32) / 255
            else:
                alpha = mask(b.get('mask', {'kind': 'empty'}), W, H, frame=b['frame'])
            alpha *= float(np.clip(b.get('mask_opacity', 1), 0, 1))
            insert_binding = b.get('insert', b['base'])
            if b.get('fit_insert_to_mask'):
                insert = fit_insert(sources.frame(insert_binding),
                                    insert_binding.get('view', [.5, .5, 1]), alpha)
            else:
                insert = layer(insert_binding)
            image = compose(base, insert, alpha, fg)
        if b.get('tint'):
            t=b['tint'];ta=cv2.imread(str(root/t['matte']),0)
            if ta is None:raise FileNotFoundError(t['matte'])
            ta=viewport(ta,t.get('view',[.5,.5,1]),W,H).astype(np.float32)/255
            ta*=mask(t['mask'],W,H)*t.get('opacity',1)
            fill=np.empty_like(image);fill[:]=list(reversed(t['rgb']))
            image=compose(image,fill,ta)
        proc.stdin.write(image.tobytes())
        if b['frame']%48==0:print('render',b['frame'],flush=True)
    proc.stdin.close();sources.close()
    if proc.wait()!=0:raise RuntimeError('Encoding failed')
    audio=data.get('audio')
    if audio:
        p=root/audio['path'];speed=audio.get('speed',1)
        if not .5<=speed<=2:raise ValueError('Audio tempo must be .5..2')
        fade=min(.18,duration)
        filters=edited_audio_filter(audio.get('start',0),speed,duration)+f",afade=t=out:st={duration-fade}:d={fade}"
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(silent),'-i',str(p),'-map','0:v','-map','1:a:0','-c:v','copy','-af',filters,'-c:a','aac','-b:a','192k','-t',str(duration),'-movflags','+faststart',str(output)],check=True);silent.unlink()
        sources.hashes['audio']=hashlib.sha256(p.read_bytes()).hexdigest()
    else:silent.replace(output)
    dependencies={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ['music_sync.py','edit_contract.py','geometric_replay.py']}
    report={'dependency_sha256':dependencies,'edit_contract':contract,'video_engine':VERSION,'mask_engine':MASK_VERSION,'frames':frames,'fps':fps,'width':W,'height':H,'input_hashes':sources.hashes,'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'engine_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'render_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'approval':'pending'}
    if 'reference_cadence' in data:
        report['reference_cadence']=data['reference_cadence']
    if 'reference_layers' in data:
        report['reference_layers']=data['reference_layers']
    output.with_suffix('.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('manifest',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args();render(args.manifest,args.output)
