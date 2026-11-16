"""Source-aware orbital typography and gesture graphics with separate depth passes."""

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .orbit_type import OrbitSpec, render_orbit_type


def read_alpha(directory, frame):
    return cv2.imread(str(Path(directory)/f'{frame:06d}.png'), cv2.IMREAD_GRAYSCALE)


def landmarks(person, names, threshold=.48):
    values = [person['landmarks'].get(name) for name in names]
    return [np.asarray(pt[:2],float) for pt in values
            if pt and len(pt)==4 and np.isfinite(pt).all() and pt[3]>=threshold
            and all(0<=v<=1 for v in pt[:2])]


def orbit_track(pose, protected, start, stop, directory):
    track = {}
    previous = None
    for index in range(start,stop):
        people = pose['frames'].get(str(index),[])
        if len(people)!=1 or not protected.get(index):
            continue
        shoulders = landmarks(people[0], ('left_shoulder','right_shoulder'))
        if len(shoulders)!=2:
            continue
        width=abs(shoulders[0][0]-shoulders[1][0])
        if width<.24:
            continue
        x,y=np.mean(shoulders,axis=0)
        # The rear arc needs exposed background at shoulder level. The front
        # arc is lowered under the verified bottom edge of the face.
        face_bottom=protected[index][0][3] if len(protected[index])==1 else None
        face=landmarks(people[0], ('mouth_left','mouth_right','nose'))
        if not face:
            continue
        minimum=max(p[1] for p in face)+.095
        y=max(minimum,min(.86,y-.015))
        if face_bottom is not None:
            y=max(y,face_bottom+.024)
        radius=min(.43,.53*width)
        x=float(np.clip(x,radius+.025,.975-radius))
        alpha=read_alpha(directory,index)
        if alpha is None:
            continue
        h,w=alpha.shape
        row=alpha[max(0,round((y-.07)*h)):max(1,round((y-.018)*h))]
        visible_background=np.mean(row<95)
        inside=np.mean(alpha[round(y*h),max(0,int((x-.10)*w)):min(w,int((x+.10)*w))]>175)
        if visible_background<.05 or inside<.55:
            continue
        current=np.asarray([x,y,radius])
        if previous is not None and index-1 in track:
            current=previous*.62+current*.38
        previous=current
        track[index]=(current,protected[index])
    # Require a contiguous track for an effect that must visibly orbit.
    return track if len(track)==stop-start else {}


def hand_track(pose, protected, side, start, stop):
    """Use independently detected palm landmarks and stop at tracking loss."""
    raw={}
    for i in range(start,stop):
        hands=[hand for hand in pose.get('hands',{}).get(str(i),[]) if hand['side']==side]
        people=pose.get('frames',{}).get(str(i),[])
        if len(hands)!=1 or len(people)!=1 or not protected.get(i):
            continue
        points=landmarks(hands[0],('hand_wrist','index_mcp','middle_mcp','ring_mcp','pinky_mcp'))
        face=landmarks(people[0],('nose','left_eye','right_eye','mouth_left','mouth_right'))
        if len(points)<3 or len(face)<3:
            continue
        center=np.mean(points,axis=0)
        radius=max(.071,min(.137,float(np.ptp(points,axis=0)[0])*.85))
        if not (.035<center[0]<.965 and .07<center[1]<.93):
            continue
        if abs(center[0]-np.mean(face,axis=0)[0])<radius+.13 and abs(center[1]-np.mean(face,axis=0)[1])<.12:
            continue
        raw[i]=np.asarray([*center,radius])
    # Prefer a real contiguous hand movement over disconnected landmarks.
    groups=[]
    for i in raw:
        if not groups or i!=groups[-1][-1]+1:
            groups.append([])
        groups[-1].append(i)
    group=max(groups,key=len,default=[])
    output={}
    for i in group:
        output[i]=.50*output[i-1]+.50*raw[i] if i-1 in output else raw[i]
    return output


def protect_front(alpha, boxes):
    height,width=alpha.shape
    for l,t,r,b in boxes:
        alpha[int(t*height):math.ceil(b*height),int(l*width):math.ceil(r*width)]=0
    return alpha


def alpha_over(canvas, layer, opacity=1.):
    rgb=layer[:,:,:3][:,:,::-1]
    coverage=layer[:,:,3].astype(np.float32)[:,:,None]*(opacity/255)
    canvas[:]=np.rint(canvas*(1-coverage)+rgb*coverage).astype(np.uint8)


def orbit_passes(size, geo, mask, text, font, ink, elapsed):
    width,height=size
    (x,y,radius), boxes=geo
    spec=OrbitSpec(size=size,center=(x*width,(y-.065)*height),
                   radius_x=radius*width,radius_z=.35*width,camera_distance=1.85*width,
                   tilt_deg=-9,pitch_deg=30,phase=.16+elapsed*2.65,
                   font_size=max(20,round(.113*width)),gap=.12*width,repeats=2,
                   strip_width=9,thickness=2.5,color=ink,highlight_phase=.15+elapsed*.85)
    occluder=Image.fromarray(cv2.resize(mask,size,interpolation=cv2.INTER_LINEAR))
    rear,front=render_orbit_type(text,font,spec,occluder_alpha=occluder)
    rear,front=np.asarray(rear),np.array(front)
    protect_front(front[:,:,3],boxes)
    return rear,front


def verify_orbit(track, resolution, directory, title, font, ink, fps):
    """Accept an orbit only when its real passes show occlusion and visible rear text."""
    if not track:
        return []
    width,height=resolution
    size=(min(540,width),round(height*min(540,width)/width))
    start,stop=min(track),max(track)
    samples=[]
    for i in np.linspace(start,stop,5).astype(int):
        matte=read_alpha(directory,i)
        rear,front=orbit_passes(size,track[i],matte,title,font,ink,(i-start)/fps)
        unmasked,_=orbit_passes(size,track[i],np.zeros_like(matte),title,font,ink,(i-start)/fps)
        behind=np.count_nonzero(unmasked[:,:,3]>45)-np.count_nonzero(rear[:,:,3]>45)
        row={'frame':int(i),
             'rear_visible':int(np.count_nonzero(rear[:,:,3]>45)),
             'rear_occluded':int(behind),
             'front_visible':int(np.count_nonzero(front[:,:,3]>45))}
        samples.append(row)
    minimum=round(size[0]*size[1]*.0015)
    return samples if all(min(r['rear_visible'],r['rear_occluded'],r['front_visible'])>=minimum
                          for r in samples) else []


def composite_orbit_context(frame, layer, index, fps):
    effect=layer.effect['body_depth']
    width,height=frame.shape[1],frame.shape[0]
    size=(min(540,width),round(height*min(540,width)/width))
    matte=read_alpha(effect['mattes'],index)
    if matte is None:
        raise ValueError(f'Missing matte for orbital frame {index}')
    elapsed=(index-layer.first)/fps
    opacity=min(1.,(elapsed+.04)/.21,(layer.last-index)/max(1.,fps*.21))
    layers=orbit_passes(size,layer.corners[index],matte,effect['title'],effect['font'],effect['ink'],elapsed)
    for art in layers:
        # Resize in premultiplied space to preserve saturated antialiased letters.
        sample=art.astype(np.float32)/255
        sample[:,:,:3]*=sample[:,:,3,None]
        sample=cv2.resize(sample,(width,height),interpolation=cv2.INTER_LINEAR)
        alpha=sample[:,:,3,None]*opacity
        frame[:]=np.rint(frame*(1-alpha)+sample[:,:,:3][:,:,::-1]*opacity*255).clip(0,255).astype(np.uint8)


def draw_arc(mask, center, radii, angle, first, last, width):
    cv2.ellipse(mask,center,radii,angle,first,last,255,width,cv2.LINE_AA)


def hand_passes(size, mark, mask, elapsed):
    width,height=size
    x,y,r=mark
    center=(round(x*width),round(y*height))
    radii=(max(8,round(r*width)),max(5,round(.61*r*width)))
    rear=np.zeros((height,width),np.uint8)
    front=np.zeros_like(rear)
    angle=-23+7*math.sin(elapsed*8)
    stroke=max(2,round(width/170))
    sweep=min(180,65+elapsed*530)
    draw_arc(rear,center,radii,angle,180,180+sweep,stroke)
    draw_arc(front,center,radii,angle,0,sweep,stroke)
    if mask is not None:
        alpha=cv2.resize(mask,size,interpolation=cv2.INTER_LINEAR)
        rear=cv2.multiply(rear,255-alpha,scale=1/255)
    return rear,front


def composite_hand_context(frame, layer, index, fps):
    effect=layer.effect['body_depth']
    width,height=frame.shape[1],frame.shape[0]
    size=(min(540,width),round(height*min(540,width)/width))
    matte=read_alpha(effect['mattes'],index) if effect['mattes'] else None
    if matte is None:
        return
    elapsed=(index-layer.first)/fps
    gain=min(1.,(elapsed+.025)/.12,(layer.last-index)/max(1.,fps*.16))
    rear,front=hand_passes(size,layer.corners[index],matte,elapsed)
    for coverage,color in zip((rear,front),((253,248,230),tuple(effect['ink']))):
        if not coverage.any():
            continue
        art=np.empty((*coverage.shape,4),np.uint8)
        art[:,:,:3]=color
        art[:,:,3]=coverage
        alpha_over(frame,cv2.resize(art,(width,height),interpolation=cv2.INTER_LINEAR),gain)
