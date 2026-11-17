"""Render declarative geometric edits from NEW footage and independently bound mattes.

Each frame declares its source clock, crop, masks, foreground and optional tint.
No reference photography or reference-specific coordinates are embedded here.
"""
from pathlib import Path
from collections import OrderedDict
from fractions import Fraction
import argparse,hashlib,json,subprocess
import cv2,numpy as np
from PIL import Image
from .geometric_replay import mask,compose,VERSION as MASK_VERSION
from .edit_contract import validate_edit
from .music_sync import edited_audio_filter
from .motion_layers import transform_layer
from .motion_binding import (transform_at, record_motion_use, motion_use_report,
                             MotionProfilePool)
VERSION='1.3.0'

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


def _motion_targets(row):
    if 'motion' in row or (row.get('base') or {}).get('motion') is not None or (row.get('tint') or {}).get('motion') is not None:
        raise ValueError('Measured motion is supported only on foreground and masked inserts')
    for name in ('foreground','insert'):
        if (row.get(name) or {}).get('motion') is not None:
            if name=='insert' and 'layers' in row:
                raise ValueError('Top-level insert motion is inactive when independent layers are present')
            if name=='foreground' and 'box' in row[name]:
                raise ValueError('Foreground box conflicts with measured placement; remove it explicitly')
            yield name,row[name]['motion']
    for item in row.get('layers',[]):
        if 'motion' in item or 'motion' in item.get('mask',{}):
            raise ValueError('Layer motion must be attached to its insert and moves its coverage together')
        if item.get('insert',{}).get('motion') is not None:
            yield 'layer:'+item['id'],item['insert']['motion']


def _preflight_motion(data,profiles):
    size=(data['width'],data['height']);rate=Fraction(str(data['fps']))
    for row in data['frame_bindings']:
        for _,binding in _motion_targets(row):
            if binding.get('stage')!='masked_canvas':
                raise ValueError('Geometric motion requires stage masked_canvas')
            transform_at(binding,float(row['frame']/rate),size,size,profiles=profiles)


def _move_masked(rgb,alpha,binding,output_time,usage,frame,target,profiles):
    """Move color and coverage as one premultiplied RGBA layer.

    Channel order is preserved, including the BGR convention of this renderer.
    The incoming raster is the already cropped/masked output-size canvas.
    """
    if binding.get('stage')!='masked_canvas':
        raise ValueError('Geometric motion requires stage masked_canvas')
    h,w=rgb.shape[:2]
    transform=transform_at(binding,output_time,(w,h),(w,h),profiles=profiles)
    rgba=np.dstack([rgb,np.rint(np.clip(alpha,0,1)*255).astype(np.uint8)])
    moved=np.asarray(transform_layer(Image.fromarray(rgba),transform,(w,h)))
    record_motion_use(usage,binding,frame,output_time,target)
    return moved[:,:,:3],moved[:,:,3].astype(np.float32)/255


def render_frame(data,row,sources,root,motion_usage=None,*,profiles=None):
    """Render one bound output frame, shared by previews and the encoded export."""
    root=Path(root);W,H=data['width'],data['height']
    output_time=float(row['frame']/Fraction(str(data['fps'])))
    usage={} if motion_usage is None else motion_usage
    if profiles is None:profiles=MotionProfilePool(data.get('motion_profiles',{}))
    # Manual manifests receive the same target validation as cadence bindings.
    list(_motion_targets(row))
    def layer(item):return viewport(sources.frame(item),item.get('view',[.5,.5,1]),W,H)
    base=layer(row['base']);fg=None
    if row.get('foreground'):
        f=row['foreground'];rgb=sources.frame(f);alpha=cv2.imread(str(root/f['matte']),0)
        if alpha is None:raise FileNotFoundError(f['matte'])
        if rgb.shape[:2]!=alpha.shape:raise ValueError('Matte must match source raster')
        view=f.get('view',[.5,.5,1]);rgb=viewport(rgb,view,W,H);alpha=viewport(alpha,view,W,H)
        if f.get('motion') is not None:
            rgb,coverage=_move_masked(rgb,alpha.astype(np.float32)/255,f['motion'],output_time,usage,row['frame'],'foreground',profiles)
            fg=np.dstack([rgb,np.rint(coverage*255).astype(np.uint8)])
        else:fg=place_foreground(rgb,alpha,f.get('box',[0,0,1,1]),W,H)
    if 'layers' in row:
        rendered_layers=[]
        for item in row['layers']:
            rgb=layer(item['insert']);coverage=mask(item['mask'],W,H,frame=row['frame'])
            if item['insert'].get('motion') is not None:
                rgb,coverage=_move_masked(rgb,coverage,item['insert']['motion'],output_time,usage,row['frame'],'layer:'+item['id'],profiles)
            rendered_layers.append((item['depth'],rgb,coverage))
        image=compose_layers(base,fg,rendered_layers)
    else:
        if 'mask_file' in row:
            alpha=cv2.imread(str(root/row['mask_file']),0)
            if alpha is None:raise FileNotFoundError(row['mask_file'])
            alpha=viewport(alpha,row['base'].get('view',[.5,.5,1]),W,H).astype(np.float32)/255
        else:alpha=mask(row.get('mask',{'kind':'empty'}),W,H,frame=row['frame'])
        alpha*=float(np.clip(row.get('mask_opacity',1),0,1))
        item=row.get('insert',row['base'])
        if row.get('fit_insert_to_mask'):
            insert=fit_insert(sources.frame(item),item.get('view',[.5,.5,1]),alpha)
        else:insert=layer(item)
        if item.get('motion') is not None:
            insert,alpha=_move_masked(insert,alpha,item['motion'],output_time,usage,row['frame'],'insert',profiles)
        image=compose(base,insert,alpha,fg)
    if row.get('tint'):
        t=row['tint'];ta=cv2.imread(str(root/t['matte']),0)
        if ta is None:raise FileNotFoundError(t['matte'])
        ta=viewport(ta,t.get('view',[.5,.5,1]),W,H).astype(np.float32)/255
        ta*=mask(t['mask'],W,H)*t.get('opacity',1)
        fill=np.empty_like(image);fill[:]=list(reversed(t['rgb']))
        image=compose(image,fill,ta)
    return image


def _check_output_paths(manifest,output,data):
    """Preserve the manifest, media, masks and prior exports before any writes."""
    manifest=Path(manifest).resolve();output=Path(output).resolve();root=manifest.parent
    silent=output.with_name(output.stem+'-silent.mp4')
    report=output.with_suffix('.json')
    destinations=[output,silent,report]
    if len(set(destinations))!=len(destinations):
        raise ValueError('Video, temporary encode and report must have distinct paths')
    inputs={manifest}
    for asset in data.get('assets',{}).values():
        for field in ('path','provenance'):
            if asset.get(field):inputs.add((root/asset[field]).resolve())
    if data.get('audio'):inputs.add((root/data['audio']['path']).resolve())
    for row in data.get('frame_bindings',[]):
        if row.get('mask_file'):inputs.add((root/row['mask_file']).resolve())
        for name in ('foreground','tint'):
            if (row.get(name) or {}).get('matte'):
                inputs.add((root/row[name]['matte']).resolve())
    if any(path in inputs for path in destinations):
        raise ValueError('Render video, sidecar or temporary path collides with the manifest or an input')
    existing=[str(path) for path in destinations if path.exists()]
    if existing:
        raise FileExistsError('Preserve the prior render; choose a new output name: '+', '.join(existing))
    return output,silent,report

def render(manifest,output):
    manifest=Path(manifest);root=manifest.parent;data=json.loads(manifest.read_text());W,H=data['width'],data['height'];fps=data['fps'];frames=data['frames']
    output,silent,report_path=_check_output_paths(manifest,output,data)
    duration=float(frames/Fraction(str(fps)))
    if len(data['frame_bindings'])!=frames or [b['frame'] for b in data['frame_bindings']]!=list(range(frames)):raise ValueError('Frame bindings must cover output exactly')
    contract=validate_edit(data,root)
    profiles=MotionProfilePool(data.get('motion_profiles',{}))
    _preflight_motion(data,profiles)
    sources=Sources(root,data['assets']);cv2.setNumThreads(2);output.parent.mkdir(parents=True,exist_ok=True)
    cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{W}x{H}','-r',str(fps),'-i','-','-an','-vf','scale=out_color_matrix=bt709:out_range=tv,format=yuv420p','-c:v','libx264','-preset','medium','-crf','17','-threads','3','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-movflags','+faststart',str(silent)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    motion_usage={}
    try:
        for b in data['frame_bindings']:
            image=render_frame(data,b,sources,root,motion_usage,profiles=profiles)
            proc.stdin.write(image.tobytes())
            if b['frame']%48==0:print('render',b['frame'],flush=True)
        proc.stdin.close()
        if proc.wait()!=0:raise RuntimeError('Encoding failed')
    except BaseException:
        try:proc.stdin.close()
        except (BrokenPipeError,OSError):pass
        if proc.poll() is None:proc.terminate()
        proc.wait();silent.unlink(missing_ok=True)
        raise
    finally:sources.close()
    audio=data.get('audio')
    try:
        if audio:
            p=root/audio['path'];speed=audio.get('speed',1)
            if not .5<=speed<=2:raise ValueError('Audio tempo must be .5..2')
            fade=min(.18,duration)
            filters=edited_audio_filter(audio.get('start',0),speed,duration)+f",afade=t=out:st={duration-fade}:d={fade}"
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(silent),'-i',str(p),'-map','0:v','-map','1:a:0','-c:v','copy','-af',filters,'-c:a','aac','-b:a','192k','-t',str(duration),'-movflags','+faststart',str(output)],check=True)
            sources.hashes['audio']=hashlib.sha256(p.read_bytes()).hexdigest()
            silent.unlink()
        else:silent.replace(output)
    except BaseException:
        # These paths were absent at preflight. A failed mux must not leave a
        # partial final file or block a later clean retry with a stale temporary.
        output.unlink(missing_ok=True);silent.unlink(missing_ok=True)
        raise
    dependencies={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ['music_sync.py','edit_contract.py','geometric_replay.py']}
    report={'dependency_sha256':dependencies,'edit_contract':contract,'video_engine':VERSION,'mask_engine':MASK_VERSION,'frames':frames,'fps':fps,'width':W,'height':H,'input_hashes':sources.hashes,'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'engine_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'render_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'approval':'pending'}
    if motion_usage:
        report['element_motion']=motion_use_report(motion_usage)
        for name in ('motion_binding.py','motion_profile.py','motion_layers.py'):
            dependencies[name]=hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    if 'reference_cadence' in data:
        report['reference_cadence']=data['reference_cadence']
    if 'reference_layers' in data:
        report['reference_layers']=data['reference_layers']
    report_path.write_text(json.dumps(report,indent=2));print(json.dumps(report));return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('manifest',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args();render(args.manifest,args.output)
