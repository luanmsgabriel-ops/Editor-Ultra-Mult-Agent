"""Landmark-driven body anchors, gesture cues and projected text orbits."""
from dataclasses import dataclass
import math

import cv2
import numpy as np

from .anchor_graphics import composite, load_face, make_art, graphemes

GROUPS={
    'head':('left_eye','right_eye','nose'),
    'shoulders':('left_shoulder','right_shoulder'),
    'hips':('left_hip','right_hip'),
    'body_center':('left_shoulder','right_shoulder','left_hip','right_hip'),
    'left_palm':('left_hand_wrist','left_index_mcp','left_middle_mcp','left_pinky_mcp','left_wrist'),
    'right_palm':('right_hand_wrist','right_index_mcp','right_middle_mcp','right_pinky_mcp','right_wrist'),
}
RELATIONS={
    'center':(0.,0.),'above':(0.,-1.),'below':(0.,1.),'left':(-1.,0.),'right':(1.,0.),
}


@dataclass
class BodyFrame:
    point: np.ndarray
    shoulders: np.ndarray
    hips: np.ndarray
    head: np.ndarray | None
    gestures: dict
    person_id: int


def locate(person, name, confidence):
    available=person.get('landmarks',{})
    values=[]
    for key in GROUPS.get(name,(name,)):
        point=available.get(key)
        if point is None or len(point)<4 or not np.isfinite(point[:4]).all():
            continue
        if point[3]>=confidence and -.15<=point[0]<=1.15 and -.15<=point[1]<=1.15:
            values.append(point)
    if len(values)<2 and name in {'shoulders','hips','body_center'}:
        return None
    return np.mean(values,axis=0)[:3] if values else None


def candidate(person,name,confidence):
    point=locate(person,name,confidence)
    shoulders=locate(person,'shoulders',confidence)
    hips=locate(person,'hips',confidence)
    if point is None:
        return None
    left,right=[locate(person,side+'_shoulder',confidence) for side in ('left','right')]
    if left is None or right is None:
        shoulder_size=np.array([.17,0.,0.])
    else:
        shoulder_size=left-right
    return BodyFrame(point,shoulder_size,hips-shoulders if hips is not None and shoulders is not None
                     else np.array([0.,.17,0.]),locate(person,'head',confidence),
                     person.get('gestures',{}),int(person['id']))


def interpolate(left,right,t):
    def blend(a,b):
        return a*(1-t)+b*t
    head=blend(left.head,right.head) if left.head is not None and right.head is not None else None
    return BodyFrame(blend(left.point,right.point),blend(left.shoulders,right.shoulders),
                     blend(left.hips,right.hips),head,{},left.person_id)


def smooth(samples,fps):
    output={}
    previous=None
    last=None
    for frame,sample in sorted(samples.items()):
        if previous is None or frame!=last+1:
            filtered=sample
        else:
            speed=np.linalg.norm(sample.point[:2]-previous.point[:2])*fps
            gain=float(np.clip(.34+speed*.67,.34,1))
            filtered=interpolate(previous,sample,gain)
            filtered.gestures=sample.gestures
        output[frame]=filtered
        previous=filtered
        last=frame
    return output


def detect_event(samples,trigger,fps):
    gesture=trigger.get('gesture')
    motion=trigger.get('motion')
    if bool(gesture)==bool(motion):
        raise ValueError('trigger precisa de exatamente um gesto ou um movimento.')
    directions={'rise':(0,-1),'fall':(0,1),'left':(-1,0),'right':(1,0)}
    if motion and motion not in {'rise','fall','left','right','move'}:
        raise ValueError('Use rise, fall, left, right ou move.')
    side=trigger.get('side','any')
    if side not in {'any','left','right'}:
        raise ValueError('Lado do gesto inválido.')
    required=max(1,int(trigger.get('min_frames',2)))
    lookback=max(1,round(fps*.13))
    minimum=float(trigger.get('min_speed',.3))
    last=None
    hits=0
    for index,item in sorted(samples.items()):
        if gesture:
            matched=[value for key,value in item.gestures.items() if side=='any' or key==side]
            present=any((v.get('name') if isinstance(v,dict) else v)==gesture for v in matched)
        else:
            previous=samples.get(index-lookback)
            if previous is None or any(i not in samples for i in range(index-lookback,index+1)):
                present=False
            else:
                step=(item.point-previous.point)[:2]*fps/lookback
                speed=np.linalg.norm(step) if motion=='move' else np.dot(step,directions[motion])
                present=speed>=minimum
        hits=hits+1 if present and last is not None and index==last+1 else int(present)
        if hits>=required:
            return index-required+1
        last=index
    return None


def track_sidecar(data, first, last, cuts, fps, spec):
    if data.get('fps')!=fps:
        raise ValueError('O FPS do rastreamento corporal precisa ser igual ao FPS do render.')
    pose=data['frames']
    confidence=float(spec.get('confidence',.5))
    if not 0<=confidence<=1:
        raise ValueError('confidence deve estar entre 0 e 1.')
    name=spec.get('landmark','body_center')
    person=spec.get('person','auto')
    if person!='auto' and type(person)!=int:
        raise ValueError('person precisa ser um ID inteiro ou auto.')
    gap=int(spec.get('max_gap',3))
    if not 0<=gap<=12:
        raise ValueError('max_gap precisa estar entre 0 e 12.')
    start_points=[first]+[f for f in cuts if first<f<last]+[last]
    tracks={}
    events=[]
    for start,stop in zip(start_points,start_points[1:]):
        per_person={}
        for idx in range(start,stop):
            for subject in pose.get(str(idx),[]):
                item=candidate(subject,name,confidence)
                if item and (person=='auto' or item.person_id==person):
                    per_person.setdefault(item.person_id,{})[idx]=item
        if not per_person:
            continue
        # Fix the identity for the entire shot using visible support.
        trigger=spec.get('trigger')
        viable=[]
        for key,available in per_person.items():
            event=detect_event(available,trigger,fps) if trigger else start
            if event is not None:
                viable.append((len(available),-event,-key,available,event))
        if not viable:
            continue
        _,_,_,raw,event=max(viable,key=lambda item:item[:3])
        if trigger:
            events.append(event)
        visible=[index for index in sorted(raw) if index>=event]
        aligned={index:raw[index] for index in visible}
        for a,b in zip(visible,visible[1:]):
            if 1<b-a<=gap+1:
                fill={i:interpolate(raw[a],raw[b],(i-a)/(b-a)) for i in range(a+1,b)}
                aligned.update(fill)
        aligned=smooth(aligned,fps)
        if spec.get('follow',True) is False and aligned:
            frozen=aligned[min(aligned)]
            aligned={i:frozen for i in range(min(aligned),stop)}
        tracks.update(aligned)
    return tracks,events


def relative_geometry(shot,resolution):
    w,h=resolution
    scale=np.array([w,h])
    shoulder=np.clip(np.linalg.norm(shot.shoulders[:2]*scale),w*.10,w*.60)
    torso=np.clip(np.linalg.norm(shot.hips[:2]*scale),h*.10,h*.49)
    return shot.point[:2]*scale,shoulder,torso


def follow_quad(shot,resolution,size,spec):
    resolution=np.asarray(resolution)
    center,shoulder,torso=relative_geometry(shot,resolution)
    box=np.asarray(size)*resolution
    if spec.get('scale_with_body',False):
        box*=np.clip(shoulder/(resolution[0]*.26),.58,1.5)
    relation=spec.get('relation','above')
    if relation not in RELATIONS:
        raise ValueError('Use center, above, below, left ou right.')
    direction=np.array(RELATIONS[relation])
    gap=float(spec.get('gap',.12))*shoulder
    center=center+direction*(box*.5+gap)
    center=np.clip(center,box*.5+8,resolution-box*.5-8)
    if shot.head is not None:
        head=shot.head[:2]*resolution
        bound=np.array([shoulder*.42,shoulder*.44])+box*.5
        if np.all(np.abs(head-center)<bound):
            options=[head+[d*(bound[0]+gap),0] for d in (-1,1)]
            possible=[mark for mark in options if np.all(mark>=box*.5+8)
                      and np.all(mark<=resolution-box*.5-8)]
            if possible:
                center=min(possible,key=lambda aim:np.linalg.norm(aim-center))
            else:
                return None
    return box_quad(center,box,0)/resolution


def box_quad(center,size,angle):
    w,h=np.asarray(size)/2
    local=np.array([[-w,-h],[w,-h],[w,h],[-w,h]])
    co,si=np.cos(angle),np.sin(angle)
    return local@np.array([[co,si],[-si,co]])+center


def orbit_geometry(shot,resolution,spec):
    w,h=resolution
    point,shoulder,torso=relative_geometry(shot,resolution)
    rx=np.clip(shoulder*float(spec.get('radius',1.30)),w*.13,w*.43)
    ry=np.clip(torso*float(spec.get('tilt',.25)),h*.035,h*.18)
    point[1]+=float(spec.get('offset',.10))*torso
    return point,rx,ry


def orbit_items(shot,resolution,spec,positions,aspect,seconds):
    center,rx,ry=orbit_geometry(shot,resolution,spec)
    turn=float(spec.get('turn_seconds',5.2))
    if not .35<=turn<=120:
        raise ValueError('turn_seconds precisa estar de 0,35 a 120.')
    phase=math.radians(float(spec.get('phase',145)))+seconds*2*math.pi/turn
    span=math.radians(float(spec.get('span',300)))
    height=resolution[1]*float(spec.get('letter_height',.038))
    output=[]
    for index,(position,ratio) in enumerate(zip(positions,aspect)):
        theta=phase-position*span
        far=np.sin(theta)<0
        factor=1+.22*np.sin(theta)
        pos=center+[rx*np.cos(theta),ry*np.sin(theta)]
        tilt=math.atan2(-ry*np.cos(theta),rx*np.sin(theta))
        tilt=(tilt+math.pi/2)%math.pi-math.pi/2
        if not spec.get('tangent',True):
            tilt=0
        tilt=float(np.clip(tilt,-.91,.91))
        glyph_h=height*factor
        glyph_w=glyph_h*ratio*(.55+.45*abs(np.sin(theta)))
        output.append((far,index,box_quad(pos,[glyph_w,glyph_h],tilt)/resolution))
    return output


def build_orbit_art(effect,spec,font_path,color,root):
    layout=spec.get('layout','ribbon')
    if layout not in {'ribbon','label'}:
        raise ValueError('layout orbital precisa ser ribbon ou label.')
    if 'asset' in effect or layout=='label':
        dimensions=(384,288) if 'asset' in effect else (480,128)
        art=make_art(effect,dimensions,font_path,color,root)
        return [art],[0.],[dimensions[0]/dimensions[1]]
    letters=graphemes(effect['text'])
    font=load_face(str(font_path),float(effect.get('weight',800)))
    total=max(1,font.getlength(effect['text']))
    all_arts,positions,ratios=[],[],[]
    prefix=''
    for letter in letters:
        prefix+=letter
        if letter.isspace():
            continue
        words_width=max(12,round(font.getlength(letter)*1.18))
        all_arts.append(make_art({**effect,'text':letter,'arc':0},(words_width,200),font_path,color,root))
        positions.append((font.getlength(prefix)-font.getlength(letter)*.5)/total)
        ratios.append(words_width/200)
    return all_arts,positions,ratios


def render_orbit(frame,shot,spec,letters,seconds,color,mask,opacity):
    resolution=frame.shape[1::-1]
    arts,positions,aspects=letters
    items=orbit_items(shot,resolution,spec,positions,aspects,seconds)
    center,rx,ry=orbit_geometry(shot,resolution,spec)
    for far in (True,False):
        if far and mask is None:
            continue
        if spec.get('ring',True):
            angle=np.linspace(math.pi,2*math.pi,180) if far else np.linspace(0,math.pi,180)
            path=np.rint(center+np.column_stack((rx*np.cos(angle),ry*np.sin(angle)))).astype('int32')
            matte=np.zeros(frame.shape[:2],'uint8')
            cv2.polylines(matte,[path],False,255,max(1,round(resolution[0]/660)),cv2.LINE_AA)
            level=opacity*(.28 if far else .55)
            if far:
                matte=cv2.multiply(matte,255-mask,scale=1/255)
            ys,xs=np.nonzero(matte)
            blend=matte[ys,xs,None]*(level/255)
            frame[ys,xs]=(frame[ys,xs]*(1-blend)+np.asarray(color[::-1])*blend).astype('uint8')
        for behind,index,quad in items:
            if behind==far:
                composite(frame,arts[index],quad,opacity*(.68 if far else 1.),mask if far else None)
