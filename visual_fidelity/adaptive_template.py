"""Analyze original speech and body movement, then apply a visual style."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import json
from pathlib import Path
import re
import subprocess
import unicodedata

import cv2
import numpy as np

from .anchor_graphics import motion
from .body_depth import hand_track, orbit_track, read_alpha, verify_orbit
from .context_art import make_card
from .editorial_motion import CUTAWAYS, treatment
from .reference_cadence import digest, video_clock
from .video_anchor import Prepared, frames_of, load, prepare, render, screen_quad, shot_starts


NUMBERS = {'um':'1','uma':'1','dois':'2','duas':'2','tres':'3','quatro':'4','cinco':'5',
           'seis':'6','sete':'7','oito':'8','nove':'9','dez':'10','onze':'11','doze':'12',
           'treze':'13','quatorze':'14','catorze':'14','quinze':'15',
           'dezesseis':'16','dezessete':'17','dezoito':'18','dezenove':'19','vinte':'20'}
QUANTITY = r'(?P<number>\d+|' + '|'.join(NUMBERS) + ')'


RULES = (
    (r'(?:pararam de autorizar|suspendeu as) decolagens', 'DECOLAGENS SUSPENSAS', 'no ar', 'plane'),
    (r'falha nos sistemas de comunicacao|falha de comunicacao', 'FALHA DE COMUNICAÇÃO', 'controle aéreo', 'signal'),
    (r'\b(?P<approx>cerca de )?'+ QUANTITY + r' horas?\b', '{approx}{number} {unit}', 'tempo', 'clock'),
    (r'\b'+ QUANTITY + r' (?:voos )?(?:foram )?cancelados\b', '{number} CANCELADOS', '', 'cancel'),
    (r'\b'+ QUANTITY + r' (?:voos )?sofreram atrasos\b', '{number} COM ATRASO', '', 'clock'),
    (r'\b'+ QUANTITY + r' voos programados\b', '{number} VOOS PROGRAMADOS', '', 'plane'),
    (r'\bchegou ate o brasil\b', 'IMPACTO NO BRASIL', 'efeito em cadeia', 'pin'),
    (r'\b(?:operacoes )?foram retomadas\b', 'OPERAÇÕES RETOMADAS', 'de volta', 'check'),
    (r'\bstatus do seu voo\b', 'CONFIRA O STATUS', 'antes de sair', 'status'),
    (r'\btomorrow travel\b', 'TOMORROW TRAVEL', 'siga a', None),
    (r'\baconteceu de verdade\b', 'ACONTECEU DE VERDADE', 'parece filme', None),
    (r'\bmalas prontas\b', 'MALAS PRONTAS', 'no aeroporto', 'plane'),
)


def tokens(text):
    plain = unicodedata.normalize('NFKD', text.casefold())
    return re.findall(r'[a-z0-9]+', ''.join(c for c in plain if not unicodedata.combining(c)))


def transcript_words(transcript):
    segments = transcript['segments'] if isinstance(transcript, dict) else transcript
    for part in segments:
        phrases = part.get('words') or [{'start': part['start'], 'end': part['end'], 'word': part['text']}]
        for phrase in phrases:
            a, b = float(phrase['start']), float(phrase['end'])
            if not (0 <= a <= b < float('inf')):
                raise ValueError('Invalid transcription clock')
            for token in tokens(phrase['word']):
                yield token, a, b


def speech_cues(transcript, reviewed=None):
    words = list(transcript_words(transcript))
    if not words:
        return []
    speech = ' '.join(w[0] for w in words)
    offsets = np.cumsum([0] + [len(w[0])+1 for w in words])
    choices = []
    if reviewed is None:
        candidates = [(re.search(pattern, speech), title, cap, icon, {}) for pattern,title,cap,icon in RULES]
    else:
        candidates = []
        for cue in reviewed:
            evidence = ' '.join(tokens(cue['evidence']))
            matches = list(re.finditer(r'\b' + re.escape(evidence) + r'\b', speech))
            if not evidence or not matches:
                raise ValueError(f"No supporting speech for {cue['title']}")
            match = min(matches, key=lambda m: abs(words[np.searchsorted(offsets,m.start(),side='right')-1][1]
                                                     - cue.get('near', 0)))
            if cue.get('icon'):
                allowed = any(icon == cue['icon'] and re.search(rule, evidence) for rule,_,_,icon in RULES)
                if not allowed:
                    raise ValueError('Known icons need matching speech, or use custom art with provenance')
            if cue.get('icon_asset') and not cue.get('provenance'):
                raise ValueError('Custom art requires a provenance file')
            if cue.get('icon') and cue.get('icon_asset'):
                raise ValueError('Choose one icon source for the cue')
            candidates.append((match, cue['title'], cue.get('script',''), cue.get('icon'), cue))
    for match,title,cap,icon,extra in candidates:
        if match is None:
            continue
        if reviewed is None and match.groupdict().get('number'):
            groups = match.groupdict()
            number = NUMBERS.get(groups['number'], groups['number'])
            title = title.format(number=number, approx='CERCA DE ' if groups.get('approx') else '',
                                 unit='HORA' if number=='1' else 'HORAS')
        left = np.searchsorted(offsets,match.start(),side='right')-1
        right = np.searchsorted(offsets,match.end()-1,side='right')-1
        choices.append({
            'title':title, 'script':cap, 'icon':icon, 'evidence':match.group(),
            'start':words[left][1], 'spoken_end':words[right][2],
            'treatment': 'metric' if re.search(r'\d', title) else
                         'alert' if icon in {'signal','cancel'} else 'headline',
            **{k: extra[k] for k in ('icon_asset','provenance','anchor','spatial_evidence',
                                      'editorial','body_effect') if k in extra},
        })
    return sorted(choices, key=lambda x:x['start'])


def point(person, name, cutoff=.48):
    xyz = person.get('landmarks', {}).get(name)
    if xyz is not None and len(xyz)==4 and np.isfinite(xyz).all() and xyz[3]>=cutoff and all(0 <= x <= 1 for x in xyz[:2]):
        return np.asarray(xyz[:2])
    return None


def box(points, pad):
    points = [p for p in points if p is not None]
    if not points:
        return None
    return np.clip([*(np.min(points,axis=0)-pad), *(np.max(points,axis=0)+pad)],0,1).tolist()


def inspect_pose(pose, count, cuts, fps):
    if pose['fps'] != fps or len(pose['frames']) != count:
        raise ValueError('Tracking must cover the very same frame clock as the source')
    excluded, gestures, shots = {}, [], []
    for first,last in zip(cuts,[*cuts[1:],count]):
        hands = {'left':{},'right':{}}
        identities = Counter(p.get('id', 0) for i in range(first,last)
                             for p in pose['frames'].get(str(i), []))
        primary_id = identities.most_common(1)[0][0] if identities else None
        tracked = feet = hands_seen = 0
        for frame in range(first,last):
            people = pose['frames'].get(str(frame),[])
            if not people:
                excluded[frame]=None
                continue
            parts=[]
            faces=0
            raw_hands=pose.get('hands',{}).get(str(frame),[])
            for raw_hand in raw_hands:
                hand_box=box([point(raw_hand,k) for k in raw_hand['landmarks']], np.array([.060,.038]))
                if hand_box is not None:
                    parts.append(hand_box)
            for person in people:
                eyes=[point(person,s) for s in ('nose','left_eye','right_eye','left_ear','right_ear','mouth_left','mouth_right')]
                shoulders=[point(person,s+'_shoulder') for s in ('left','right')]
                shoulder_width=abs(shoulders[0][0]-shoulders[1][0]) if all(p is not None for p in shoulders) else .40
                face=box(eyes, np.array([max(.045, .18*shoulder_width), max(.045,.15*shoulder_width)]))
                if face is not None:
                    parts.append(face)
                    faces+=1
                seen=False
                for side in hands:
                    fingers=[point(person,f'{side}_{name}') for name in
                             ('hand_wrist','wrist','palm','thumb_tip','index_tip','middle_tip','pinky_tip')]
                    hand_box=box(fingers, np.array([.075,.050]))
                    if hand_box is not None:
                        parts.append(hand_box)
                        seen=True
                    if person.get('id',0)==primary_id and fingers[0] is not None and all(p is not None for p in shoulders):
                        hands[side][frame]=fingers[0]-np.mean(shoulders,axis=0)
                if person.get('id',0)==primary_id:
                    if len(people)==1 and all(p is not None for p in shoulders):
                        origin=np.mean(shoulders,axis=0)
                        for raw_hand in raw_hands:
                            side=raw_hand['side']
                            wrist=point(raw_hand,'hand_wrist')
                            if side in hands and wrist is not None and frame not in hands[side]:
                                hands[side][frame]=wrist-origin
                    tracked+=int(face is not None)
                    hands_seen+=int(seen or bool(raw_hands))
                    feet+=int(all(point(person,side+'_ankle',.65) is not None and
                                  point(person,side+'_heel',.65) is not None for side in hands))
            excluded[frame]=parts if faces==len(people) else None
        lookback=max(1,round(.16*fps))
        for side, samples in hands.items():
            last_hit=first-fps
            for frame, xyz in samples.items():
                earlier=frame-lookback
                if earlier not in samples or any(k not in samples for k in range(earlier,frame+1)):
                    continue
                delta=(xyz-samples[earlier])*fps/lookback
                speed=float(np.linalg.norm(delta))
                if speed>.54 and frame-last_hit>=.42*fps:
                    gestures.append({'frame':frame,'side':side,'speed':round(speed,3)})
                    last_hit=frame
        shots.append({'frames':[first,last], 'pose_frames':tracked, 'hands_visible_frames':hands_seen,
                      'feet_visible_frames':feet, 'framing':'feet_visible' if feet>=.72*(last-first) else 'close_or_partial',
                      'subject':'original_plate', 'contact':'unverified', 'camera':'source_plate'})
    return excluded, sorted(gestures,key=lambda x:x['frame']), shots


def overlap(quad, rectangle):
    # An envelope over a whole shape is conservative for slanted graphic quads.
    l,t=quad.min(axis=0)
    r,b=quad.max(axis=0)
    x,y,z,w=rectangle
    return l<z and r>x and t<w and b>y


def spoken_windows(cues, count, fps):
    scheduled=[]
    for cue in cues:
        frame=round(cue['start']*fps)
        if frame>=count:
            continue
        if scheduled and frame-scheduled[-1]['spoken_frame']<.80*fps:
            continue
        scheduled.append(dict(cue,spoken_frame=frame))
    for i,cue in enumerate(scheduled):
        stop=scheduled[i+1]['spoken_frame'] if i<len(scheduled)-1 else count
        duration=min(3.8,max(1.65,cue['spoken_end']-cue['start']+.82))
        cue['end_frame']=min(stop,count,cue['spoken_frame']+round(duration*fps))
    return scheduled


def place_screen(first, stop, protected, resolution):
    frames=list(range(first,stop))
    width,height=resolution
    w,h=(.87,.87*width*(210/900)/height)
    # Also reserve the pop's largest possible extent.
    for factor in (1., .86, .72):
        size = (w*factor, h*factor)
        for y in (.16,.105,.23,.77,.86,.30):
            corners=screen_quad((.50,y),size)
            envelope=screen_quad((.50,y),np.asarray(size)*1.09)
            visible=[i for i in frames if protected.get(i) is not None
                     and not any(overlap(envelope, r) for r in protected[i])]
            if len(visible)>=.93*len(frames):
                return {k:corners for k in visible}, tuple(max(4,round(a*b)) for a,b in zip(size,resolution))
    return {}, (8,8)


def build_layers(source, transcript, pose, style, root, condensed, script, reviewed=None, mattes=None):
    rate,count=video_clock(source)
    checksum=digest(source)
    if pose.get('source_sha256') != checksum:
        raise ValueError('Pose sidecar must be measured on this source file')
    if rate.denominator != 1:
        raise ValueError('Conform fractional FPS to an integer clock before tracking and rendering')
    fps=int(rate)
    if mattes:
        alpha_index=load(mattes/'alpha.json')
        if (alpha_index['source_sha256']!=checksum or int(alpha_index['frames'])!=count or
                Fraction(alpha_index['fps'])!=rate):
            raise ValueError('Matting must be measured on this source and frame clock')
    if style['animation'] not in {'fade','pop','hold'}:
        raise ValueError('Adaptive layouts support fade, pop and hold animation')
    picture=next(frames_of(source),None)
    if picture is None:
        raise ValueError('Source failed to decode')
    resolution=picture.shape[1::-1]
    frames=list(frames_of(source,analysis=True))
    if len(frames)!=count:
        raise ValueError('Source clock differs from decoded frames')
    cuts=sorted({0,*(c for c in pose.get('shots',[]) if 0<c<count),*shot_starts(frames)})
    protected, gestures, shots=inspect_pose(pose,count,cuts,fps)
    planned=[]
    layers=[]
    occupied=defaultdict(list)
    depth_effects=[]
    depth_candidates=[]
    used_orbit=False
    for index,cue in enumerate(spoken_windows(speech_cues(transcript,reviewed),count,fps)):
        first,end=cue['spoken_frame'],cue['end_frame']
        # A gesture can accent a phrase after it starts, within 320 milliseconds.
        events=[g for g in gestures if first<=g['frame']<=first+round(.32*fps)
                and not any(first<c<=g['frame'] for c in cuts)]
        gesture=max(events,key=lambda e:e['speed']) if events else None
        if gesture and end-gesture['frame']>=.9*fps:
            first=gesture['frame']
        else:
            gesture=None
        key=f'cue-{index+1:02d}'
        asset=f'{key}.png'
        visual = treatment(dict(cue, gesture=gesture)) if style.get('editorial_motion') and not cue.get('anchor') else None
        if cue.get('icon_asset'):
            provenance = load(root/cue['provenance'])
            evidence = ' '.join(tokens(provenance.get('evidence','')))
            if evidence != cue['evidence'] or not provenance.get('concept','').strip():
                raise ValueError('Custom icon provenance must identify its concept and supporting speech')
        # Preserve externally prepared artwork or spatial anchors through the legacy overlay path.
        if not visual or cue.get('icon_asset'):
            visual = None
            make_card(cue,style,condensed,script,root).save(root/asset)
        if visual in CUTAWAYS:
            end = min(end, first+round(2.35*fps))
        anchor=cue.get('anchor') or {'mode':'screen'}
        effect={'id':key,'asset':asset,'frames':[first,end],'animation':style['animation'],
                'entrance_seconds':style['entrance_seconds'],'anchor':anchor}
        marks=[first,*(c for c in cuts if first<c<end),end]
        details=dict(cue,output_frames=[first,end],gesture=gesture,rendered_frames=0,
                     asset=asset,anchor_mode=anchor['mode'],placements=[])
        if visual:
            effect.pop('asset')
            effect['editorial_scene'] = {
                'kind': visual, 'cue': cue, 'style': style,
                'condensed': str(condensed.resolve()), 'script': str(script.resolve()),
            }
            details['asset'] = None
            details['visual_treatment'] = visual
        orbit=None
        orbit_cue=(cue.get('body_effect')=='orbit' or
                  any(word in cue['evidence'].split() for word in ('decolagens','retomadas')))
        if (mattes and style.get('body_depth') and not used_orbit and visual=='kinetic_type'
                and orbit_cue
                and len(marks)==2):
            track=orbit_track(pose,protected,first,end,mattes)
            title={'DECOLAGENS SUSPENSAS':'VOOS SUSPENSOS'}.get(cue['title'],cue['title'])
            evidence=verify_orbit(track,resolution,mattes,title,str(condensed),tuple(style['ink']),fps)
            depth_candidates.append({'kind':'orbit','frames':[first,end],
                                     'status':'selected' if evidence else 'insufficient_visible_depth'})
            if evidence:
                orbit={ 'kind':'orbit', 'title':title, 'font':str(condensed.resolve()),
                        'mattes':str(mattes.resolve()),'ink':style['ink'] }
                depth_effects.append({'kind':'orbit','frames':[first,end],'evidence':evidence})
                used_orbit=True
        if orbit:
            layers.append(Prepared({'id':key,'body_depth':orbit},first,end,track,{}, {'mode':'body_orbit'},
                                   resolution,{},None))
            details.update(visual_treatment='body_orbit',anchor_mode='tracked_shoulders',rendered_frames=len(track))
        elif visual in CUTAWAYS:
            corners = {i: None for i in range(first,end)}
            layers.append(Prepared(effect,first,end,corners,{}, {'mode':'cutaway'},resolution,{},None))
            details['rendered_frames'] = len(corners)
            details['anchor_mode'] = 'cutaway'
        elif anchor['mode']=='screen':
            for a,b in zip(marks,marks[1:]):
                corners,size=place_screen(a,b,protected,resolution)
                if corners:
                    layers.append(Prepared(effect,a,b,corners,{}, {'mode':'screen'},size,{},None))
                    details['rendered_frames']+=len(corners)
                    details['placements'].append({'interval':[a,b],
                                                 'quad':next(iter(corners.values())).tolist()})
        elif anchor['mode'] in {'planar','world'} and cue.get('spatial_evidence'):
            layer=prepare(effect,frames,cuts,fps,resolution,root,occupied)
            speed=max(1,round(style['entrance_seconds']*fps))
            safe={}
            for i,q in layer.corners.items():
                animated,_=motion(q,(i-first+1)/speed,style['animation'])
                if protected.get(i) is not None and not any(overlap(animated,r) for r in protected[i]):
                    safe[i]=q
            layer.corners=safe
            details['rendered_frames']=len(layer.corners)
            if layer.corners:
                layers.append(layer)
        else:
            raise ValueError('A spatial layout requires measured planar or world anchor evidence')
        details['status']='renderable' if details['rendered_frames'] else 'no_safe_placement'
        planned.append(details)
        if gesture and mattes and style.get('body_depth') and not cue.get('anchor'):
            shot_start=max(c for c in cuts if c<=gesture['frame'])
            shot_stop=min((c for c in cuts if c>gesture['frame']),default=count)
            hand=hand_track(pose,protected,gesture['side'],
                            max(shot_start,cue['spoken_frame']-round(.40*fps)),
                            min(shot_stop,gesture['frame']+round(.44*fps)+1))
            valid=len(hand)>=round(.20*fps) and all(read_alpha(mattes,i) is not None for i in hand)
            depth_candidates.append({'kind':'hand_track','trigger_frame':gesture['frame'],
                                     'status':'selected' if valid else 'insufficient_hand_track'})
            if valid:
                a,b=min(hand),max(hand)+1
                art={'kind':'hand_track','ink':style['ink'],'mattes':str(mattes.resolve())}
                layers.append(Prepared({'id':key+'-hand','body_depth':art},a,b,hand,{}, {'mode':'hand_track'},
                                       resolution,{},None))
                depth_effects.append({'kind':'hand_track','frames':[a,b],'tracked_frames':len(hand),
                                      'side':gesture['side'],'trigger_frame':gesture['frame']})
    report={'schema':'adaptive-template/1','source_sha256':checksum,'fps':fps,'frames':count,
            'style':style['id'],'shots':shots,'gesture_candidates':gestures,'graphics':planned,
            'depth_effects':depth_effects,'depth_candidates':depth_candidates,
            'limits':'Geometry measured from source landmarks. Spatial depth requires an independent anchor solve.'}
    return report,layers,resolution


def transcribe(source, model):
    from faster_whisper import WhisperModel
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(source),'-map','0:a:0',
                                 '-ac','1','-ar','16000','-f','f32le','-'])
    decoder=WhisperModel(str(model),device='cpu',compute_type='int8',local_files_only=True,cpu_threads=4)
    segments,_=decoder.transcribe(np.frombuffer(raw,'<f4'),word_timestamps=True)
    return [{'start':s.start,'end':s.end,'text':s.text.strip(),
             'words':[{'start':w.start,'end':w.end,'word':w.word} for w in s.words]} for s in segments]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('style',type=Path)
    parser.add_argument('work',type=Path)
    transcript=parser.add_mutually_exclusive_group(required=True)
    transcript.add_argument('--transcript',type=Path)
    transcript.add_argument('--asr-model',type=Path)
    tracking=parser.add_mutually_exclusive_group(required=True)
    tracking.add_argument('--pose',type=Path)
    tracking.add_argument('--pose-model',type=Path)
    parser.add_argument('--hand-model',type=Path)
    alpha=parser.add_mutually_exclusive_group()
    alpha.add_argument('--mattes',type=Path)
    alpha.add_argument('--matte-model',type=Path,help='RVM MobileNetV3 FP32 ONNX checkpoint')
    parser.add_argument('--persons', type=int, choices=range(1,9), default=2)
    parser.add_argument('--cues',type=Path)
    parser.add_argument('--condensed',type=Path,required=True)
    parser.add_argument('--script',type=Path,required=True)
    parser.add_argument('--render',type=Path)
    args=parser.parse_args()
    if args.render and args.render.resolve()==args.source.resolve():
        parser.error('Choose a new file for the render')
    args.work.mkdir(exist_ok=True,parents=True)
    words=load(args.transcript) if args.transcript else transcribe(args.source,args.asr_model)
    if args.pose:
        pose=load(args.pose)
    else:
        from .body_pose import analyze
        rate,_=video_clock(args.source)
        if rate.denominator != 1:
            parser.error('Conform fractional FPS before body tracking')
        pose=analyze(args.source,args.work/'pose.json',args.pose_model,args.hand_model,
                     fps=int(rate),persons=args.persons)
    reviewed=load(args.cues) if args.cues else None
    if reviewed:
        for cue in reviewed:
            for field in ('icon_asset','provenance'):
                if cue.get(field):
                    cue[field]=str((args.cues.parent/cue[field]).resolve())
            if cue.get('anchor'):
                for field in ('projection','tracks','cameras'):
                    if cue['anchor'].get(field):
                        cue['anchor'][field]=str((args.cues.parent/cue['anchor'][field]).resolve())
    mattes=args.mattes
    if args.matte_model:
        from .subject_alpha import prepare_alpha
        mattes=args.work/'alpha'
        prepare_alpha(args.source,args.matte_model,mattes)
    report,layers,resolution=build_layers(args.source,words,pose,load(args.style),args.work,
                                          args.condensed,args.script,reviewed,mattes)
    (args.work/'analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if args.render:
        if not layers:
            parser.error('No evidence-backed graphics with safe placement; inspect analysis.json')
        args.render.parent.mkdir(parents=True,exist_ok=True)
        render(args.source,args.render,resolution,report['fps'],layers,None,args.work)


if __name__=='__main__':
    main()
