"""Plan and render visual anchors on a new video using a local editing plan."""
import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from .anchor_camera import parse_colmap, project
from .anchor_graphics import composite, make_art, motion
from .anchor_tracking import track_planar
from .anchor_ocr import contains, detect, engine
from .auto_placement import choose_anchor
from .body_anchors import build_orbit_art, follow_quad, orbit_geometry, render_orbit, track_sidecar
from .editorial_motion import composite_editorial
from .body_depth import composite_hand_context, composite_orbit_context


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def screen_quad(center, size):
    sx,sy = np.asarray(size)/2
    x,y = center
    return np.float32([[x-sx,y-sy],[x+sx,y-sy],[x+sx,y+sy],[x-sx,y+sy]])


def num_pair(value):
    pair=np.asarray(value,dtype=float)
    if pair.shape!=(2,) or not np.isfinite(pair).all() or np.any(pair<=0) or np.any(pair>=1):
        raise ValueError('size precisa conter largura e altura normalizadas entre 0 e 1.')
    return pair


def quad(value):
    points=np.asarray(value,dtype='float32')
    if points.shape!=(4,2) or not np.isfinite(points).all() or np.max(np.abs(points))>100:
        raise ValueError('Uma âncora precisa de quatro cantos 2D finitos.')
    if not cv2.isContourConvex(points) or cv2.contourArea(points,oriented=True)<1e-6:
        raise ValueError('Ordene os cantos como superior esquerdo/direito e inferior direito/esquerdo.')
    return points


def shot_starts(frames):
    cuts=[0]
    if not len(frames):
        return cuts
    mini=[cv2.resize(frame,(72,48),interpolation=cv2.INTER_AREA) for frame in frames]
    for index,(previous,current) in enumerate(zip(mini,mini[1:]),1):
        diff=np.mean(cv2.absdiff(previous,current))
        if diff>32 and np.count_nonzero(np.max(cv2.absdiff(previous,current),axis=2)>38)>.42*72*48:
            cuts.append(index)
    return cuts


def interval(effect, fps):
    if 'frames' in effect:
        pair=effect['frames']
        if len(pair)!=2 or any(type(x)!=int for x in pair):
            raise ValueError('frames precisa ser [início inclusivo, fim exclusivo] em inteiros.')
        start,end=pair
    else:
        start,end=(round(float(effect[k])*fps) for k in ('start','end'))
    if start<0 or end<=start:
        raise ValueError('O intervalo da camada precisa ter duração positiva.')
    return start,end


def from_transcript(transcript):
    segments = transcript.get('segments')
    if not isinstance(segments,list):
        raise ValueError('A transcrição precisa de segmentos com start, end e text.')
    return [{'text':' '.join(str(segment['text']).strip().split()), 'start':segment['start'],
             'end':segment['end'], 'anchor':{'mode':'screen'}} for segment in segments
            if str(segment.get('text','')).strip()]


def frames_of(path, analysis=False):
    reader=cv2.VideoCapture(str(path))
    try:
        while True:
            ok,frame=reader.read()
            if not ok:
                return
            if analysis:
                h,w=frame.shape[:2]
                scale=min(1.,480/max(h,w))
                frame=cv2.resize(frame,(max(1,round(w*scale)),max(1,round(h*scale))),
                                 interpolation=cv2.INTER_AREA)
            yield frame
    finally:
        reader.release()


def sample_boxes(boxes, ids):
    if isinstance(boxes,dict):
        return [boxes.get(str(index),[]) for index in ids]
    return boxes


def valid_projection(points):
    try:
        projected=quad(points)
    except ValueError:
        return None
    if np.any(projected.max(axis=0)<=0) or np.any(projected.min(axis=0)>=1):
        return None
    return projected


def poses_at(roll, elapsed, duration):
    if not roll:
        return None
    steps=sorted(int(index) for index in roll)
    target=(elapsed/max(1,duration-1))*steps[-1]
    end=int(np.searchsorted(steps,target))
    if end==0:
        return roll[str(steps[0])]
    if end>=len(steps):
        return roll[str(steps[-1])]
    start,stop=steps[end-1:end+1]
    phase=(target-start)/(stop-start)
    return np.asarray(roll[str(start)])*(1-phase)+np.asarray(roll[str(stop)])*phase


@dataclass
class Prepared:
    effect: dict
    first: int
    last: int
    corners: dict
    palette: dict
    report: dict
    size: tuple
    glyph_profile: dict
    profile_aspect: float | None
    body: dict = field(default_factory=dict)
    body_spec: dict = field(default_factory=dict)
    body_events: list = field(default_factory=list)
    body_masks: Path | None = None


def validate_effect(effect, root):
    if ('text' in effect)==('asset' in effect) or ('text' in effect and not effect['text'].strip()):
        raise ValueError('A camada precisa de texto não vazio ou de um ativo.')
    if 'asset' in effect and not (root/effect['asset']).is_file():
        raise ValueError(f'Ativo ausente: {effect["asset"]}')
    if effect.get('animation','pop') not in {'pop','slide','fade','hold'}:
        raise ValueError('Animação desconhecida.')
    color=effect.get('color')
    if color is not None and (len(color)!=3 or any(type(x)!=int or not 0<=x<=255 for x in color)):
        raise ValueError('color precisa ser uma lista RGB de três inteiros entre 0 e 255.')


def prepare(effect, frames, cuts, fps, resolution, root, occupied, ocr=None, body_default=None):
    validate_effect(effect,root)
    first,last=interval(effect,fps)
    last=min(last,len(frames))
    if first>=last:
        raise ValueError('A camada começa depois do fim do vídeo.')
    size=num_pair(effect.get('size',[.53,.14]))
    pixels=tuple(max(4,round(s*dimension)) for s,dimension in zip(size,resolution))
    requested=effect.get('anchor',{})
    mode=requested.get('mode','screen')
    if mode not in {'screen','planar','world','body','orbit'}:
        raise ValueError(f'Modo de âncora desconhecido: {mode}')
    style=effect.get('animation','pop')
    profile_data=load(root/effect['glyph_profile']) if effect.get('glyph_profile') else {}
    glyph_profile=profile_data.get('frames',{})
    aspect=profile_data.get('aspect')
    if aspect is not None and (not np.isfinite(aspect) or aspect<=0):
        raise ValueError('aspect em perfil tipográfico precisa ser positivo.')
    corners,palette={},{}
    body,events={},[]
    masks=None
    audit={'mode':mode,'frames':[first,last],'shots':[]}
    if mode in {'body','orbit'}:
        pose=requested.get('pose')
        if not pose and not body_default:
            raise ValueError('Informe anchor.pose ou --body-model para rastreamento corporal.')
        path=root/pose if pose else body_default[0]
        masks_spec=effect.get('occlusion') or requested.get('masks')
        masks=root/masks_spec if masks_spec else (body_default[1] if not pose and body_default else None)
        data=load(path)
        body,events=track_sidecar(data,first,last,cuts,fps,requested)
        audit.update({'provider':data.get('provider','landmarks_json'),'landmark':requested.get('landmark','body_center'),
                      'events':events,'persons':sorted({sample.person_id for sample in body.values()})})
        if mode=='body':
            for i,item in body.items():
                mapped=follow_quad(item,resolution,size,requested)
                if mapped is not None:
                    corners[i]=mapped
        else:
            mask_frames=0
            for i,item in body.items():
                center,rx,ry=orbit_geometry(item,resolution,requested)
                corners[i]=screen_quad(center/np.asarray(resolution),[2*rx/resolution[0],2*ry/resolution[1]])
                mask_frames+=int(masks is not None and (masks/f'{i:06d}.png').is_file())
            audit.update({'frames_with_occlusion_mask':mask_frames,
                          'review_required':mask_frames<len(body)})
    elif mode=='screen':
        previous=None
        boundaries=[first]+[index for index in cuts if first<index<last]+[last]
        for start,stop in zip(boundaries,boundaries[1:]):
            ids=sorted(set(np.linspace(start,stop-1,min(7,stop-start)).astype(int).tolist()))
            protected=sample_boxes(effect.get('protected'),ids)
            recognized=[ocr(i) for i in ids] if ocr else []
            # Existing layers and recognized text are obstacles too.
            if recognized and 'text' in effect and any(contains(one['lines'],effect['text'])
                                                        for one in recognized):
                audit['shots'].append({'frames':[start,stop],'rendered':False,
                                       'reason':'existing_text'})
                continue
            if recognized or any(occupied.get(i) for i in ids):
                shared=protected is not None and not isinstance(effect.get('protected'),dict)
                protected=[list(protected if shared else (protected or [[] for _ in ids])[j])+
                           occupied.get(i,[])+(recognized[j]['boxes'] if recognized else [])
                           for j,i in enumerate(ids)]
            candidates=[]
            padding=1.55 if style=='slide' else 1.16 if style=='pop' else 1.
            for factor in (1., .83, .70, .63):
                selected=size*factor
                envelope=np.minimum(selected*[padding if style=='pop' else 1.,padding],.99)
                choice=choose_anchor([frames[i] for i in ids],envelope,protected=protected,
                                     previous=previous)
                candidates.append((choice,selected))
                if choice['protected_overlap']==0 and choice.get('subject_overlap_estimate',0)<=.10:
                    break
            choice,selected=min(candidates,key=lambda item:(
                item[0]['protected_overlap']>0,
                item[0]['protected_overlap'],
                item[0].get('subject_overlap_estimate',0)>.10,
                max(0.,item[0].get('subject_overlap_estimate',0)-.10)))
            safe=choice['protected_overlap']==0
            if safe and choice.get('subject_overlap_estimate',0)>.20:
                choice['review_required']=True
            audit['shots'].append({'frames':[start,stop],**choice,'rendered':safe})
            if not safe:
                continue
            previous=choice['center']
            box=screen_quad(previous,selected)
            for index in range(start,stop):
                corners[index]=box
                palette[index]=choice['color']
    elif mode=='planar':
        if any(first<cut<last for cut in cuts):
            cutoff=next(cut for cut in cuts if first<cut<last)
        else:
            cutoff=last
        trace=root/requested['tracks'] if requested.get('tracks') else None
        if trace and cutoff!=last:
            raise ValueError('Uma trilha TAPIR precisa coincidir com um único plano sem corte.')
        result=track_planar(frames[first:cutoff],quad(requested['quad']),tracks=trace)
        audit['provider']='tapir_npz' if trace is not None else 'opencv'
        audit['stop_at_cut']=cutoff if cutoff!=last else None
        for i,points in enumerate(result,first):
            if points is not None:
                mapped=valid_projection(points)
                if mapped is not None:
                    corners[i]=mapped
    else:
        if 'projection' in requested:
            quads=load(root/requested['projection'])['quads']
            for i in range(first,last):
                if quads.get(str(i)) is not None:
                    mapped=valid_projection(quads[str(i)])
                    if mapped is not None:
                        corners[i]=mapped
            audit['provider']='blender_projection'
        else:
            cameras=load(root/requested['cameras'])['cameras']
            for i in range(first,last):
                mapped=project(requested['corners_3d'],cameras.get(str(i)))
                if mapped is not None:
                    valid=valid_projection(mapped)
                    if valid is not None:
                        corners[i]=valid
            audit['provider']='pinhole_projection'
    for i,box in corners.items():
        low=np.clip(box.min(axis=0),0,1)
        high=np.clip(box.max(axis=0),0,1)
        if np.all(high>low):
            occupied[i].append([*low.tolist(),*high.tolist()])
    audit.update({'layer':effect.get('id',effect.get('text',effect.get('asset'))),
                  'animation':style,'tracked_frames':len(corners),'missing_frames':last-first-len(corners),
                  'sample_centers':{str(i): np.round(corners[i].mean(axis=0),5).tolist()
                                    for i in sorted(corners)[::max(1,len(corners)//6)]}})
    if mode in {'planar','world'} and corners:
        initial=corners[min(corners)]*resolution
        widths=[np.linalg.norm(initial[1]-initial[0]),np.linalg.norm(initial[2]-initial[3])]
        heights=[np.linalg.norm(initial[3]-initial[0]),np.linalg.norm(initial[2]-initial[1])]
        pixels=(max(4,min(resolution[0],round(np.mean(widths)))),
                max(4,min(resolution[1],round(np.mean(heights)))))
    return Prepared(effect,first,last,corners,palette,audit,pixels,glyph_profile,aspect,body,requested,events,masks)


def occlusion_at(root, spec, index, shape):
    folder=root/spec
    path=folder/f'{index:06d}.png'
    if not path.is_file():
        return None
    image=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f'Máscara não pôde ser decodificada: {path}')
    if image.shape!=shape:
        image=cv2.resize(image,(shape[1],shape[0]),interpolation=cv2.INTER_LINEAR)
    return image


def render(picture, destination, resolution, fps, layers, font, root):
    w,h=resolution
    command=['ffmpeg','-v','error','-y','-f','rawvideo','-pixel_format','bgr24','-video_size',
             f'{w}x{h}','-framerate',str(fps),'-i','-','-i',str(picture),'-map','0:v:0',
             '-map','1:a:0?','-c:v','libx264','-threads','4','-preset','fast','-crf','18',
             '-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart',str(destination)]
    cache={}
    with subprocess.Popen(command,stdin=subprocess.PIPE) as encoder:
        for index,frame in enumerate(frames_of(picture)):
            for layer_id, layer in enumerate(layers):
                if index not in layer.corners:
                    continue
                effect=layer.effect
                if 'body_depth' in effect:
                    compositor = composite_orbit_context if effect['body_depth']['kind']=='orbit' else composite_hand_context
                    compositor(frame,layer,index,fps)
                    continue
                if 'editorial_scene' in effect:
                    composite_editorial(frame,layer,index,root,cache,fps)
                    continue
                color=tuple(effect.get('color',layer.palette.get(index,[246,248,249])))
                starts=[n for n in layer.body_events if n<=index]
                origin=starts[-1] if starts else layer.first
                speed=max(1,round(float(effect.get('entrance_seconds',.23))*fps))
                key=(layer_id,color)
                if layer.report['mode']=='orbit':
                    if key not in cache:
                        cache[key]=build_orbit_art(effect,layer.body_spec,font,color,root)
                    mask=occlusion_at(root,layer.body_masks,index,frame.shape[:2]) if layer.body_masks is not None else None
                    opacity=1-(1-min(1.,(index-origin+1)/speed))**3
                    render_orbit(frame,layer.body[index],layer.body_spec,cache[key],
                                 (index-origin)/fps,color,mask,opacity)
                    continue
                profile_index=index-origin
                roll=layer.glyph_profile
                poses=poses_at(roll,profile_index,layer.last-layer.first)
                if poses is not None:
                    art=make_art(effect,layer.size,font,color,root,poses,layer.profile_aspect)
                else:
                    if key not in cache:
                        cache[key]=make_art(effect,layer.size,font,color,root)
                    art=cache[key]
                bounds, opacity=motion(layer.corners[index],(index-origin+1)/speed,
                                       effect.get('animation','pop'),
                                       fit_inside=layer.report['mode']=='screen')
                mask=occlusion_at(root,effect['occlusion'],index,frame.shape[:2]) if effect.get('occlusion') else None
                composite(frame,art,bounds,opacity,mask)
            encoder.stdin.write(frame.tobytes())
        encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError('O FFmpeg falhou ao compor o vídeo.')


def conform(source, destination, fps):
    # Decode and plan the same CFR sequence that will be rendered.
    command=['ffmpeg','-nostdin','-v','error','-y','-i',str(source),'-map','0:v:0','-map','0:a:0?',
             '-vf',f'fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1',
             '-c:v','libx264','-crf','14','-threads','4','-preset','veryfast','-c:a','aac',str(destination)]
    subprocess.run(command,check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    run=sub.add_parser('render')
    run.add_argument('source',type=Path)
    run.add_argument('output',type=Path)
    inputs=run.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--plan',type=Path)
    inputs.add_argument('--transcript',type=Path)
    run.add_argument('--font',type=Path)
    run.add_argument('--fps',type=int,default=30)
    run.add_argument('--report',type=Path)
    run.add_argument('--body-model',type=Path,help='Modelo Pose Landmarker .task para âncoras sem JSON.')
    run.add_argument('--gesture-model',type=Path,help='Modelo Gesture Recognizer .task opcional.')
    run.add_argument('--pose-python',default=sys.executable,help='Python do ambiente com MediaPipe.')
    run.add_argument('--body-persons',type=int,default=4)
    run.add_argument('--ocr-language',help='Idioma Tesseract já instalado para proteger texto existente.')
    imported=sub.add_parser('colmap')
    imported.add_argument('model',type=Path)
    imported.add_argument('frame_map',type=Path)
    imported.add_argument('output',type=Path)
    tapir=sub.add_parser('tapir')
    tapir.add_argument('source',type=Path)
    tapir.add_argument('output',type=Path)
    tapir.add_argument('--checkpoint',type=Path,required=True)
    tapir.add_argument('--frames',nargs=2,type=int,required=True)
    tapir.add_argument('--quad',nargs=8,type=float,required=True)
    tapir.add_argument('--fps',type=int,default=30)
    tapir.add_argument('--device',choices=('cpu','cuda'),default='cuda')
    args=parser.parse_args()
    try:
        if args.action=='tapir':
            from .tapir_points import export
            if args.output.suffix.lower()!='.npz' or not 1<=args.fps<=120 or not args.source.is_file():
                raise ValueError('Informe um vídeo local, destino NPZ e FPS entre 1 e 120.')
            export(args.source,args.output,args.checkpoint,args.fps,*args.frames,
                   np.asarray(args.quad).reshape(4,2),args.device)
            return
        if args.action=='colmap':
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps({'cameras':parse_colmap(args.model,load(args.frame_map))},
                                              indent=2)+'\n',encoding='utf-8')
            return
        if not args.source.is_file() or args.source.resolve()==args.output.resolve() or not 1<=args.fps<=120:
            raise ValueError('Informe uma origem existente, destino distinto e FPS entre 1 e 120.')
        plan=args.plan or args.transcript
        effects=load(plan)['effects'] if args.plan else from_transcript(load(plan))
        if not effects:
            raise ValueError('Sem camadas para renderizar.')
        if any('text'in effect for effect in effects) and not (args.font and args.font.is_file()):
            raise ValueError('Informe --font com um arquivo OTF ou TTF local para camadas de texto.')
        root=plan.resolve().parent
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(prefix='video-anchor-') as working:
            picture=Path(working)/'conformed.mp4'
            conform(args.source,picture,args.fps)
            original=next(frames_of(picture),None)
            if original is None:
                raise ValueError('Nenhum quadro decodificado.')
            resolution=original.shape[1::-1]
            frames=list(frames_of(picture,analysis=True))
            cuts=shot_starts(frames)
            occupied=defaultdict(list)
            ocr=None
            if args.ocr_language:
                binary=engine(args.ocr_language)
                ocr=lru_cache(maxsize=512)(lambda i: detect(frames[i],binary,args.ocr_language))
            needs_body=any(e.get('anchor',{}).get('mode') in {'body','orbit'}
                           and not e.get('anchor',{}).get('pose') for e in effects)
            body_default=None
            if needs_body and args.body_model:
                body_data=Path(working)/'body.json'
                masks=Path(working)/'masks'
                cmd=[args.pose_python,'-m','visual_fidelity.body_pose',str(picture),str(body_data),
                     '--model',str(args.body_model),'--fps',str(args.fps),'--persons',str(args.body_persons),
                     '--masks',str(masks)]
                if args.gesture_model:
                    cmd+=['--gesture-model',str(args.gesture_model)]
                subprocess.run(cmd,check=True)
                body_default=(body_data,masks)
            layers=[prepare(effect,frames,cuts,args.fps,resolution,root,occupied,ocr,body_default)
                    for effect in effects]
            render(picture,args.output,resolution,args.fps,layers,args.font,root)
        report={'source':args.source.name,'fps':args.fps,'frames':len(frames),
                'resolution':list(resolution),'shot_starts':cuts,'effects':[layer.report for layer in layers]}
        output=args.report or args.output.with_suffix('.anchors.json')
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except (ValueError,KeyError,TypeError,FileNotFoundError,subprocess.CalledProcessError) as exc:
        parser.exit(1,f'{exc}\n')


if __name__=='__main__':
    main()

