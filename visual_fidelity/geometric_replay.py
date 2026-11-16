"""Reference-independent geometric masks, frame clocks, and alpha composition.

Geometry is authored in normalized coordinates; no photographic content is
inferred or generated. RGB layers may be partial recovered reference assets.
"""
from __future__ import annotations
import copy
from fractions import Fraction
import math
import cv2
import numpy as np

VERSION='1.0.1'


def _number(value,name):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,float,np.number)) or not math.isfinite(float(value)):
        raise ValueError(name+' must be finite numeric data')
    return float(value)


def _integer(value,name,minimum=0):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,np.integer)) or value<minimum:
        raise ValueError(name+f' must be an integer >= {minimum}')
    return int(value)


def frame_schedule(fps,frames,start_frame=0):
    """float64 times for integer frames, rationally evaluated (no accumulated drift).

    fps accepts finite positive numeric values or a rational string such as
    '24000/1001'. End time is excluded: 24 frames at 24fps spans [0,23/24].
    """
    frames=_integer(frames,'frames',1);start_frame=_integer(start_frame,'start_frame')
    if isinstance(fps,(bool,np.bool_)):raise ValueError('fps must be positive')
    try:rate=Fraction(str(fps))
    except (ValueError,TypeError,ZeroDivisionError) as exc:raise ValueError('fps must be finite and positive') from exc
    if rate<=0:raise ValueError('fps must be positive')
    return np.fromiter((float(Fraction(i,1)/rate) for i in range(start_frame,start_frame+frames)),dtype=np.float64,count=frames)


def _interpolate(a,b,t):
    if isinstance(a,dict) and isinstance(b,dict):
        if set(a)!=set(b):raise ValueError('Animated object topology must remain constant')
        return {k:_interpolate(a[k],b[k],t) for k in a}
    if isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):
        if len(a)!=len(b):raise ValueError('Animated array topology must remain constant')
        return [_interpolate(x,y,t) for x,y in zip(a,b)]
    if isinstance(a,(int,float,np.number)) and not isinstance(a,(bool,np.bool_)) and isinstance(b,(int,float,np.number)) and not isinstance(b,(bool,np.bool_)):
        va=_number(a,'key value');vb=_number(b,'key value')
        return copy.deepcopy(a) if va==vb else va+(vb-va)*t
    if a!=b:raise ValueError('Discrete fields cannot change between linear keyframes')
    return copy.deepcopy(a)


def evaluate(spec,frame):
    """Resolve inclusive integer `keyframes` using linear, held-outside motion.

    Each key is {'frame': integer, ...overrides}. Omitted fields inherit the
    previous key (the first inherits the base spec). Numeric arrays interpolate;
    shape kinds/topology remain fixed. Nested child specs can have their own keys.
    """
    frame=_integer(frame,'frame')
    if not isinstance(spec,dict):raise ValueError('Spec must be an object')
    base=copy.deepcopy({k:v for k,v in spec.items() if k!='keyframes'})
    keys=spec.get('keyframes',[])
    if not isinstance(keys,list):raise ValueError('keyframes must be a list')
    states=[];last=-1;current=base
    for key in keys:
        if not isinstance(key,dict):raise ValueError('Each keyframe must be an object')
        at=_integer(key.get('frame'),'keyframe frame')
        if at<=last:raise ValueError('Keyframe indices must be strictly increasing')
        last=at;current={**copy.deepcopy(current),**copy.deepcopy({k:v for k,v in key.items() if k!='frame'})}
        states.append((at,current))
    if states:
        if frame<=states[0][0]:base=states[0][1]
        elif frame>=states[-1][0]:base=states[-1][1]
        else:
            for (fa,a),(fb,b) in zip(states,states[1:]):
                if fa<=frame<=fb:base=_interpolate(a,b,(frame-fa)/(fb-fa));break
    def nested(value):
        if isinstance(value,dict):return evaluate(value,frame)
        if isinstance(value,(list,tuple)):return [nested(v) for v in value]
        return value
    return {k:nested(v) for k,v in base.items()}


def _pair(value,name):
    if not isinstance(value,(list,tuple,np.ndarray)) or len(value)!=2:raise ValueError(name+' must have two coordinates')
    return np.array([_number(v,name) for v in value],dtype=np.float64)


def _coverage(distance):
    # Signed distance in pixels, positive inside; one-pixel transition.
    return np.clip(distance+.5,0,1).astype(np.float32)


def mask(spec,width,height,frame=None):
    """Return float32 HxW coverage [0,1], antialiased at approximately one pixel.

    Pixel centers are (x+.5,y+.5). Normalized x uses width, y uses height.
    Strip thickness uses image HEIGHT independent of strip angle/aspect ratio.
    Angles are degrees clockwise from image +x; strip angle 0 is horizontal.
    """
    width=_integer(width,'width',1);height=_integer(height,'height',1)
    if not isinstance(spec,dict):raise ValueError('Spec must be an object')
    if frame is not None:spec=evaluate(spec,frame)
    elif spec.get('keyframes'):raise ValueError('Animated spec requires frame')
    kind=spec.get('kind');yy,xx=np.mgrid[:height,:width];xx=xx+.5;yy=yy+.5
    if kind in ('full','empty'):
        result=np.full((height,width),kind=='full',np.float32)
    elif kind=='polygon':
        points=np.asarray(spec.get('points'),dtype=float)
        if points.ndim!=2 or points.shape[1]!=2 or len(points)<3 or not np.isfinite(points).all():raise ValueError('Polygon needs >=3 finite 2D normalized points')
        if abs(cv2.contourArea(points.astype(np.float32)))<1e-12:raise ValueError('Polygon must enclose nonzero area')
        if np.max(np.abs(points*[width,height]))>1e6:raise ValueError('Polygon coordinates exceed rasterizer range')
        # Four samples per axis, pixel centers aligned to the output raster.
        scale=4;canvas=np.zeros((height*scale,width*scale),np.uint8)
        coordinates=np.rint((points*[width,height]*scale-.5)*256).astype(np.int32)
        cv2.fillPoly(canvas,[coordinates],255,lineType=cv2.LINE_8,shift=8)
        result=cv2.resize(canvas,(width,height),interpolation=cv2.INTER_AREA).astype(np.float32)/255
    elif kind in ('strip','x'):
        center=_pair(spec.get('center',[.5,.5]),'center')*[width,height]
        thickness=_number(spec.get('width'),'strip width')*height
        if thickness<0:raise ValueError('Strip width cannot be negative')
        angles=spec.get('angles',[-45,45]) if kind=='x' else [spec.get('angle',0)]
        if not isinstance(angles,(list,tuple)) or (kind=='x' and len(angles)!=2):raise ValueError('X needs two angles')
        result=np.zeros((height,width),np.float32)
        if thickness>0:
            for angle in angles:
                theta=math.radians(_number(angle,'angle'))
                signed=-math.sin(theta)*(xx-center[0])+math.cos(theta)*(yy-center[1])
                result=np.maximum(result,_coverage(thickness/2-np.abs(signed)))
    elif kind=='bands':
        axis=spec.get('axis');axis={'horizontal':'y','vertical':'x'}.get(axis,axis)
        if axis not in ('x','y'):raise ValueError('Bands axis must be x/vertical or y/horizontal')
        intervals=spec.get('intervals')
        if not isinstance(intervals,list):raise ValueError('Bands require intervals list')
        coordinate,extent=(xx,width) if axis=='x' else (yy,height)
        result=np.zeros((height,width),np.float32)
        for pair in intervals:
            lo,hi=_pair(pair,'band interval')*extent
            if hi<lo:raise ValueError('Band interval must be ordered')
            if hi>lo:result=np.maximum(result,_coverage(np.minimum(coordinate-lo,hi-coordinate)))
    elif kind=='linear_gradient':
        axis=spec.get('axis','x');axis={'horizontal':'x','vertical':'y'}.get(axis,axis)
        if axis not in ('x','y'):raise ValueError('Gradient axis must be x/horizontal or y/vertical')
        start=_number(spec.get('start',.61),'gradient start')
        end=_number(spec.get('end',.79),'gradient end')
        if end<=start:raise ValueError('Gradient end must be greater than start')
        coordinate=xx/width if axis=='x' else yy/height
        result=np.clip((end-coordinate)/(end-start),0,1).astype(np.float32)
    elif kind=='ellipse':
        center=_pair(spec.get('center',[.5,.5]),'center')*[width,height]
        radii=_pair(spec.get('radii'),'radii')*[width,height]
        if (radii<0).any():raise ValueError('Ellipse radii cannot be negative')
        if (radii==0).any():result=np.zeros((height,width),np.float32)
        else:
            theta=math.radians(_number(spec.get('angle',0),'angle'))
            dx=xx-center[0];dy=yy-center[1]
            x=math.cos(theta)*dx+math.sin(theta)*dy;y=-math.sin(theta)*dx+math.cos(theta)*dy
            implicit=1-(x/radii[0])**2-(y/radii[1])**2
            gradient=2*np.sqrt((x/radii[0]**2)**2+(y/radii[1]**2)**2)
            result=_coverage(implicit/np.maximum(gradient,1e-12))
    elif kind in ('union','intersection','subtract'):
        shapes=spec.get('shapes')
        if not isinstance(shapes,list) or not shapes or (kind=='subtract' and len(shapes)!=2):raise ValueError('Boolean mask needs child shapes (subtract needs two)')
        children=[mask(child,width,height,frame=frame) for child in shapes]
        if kind=='union':result=np.maximum.reduce(children)
        elif kind=='intersection':result=np.minimum.reduce(children)
        else:result=np.clip(children[0]-children[1],0,1)
    else:raise ValueError('Unknown geometric mask kind: '+str(kind))
    opacity=_number(spec.get('opacity',1),'mask opacity')
    if not 0<=opacity<=1:raise ValueError('Mask opacity must be in [0,1]')
    if not isinstance(spec.get('invert',False),bool):raise ValueError('invert must be boolean')
    if spec.get('invert',False):result=1-result
    return np.asarray(result*opacity,dtype=np.float32)


def _rgba(image,name):
    image=np.asarray(image)
    if image.ndim!=3 or image.shape[2] not in (3,4):raise ValueError(name+' must be HxWx3/4 RGB(A)')
    if image.dtype==np.uint8:arr=image.astype(np.float32)/255
    elif np.issubdtype(image.dtype,np.floating):
        arr=image.astype(np.float32)
        if not np.isfinite(arr).all() or np.any((arr<0)|(arr>1)):raise ValueError(name+' float samples must be finite in [0,1]')
    else:raise ValueError(name+' must be uint8 or float [0,1]')
    if arr.shape[2]==3:arr=np.concatenate([arr,np.ones((*arr.shape[:2],1),np.float32)],axis=2)
    return arr


def compose(base,insert,mask,foreground=None):
    """Insert through coverage, then overlay optional foreground, in premultiplied RGB.

    Inputs are STRAIGHT RGB/RGBA uint8 or floating [0,1], same raster. Insert alpha
    multiplies mask. Foreground RGBA supplies its own occlusion; RGB covers all.
    Return ndarray with base's dtype/channels. No resize or inferred missing art.
    """
    original=np.asarray(base);background=_rgba(base,'base');layer=_rgba(insert,'insert')
    if background.shape!=layer.shape:raise ValueError('Base and insert raster must match')
    coverage=np.asarray(mask,dtype=np.float32)
    if coverage.shape!=background.shape[:2] or not np.isfinite(coverage).all() or np.any((coverage<0)|(coverage>1)):
        raise ValueError('Mask must match raster and be finite [0,1]')
    b_alpha=background[:,:,3:4];premul=background[:,:,:3]*b_alpha
    alpha=layer[:,:,3:4]*coverage[:,:,None]
    premul=layer[:,:,:3]*alpha+premul*(1-alpha);out_alpha=alpha+b_alpha*(1-alpha)
    if foreground is not None:
        front=_rgba(foreground,'foreground')
        if front.shape!=background.shape:raise ValueError('Foreground raster must match')
        alpha=front[:,:,3:4];premul=front[:,:,:3]*alpha+premul*(1-alpha);out_alpha=alpha+out_alpha*(1-alpha)
    rgb=np.divide(premul,out_alpha,out=np.zeros_like(premul),where=out_alpha>0)
    output=rgb if original.shape[2]==3 else np.concatenate([rgb,out_alpha],axis=2)
    output=np.clip(output,0,1)
    return np.rint(output*255).astype(np.uint8) if original.dtype==np.uint8 else output.astype(original.dtype)


def decompose_observed(observed,base_guess,coverage):
    """Coupled inverse composition for an observed uint8 RGB composite.

    Return (adjusted_base, insert), uint8. In soft-alpha pixels, constrain the
    guessed base to values allowing an in-gamut insert. This avoids seams caused
    by clipping the inverse solution. The decomposition is non-unique and is
    NOT recovery of the original/hidden photography. At alpha=0 the observed
    image belongs to the base; at alpha=1 it belongs to the insert.
    """
    source=np.asarray(observed);guess=np.asarray(base_guess)
    if source.dtype!=np.uint8 or guess.dtype!=np.uint8 or source.ndim!=3 or source.shape[-1]!=3 or guess.shape!=source.shape:
        raise ValueError('Observed and base guess must be matching uint8 RGB rasters')
    a=np.asarray(coverage,dtype=np.float32)
    if a.shape!=source.shape[:2] or not np.isfinite(a).all() or np.any((a<0)|(a>1)):
        raise ValueError('Coverage must match raster and be finite [0,1]')
    base=guess.copy();insert=np.zeros_like(source)
    base[a==0]=source[a==0];insert[a==1]=source[a==1]
    soft=(a>0)&(a<1)
    if soft.any():
        weight=a[soft,None];pixel=source[soft].astype(np.float32)
        low=np.maximum(0,(pixel-255*weight)/(1-weight))
        high=np.minimum(255,pixel/(1-weight))
        base[soft]=np.rint(np.clip(base[soft],np.ceil(low),np.floor(high))).astype(np.uint8)
        solved=(pixel-(1-weight)*base[soft])/weight
        insert[soft]=np.rint(np.clip(solved,0,255)).astype(np.uint8)
    return base,insert
