"""Manifest-driven hybrid studio editor. Real RGBA subjects, reusable motion kit.

Source clocks are explicit per shot; video reuse never silently retimes audio.
Spatial background sequences may be physical 3D renders, while the subject is
always a 2D cutout. The report preserves this distinction and the engine hashes.
"""
from pathlib import Path
from functools import lru_cache
import argparse,hashlib,json,math,subprocess,time
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from .type_layout import text_mask,render_arc
from .optical_lens import magnify
from .light_sweep import light_sweep,Sweep
from .motion_layers import Transform,transform_layer
from .motion_binding import (transform_at, validate_authored_channels,
                             record_motion_use, motion_use_report)
from .orbit_type import OrbitSpec,render_orbit_type,composite_orbit

VERSION='0.8.0'
SIZE=(720,1280)
def ease(x):return 1-(1-max(0,min(1,x)))**3

def _finite(value, name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(name+' must be a finite number')
    return value


def validate_manifest(d):
    if d.get('version')!=VERSION:raise ValueError('Pin studio editor version '+VERSION)
    if _finite(d.get('fps'), 'fps')<=0:raise ValueError('Positive fps required')
    frames=d.get('frames')
    if not isinstance(frames,int) or isinstance(frames,bool) or frames<=0:raise ValueError('Positive integer frame count required')
    if not isinstance(d.get('shots'),list) or not d['shots']:raise ValueError('Nonempty shots list required')
    cursor=0
    for shot in d['shots']:
        start,end=shot.get('start'),shot.get('end')
        if any(not isinstance(v,int) or isinstance(v,bool) for v in (start,end)):
            raise ValueError('Shot frame bounds must be integers')
        if start!=cursor or end<=cursor:raise ValueError('Shots must cover timeline without gaps/overlap')
        cursor=end
        if shot.get('person') is not None and 'source' not in shot:raise ValueError('Subject requires explicit source clock')
        if shot.get('source') is not None:
            for name,default in [('start',0),('speed',1)]:_finite(shot['source'].get(name,default),'Source '+name)
        for layer in shot.get('layers',[]):
            if layer.get('kind') not in ('text','arc','image','sequence','panel','lens'):raise ValueError('Unknown layer kind')
            if 'z' in layer:_finite(layer['z'],'Layer z')
            if layer.get('motion'):
                if layer['kind']=='lens':raise ValueError('Measured lens motion is not implemented')
                if not isinstance(layer.get('id'),str) or not layer['id']:raise ValueError('Measured layers need an explicit id')
        if shot.get('background',{}).get('motion'):raise ValueError('Measured background motion requires a separate RGBA layer')
        for spec in [shot.get('person')]+shot.get('layers',[]):
            if spec is None:continue
            validate_authored_channels(spec)
            if spec.get('motion') and spec['motion']['stage']!='local_rgba':raise ValueError('Studio motion requires stage local_rgba')
            for name in ('x','y','scale','angle','opacity'):
                if name in spec:_finite(spec[name],name)
            if spec.get('scale',1)<=0 or not 0<=spec.get('opacity',1)<=1:raise ValueError('Invalid scale or opacity')
            keys=spec.get('keys',[]);previous=-float('inf')
            for key in keys:
                value=_finite(key.get('u'),'Key time')
                if not 0<=value<=1 or value<=previous:raise ValueError('Animation keys must increase in [0,1]')
                previous=value
                if set(key)-{'u','x','y','scale','angle','opacity'}:raise ValueError('Unknown transform key')
                for name,v in key.items():_finite(v,'Animation '+name)
                if key.get('scale',1)<=0 or not 0<=key.get('opacity',1)<=1:raise ValueError('Invalid keyed scale or opacity')
    if cursor!=frames:raise ValueError('Timeline does not cover duration')
    return True


def source_frame(shot,local_frame,count):
    # Clock units are decoded source frame indices, independent of output fps.
    if not isinstance(count,int) or count<=0:raise ValueError('Source has no frames')
    if _finite(local_frame,'Local frame')<0:raise ValueError('Local frame cannot be negative')
    source=shot['source'];start=_finite(source.get('start',0),'Source start');speed=_finite(source.get('speed',1),'Source speed')
    idx=int(round(start+local_frame*speed))
    if source.get('loop',False):idx%=count
    if not 0<=idx<count:raise ValueError('Source clock exceeds video; use an explicit loop or bounded rate')
    return idx

def animated(spec,u):
    keys=spec.get('keys',[])
    base={k:spec.get(k,v) for k,v in dict(x=0,y=0,scale=1,angle=0,opacity=1).items()}
    if not keys:return base
    if u<=keys[0]['u']:return {**base,**{k:v for k,v in keys[0].items() if k!='u'}}
    if u>=keys[-1]['u']:return {**base,**{k:v for k,v in keys[-1].items() if k!='u'}}
    for a,b in zip(keys,keys[1:]):
        if a['u']<=u<=b['u']:
            t=(u-a['u'])/(b['u']-a['u'])
            return {k:a.get(k,base[k])+(b.get(k,base[k])-a.get(k,base[k]))*t for k in base}
    return base

def move(img,spec,u,size=SIZE,*,output_time=None):
    if spec.get('motion') is not None:
        validate_authored_channels(spec)
        if spec['motion']['stage']!='local_rgba':raise ValueError('Studio motion requires stage local_rgba')
        if output_time is None:raise ValueError('Measured motion requires the real output time, not shot u')
        transform=transform_at(spec['motion'],output_time,img.size,size,animated(spec,u))
    else:transform=Transform(**animated(spec,u),pivot=tuple(spec.get('pivot',(0,0))))
    return transform_layer(img,transform,size)

@lru_cache(maxsize=24)
def load(path):
    with Image.open(path) as image:return image.convert('RGBA')
@lru_cache(maxsize=64)
def font(path,size,weight=0):
    f=ImageFont.truetype(path,size)
    if weight:
        try:f.set_variation_by_axes([weight])
        except OSError:pass
    return f

@lru_cache(maxsize=6)
def studio(colors):
    top,bottom=colors;y,x=np.mgrid[:SIZE[1],:SIZE[0]]
    radial=np.clip(np.sqrt(((x-350)/850)**2+((y-570)/1400)**2),0,1)
    a=np.array(top)[None,None,:]*(1-radial[:,:,None])+np.array(bottom)[None,None,:]*radial[:,:,None]
    return Image.fromarray(np.uint8(a)).convert('RGBA')

def styled(mask,color,bevel=1,stroke=0,shadow=0):
    a=np.asarray(mask,dtype=float)/255
    if bevel:
        gy,gx=np.gradient(cv2.GaussianBlur(a,(0,0),1.5));light=np.clip(1+(gx+gy)*bevel*.55,.4,1.5)
    else:light=np.ones(a.shape)
    rgb=np.clip(np.asarray(color[:3])[None,None,:]*light[:,:,None],0,255)
    fg=Image.fromarray(np.uint8(np.dstack([rgb,a*255])))
    result=Image.new('RGBA',mask.size)
    if shadow:
        sh=Image.new('RGBA',mask.size,(0,0,0));sh.putalpha(mask.filter(ImageFilter.GaussianBlur(shadow)).point(lambda v:int(v*.42)))
        result.alpha_composite(sh,(2,4))
    if stroke:
        edge=Image.new('RGBA',mask.size,(255,255,245));edge.putalpha(mask.filter(ImageFilter.MaxFilter(stroke*2+1)));result.alpha_composite(edge)
    result.alpha_composite(fg);return result

class Editor:
    def __init__(self,manifest):
        self.path=Path(manifest).resolve();self.root=self.path.parent;self.d=json.loads(self.path.read_text());validate_manifest(self.d)
        self.cap=cv2.VideoCapture(str(self.p(self.d['source'])));self.count=int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT));self.cache={};self.source_next=-1
        if not self.cap.isOpened():raise ValueError('Cannot open source video')
    def p(self,path):return (self.root/path).resolve()
    def _move(self,img,spec,u,target):
        n=getattr(self,'_output_frame',None)
        output_time=None if n is None else n/self.d['fps']
        result=move(img,spec,u,output_time=output_time)
        if spec.get('motion'):
            if not hasattr(self,'_motion_usage'):self._motion_usage={}
            record_motion_use(self._motion_usage,spec['motion'],n,output_time,
                              str(getattr(self,'_output_shot',''))+':'+target)
        return result
    def subject(self,shot,local,u):
        index=source_frame(shot,local,self.count)
        if index!=self.source_next:self.cap.set(cv2.CAP_PROP_POS_FRAMES,index)
        ok,bgr=self.cap.read();self.source_next=index+1
        if not ok:raise RuntimeError('Cannot decode source '+str(index))
        rgba=Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)).convert('RGBA')
        mask=Image.open(self.p(self.d['mattes'])/f'{index:04d}.png').convert('L')
        if rgba.size!=SIZE or mask.size!=SIZE:raise ValueError('Source/matte must match output raster')
        rgba.putalpha(mask)
        return self._move(rgba,shot['person'],u,'person'),index
    def layer(self,l,u,local):
        kind=l['kind'];key=json.dumps(l,sort_keys=True)
        if kind in ('text','arc','panel') and key in self.cache:im=self.cache[key].copy()
        elif kind=='text':
            f=font(str(self.p(l['font'])),l.get('font_size',160),l.get('weight',0));mask=text_mask(l['text'],f,padding=12)
            if l.get('width') or l.get('height'):
                w=l['width'] if 'width' in l else round(mask.width*l['height']/mask.height);h=l.get('height',round(mask.height*w/mask.width));mask=mask.resize((w,h),Image.Resampling.LANCZOS)
            im=styled(mask,l.get('color',[200,0,12]),l.get('bevel',1),l.get('stroke',0),l.get('shadow',0));self.cache[key]=im.copy()
        elif kind=='arc':
            f=font(str(self.p(l['font'])),l['font_size'],l.get('weight',0));im=render_arc(SIZE,l['text'],f,center=l['center'],radius=l['radius'],center_angle=l.get('center_angle',0),tracking=l.get('tracking',0),color=tuple(l.get('color',[255,255,245,255])))
            im=styled(im.getchannel('A'),l.get('color',[255,255,245]),1,l.get('stroke',0),l.get('shadow',2));self.cache[key]=im.copy()
        elif kind in ('image','panel'):
            im=load(str(self.p(l['path']))).copy()
            if kind=='panel':self.cache[key]=im.copy()
        elif kind=='sequence':
            idx=round(l.get('first',1)+(l['last']-l.get('first',1))*u);im=load(str(self.p(l['pattern'].format(frame=idx)))).copy()
        else:raise ValueError(kind)
        if l.get('sweep'):im=light_sweep(im,(u*l.get('sweep_cycles',1))%1,Sweep(intensity=l.get('sweep_intensity',.32),width=.12))
        if l.get('resize'):im=im.resize(tuple(l['resize']),Image.Resampling.LANCZOS)
        if l.get('quad_file'):
            points=json.loads(self.p(l['quad_file']).read_text());quad=np.float32(points[round(u*(len(points)-1))]);w,h=im.size
            M=cv2.getPerspectiveTransform(np.float32([[0,0],[w,0],[w,h],[0,h]]),quad)
            arr=np.asarray(im,dtype=np.float32)/255;arr[:,:,:3]*=arr[:,:,3:4];arr=cv2.warpPerspective(arr,M,SIZE)
            arr[:,:,:3]/=np.maximum(arr[:,:,3:4],1e-6);im=Image.fromarray(np.uint8(np.clip(arr,0,1)*255))
            # Quad places the asset in canvas space; declared transforms still
            # animate that placed layer, including opacity.
            im=self._move(im,l,u,'layer:'+str(l.get('id',kind)))
        else:im=self._move(im,l,u,'layer:'+str(l.get('id',kind)))
        enter=l.get('enter',0)
        if enter and local<enter:
            t=ease(local/enter);im=move(im,{'y':(1-t)*l.get('enter_y',50),'opacity':t},u)
        return im
    def frame(self,n):
        if not isinstance(n,int) or not 0<=n<self.d['frames']:raise ValueError('Frame outside timeline')
        s=next(s for s in self.d['shots'] if s['start']<=n<s['end']);local=n-s['start'];u=local/max(1,s['end']-s['start']-1)
        self._output_frame=n;self._output_shot=s['id']
        bg=s.get('background',{});colors=tuple(tuple(c) for c in bg.get('colors',[[249,250,234],[218,222,210]]))
        out=studio(colors).copy()
        if bg.get('pattern'):
            idx=round(bg.get('first',1)+(bg['last']-bg.get('first',1))*u);out.alpha_composite(load(str(self.p(bg['pattern'].format(frame=idx)))).resize(SIZE,Image.Resampling.LANCZOS))
        if bg.get('diagonal'):
            d=ImageDraw.Draw(out);d.polygon([(-500,550),(720,-150),(1220,50),(0,800)],fill=(225,0,9,255));d.polygon([(-400,1200),(720,400),(1200,600),(0,1500)],fill=(202,0,7,255))
        behind=[l for l in s.get('layers',[]) if l.get('z',1)<0];front=[l for l in s.get('layers',[]) if l.get('z',1)>=0]
        for l in sorted(behind,key=lambda l:l.get('z',-1)):out.alpha_composite(self.layer(l,u,local))
        subject=None
        if s.get('person') is not None:
            subject,index=self.subject(s,local,u)
            # Authored contact shadow, same transform as source subject. Not recovered physical light.
            shadow=Image.new('RGBA',SIZE);dr=ImageDraw.Draw(shadow);dr.ellipse([155,1104,570,1188],fill=(20,15,9,85));shadow=shadow.filter(ImageFilter.GaussianBlur(20));out.alpha_composite(self._move(shadow,s['person'],u,'person_shadow'))
            if s.get('orbit'):
                o=s['orbit'];params={k:v for k,v in o.items() if k not in ['text','font','phase_start','phase_end']};params['size']=SIZE;params['phase']=o.get('phase_start',0)+u*(o.get('phase_end',2)-o.get('phase_start',0));params['highlight_phase']=u
                rear,fore=render_orbit_type(o['text'],str(self.p(o['font'])),OrbitSpec(**params));out=composite_orbit(out,subject,rear,fore)
            else:out.alpha_composite(subject)
        for l in sorted(front,key=lambda l:l.get('z',1)):
            if l['kind']=='lens':
                if l.get('motion'):raise ValueError('Measured lens motion is not implemented')
                t=animated(l,u);out.alpha_composite(magnify(out,(t['x'],t['y']),l.get('radius',120),l.get('zoom',1.4),t['angle']))
            else:out.alpha_composite(self.layer(l,u,local))
        if s.get('transition') and local<s.get('transition_frames',5):
            t=1-local/s.get('transition_frames',5)
            if s['transition']=='flash':out=Image.blend(out,Image.new('RGBA',SIZE,(255,255,244,255)),t*.8)
            elif s['transition']=='blur':out=out.filter(ImageFilter.GaussianBlur(t*12))
        return out.convert('RGB')
    def render(self,output,start=0,end=None):
        end=self.d['frames'] if end is None else min(end,self.d['frames'])
        if not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end:raise ValueError('Render range must contain frames inside the timeline')
        out=Path(output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
        self._motion_usage={}
        cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','720x1280','-r',str(self.d['fps']),'-i','-']
        if self.d.get('audio'):cmd+=['-ss',str(start/self.d['fps']),'-i',str(self.p(self.d['audio']))]
        cmd+=['-map','0:v:0']
        if self.d.get('audio'):cmd+=['-map','1:a:0','-c:a','aac','-b:a','192k']
        cmd+=['-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-t',str((end-start)/self.d['fps']),'-movflags','+faststart',str(out)]
        p=subprocess.Popen(cmd,stdin=subprocess.PIPE);t=time.time()
        try:
            for n in range(start,end):
                p.stdin.write(np.asarray(self.frame(n)).tobytes())
                if n%48==0:print(json.dumps({'frame':n,'end':end,'elapsed':round(time.time()-t,1)}),flush=True)
        except BaseException:
            p.stdin.close()
            p.terminate()
            p.wait()
            raise
        else:p.stdin.close()
        if p.wait():raise RuntimeError('FFmpeg export failed')
        hashes={name:hashlib.sha256(Path(__file__).with_name(name+'.py').read_bytes()).hexdigest() for name in ['studio_edit','studio_matte','orbit_type','type_layout','motion_layers','light_sweep','optical_lens']}
        report={'engine_version':VERSION,'manifest_sha256':hashlib.sha256(self.path.read_bytes()).hexdigest(),'engine_files':hashes,'rendered_frames':[start,end],'fps':self.d['fps'],'seconds':(end-start)/self.d['fps'],'elapsed_seconds':time.time()-t,'actual_engine_executed':True,'subject':'Original RGB + supervised temporal alpha; 2D card','background':'3D rendered passes where declared; otherwise 2D','source_reuse':[{'shot':s['id'],'source':s.get('source')} for s in self.d['shots']],'user_approved':False,'perceptual_playback':False}
        if self._motion_usage:
            report['element_motion']=motion_use_report(self._motion_usage)
            for name in ('motion_binding','motion_profile'):
                hashes[name]=hashlib.sha256(Path(__file__).with_name(name+'.py').read_bytes()).hexdigest()
        out.with_suffix('.render.json').write_text(json.dumps(report,indent=2));return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest');p.add_argument('output');p.add_argument('--start',type=int,default=0);p.add_argument('--end',type=int);p.add_argument('--video-only',action='store_true');a=p.parse_args();editor=Editor(a.manifest)
    if a.video_only:editor.d.pop('audio',None)
    editor.render(a.output,a.start,a.end)
if __name__=='__main__':main()
