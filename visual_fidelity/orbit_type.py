"""Cylinder-mapped type with perspective and explicit front/back compositing.

This CPU renderer projects textured strips in 3D coordinates. It is 2.5D artwork,
not an editable extruded glyph mesh or a recovered camera solve. Screen placement,
depth, phase and holdout are independent, so rear text cannot be baked into a cutout.
"""
from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class OrbitSpec:
    size: tuple = (720, 1280)
    center: tuple = (360., 740.)
    radius_x: float = 420.
    radius_z: float = 300.
    camera_distance: float = 1500.
    tilt_deg: float = -18.
    pitch_deg: float = 6.
    phase: float = 0.
    font_size: int = 145
    tracking: float = 0.
    gap: float = 35.
    repeats: int = 5
    strip_width: int = 12
    thickness: float = 5.
    color: tuple = (204, 3, 15)
    highlight_phase: float = 0.

    def validate(self):
        values=(*self.center,self.radius_x,self.radius_z,self.camera_distance,
                self.tilt_deg,self.pitch_deg,self.phase,self.tracking,self.gap,self.thickness)
        if not np.isfinite(values).all():
            raise ValueError('Orbit parameters must be finite.')
        if (min(self.size)<=0 or min(self.radius_x,self.radius_z)<=0 or
            self.camera_distance <= self.radius_z+self.font_size or
            self.font_size<=0 or self.repeats<1 or self.strip_width<2 or self.thickness<0):
            raise ValueError('Invalid size, radius, camera clearance or text settings.')


@lru_cache(maxsize=16)
def _face(path, size):
    return ImageFont.truetype(str(path),size)


def text_metrics(text, font_path, font_size, tracking=0.):
    """Actual font advances, including pair kerning; no equal-width glyph spacing."""
    font=_face(str(font_path),font_size)
    positions=[]
    for i,char in enumerate(text):
        start=font.getlength(text[:i+1])-font.getlength(char)+i*tracking
        positions.append((char,float(start),float(font.getlength(char))))
    return positions,float(font.getlength(text)+max(0,len(text)-1)*tracking)


@lru_cache(maxsize=24)
def _texture(text,path,size,tracking,gap,repeats):
    font=_face(path,size)
    positions,width=text_metrics(text,path,size,tracking)
    left,top,right,bottom=font.getbbox(text)
    h=bottom-top+6
    period=max(2,math.ceil(width+gap))
    mask=Image.new('L',(period*repeats,h))
    draw=ImageDraw.Draw(mask)
    for j in range(repeats):
        for char,x,advance in positions:
            draw.text((j*period+x,3-top),char,font=font,fill=255)
    return np.asarray(mask),period


def project_ring(theta, vertical, spec, radial_offset=0.):
    """Project radians and a vertical glyph coordinate; z>0 is nearer camera."""
    rx,rz=spec.radius_x+radial_offset,spec.radius_z+radial_offset
    x=rx*np.sin(theta);z=rz*np.cos(theta)
    p=math.radians(spec.pitch_deg)
    y=vertical*np.cos(p)+z*np.sin(p)
    z=z*np.cos(p)-vertical*np.sin(p)
    scale=spec.camera_distance/(spec.camera_distance-z)
    x,y=x*scale,y*scale
    a=math.radians(spec.tilt_deg)
    return (spec.center[0]+x*np.cos(a)-y*np.sin(a),
            spec.center[1]+x*np.sin(a)+y*np.cos(a),z)


def _over(dst,patch,quad):
    """Premultiplied perspective warp limited to the actual destination bounds."""
    q=np.asarray(quad,np.float32)
    x0=max(0,int(np.floor(q[:,0].min()))-1);y0=max(0,int(np.floor(q[:,1].min()))-1)
    x1=min(dst.shape[1],int(np.ceil(q[:,0].max()))+2);y1=min(dst.shape[0],int(np.ceil(q[:,1].max()))+2)
    if x1<=x0 or y1<=y0:return
    h,w=patch.shape[:2]
    source=np.float32([[0,0],[w,0],[w,h],[0,h]])
    transform=cv2.getPerspectiveTransform(source,np.float32(q-[x0,y0]))
    warped=cv2.warpPerspective(patch,transform,(x1-x0,y1-y0),flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_REPLICATE)
    # Adjacent cylinder patches share an edge. Transparent texture borders create
    # seams through opaque glyph interiors; replicate texels and clip to geometry.
    coverage=np.zeros((y1-y0,x1-x0),np.uint8)
    cv2.fillConvexPoly(coverage,np.rint(q-[x0,y0]).astype(np.int32),255)
    warped*=coverage[:,:,None]/255.
    region=dst[y0:y1,x0:x1]
    region[:]=warped+region*(1-warped[:,:,3:4])


def _straight_rgba(premul):
    alpha=np.clip(premul[:,:,3],0,1)
    rgb=premul[:,:,:3]/np.maximum(alpha[:,:,None],1e-6)
    return Image.fromarray(np.uint8(np.clip(np.dstack([rgb,alpha]),0,1)*255))


def render_orbit_type(text,font_path,spec,occluder_alpha=None):
    """Return (rear, front) RGBA layers; positive z remains in front of subject.

    With a supplied occluder alpha, rear pixels are attenuated by its coverage.
    Otherwise compose background -> rear -> subject -> front. Alpha is not baked
    into the source lettering, allowing arbitrary independent subject motion.
    """
    spec.validate()
    mask,period=_texture(text,str(Path(font_path)),spec.font_size,spec.tracking,spec.gap,spec.repeats)
    h,w=mask.shape;shape=(spec.size[1],spec.size[0],4)
    rear=np.zeros(shape,np.float32);front=np.zeros(shape,np.float32)
    # Uniform physical spacing along an elliptical cylinder, not uniform angles.
    angles=np.linspace(0,2*np.pi,4097)
    speed=np.sqrt((spec.radius_x*np.cos(angles))**2+(spec.radius_z*np.sin(angles))**2)
    arc=np.cumsum((speed[1:]+speed[:-1])/2*np.diff(angles));arc=np.r_[0,arc]
    records=[]
    for start in range(0,w,spec.strip_width):
        end=min(w,start+spec.strip_width)
        if not mask[:,start:end].any():continue
        theta=np.interp(np.array([start,end])/w*arc[-1],arc,angles)+spec.phase
        mid=(theta[0]+theta[1])/2
        records.append((math.cos(mid),start,end,theta,mid))
    records.sort(key=lambda r:r[0])
    for side,start,end,theta,mid in records:
        dest=front if side>=0 else rear
        alpha=mask[:,start:end].astype(np.float32)/255
        # Directional broad reflection varies on the curved surface, not in screen space.
        column_angles=np.linspace(theta[0],theta[1],end-start,endpoint=False)
        reflection=np.arctan2(np.sin(column_angles-spec.highlight_phase),np.cos(column_angles-spec.highlight_phase))
        specular=.58*np.exp(-(reflection/.20)**2)
        diffuse=.64+.36*np.maximum(0,np.cos(column_angles-.3))
        color=np.asarray(spec.color,dtype=np.float32)[None,:]/255*diffuse[:,None]
        color=color*(1-specular[:,None])+np.array([1,.78,.73])*specular[:,None]
        face=np.dstack([alpha[:,:,None]*color,alpha])
        if spec.thickness:
            edge=np.dstack([alpha[:,:,None]*np.asarray(spec.color)/255*.35,alpha])
            quad=[project_ring(theta[0],-h/2,spec,-spec.thickness)[:2],
                  project_ring(theta[1],-h/2,spec,-spec.thickness)[:2],
                  project_ring(theta[1],h/2,spec,-spec.thickness)[:2],
                  project_ring(theta[0],h/2,spec,-spec.thickness)[:2]]
            _over(dest,edge,quad)
        quad=[project_ring(theta[0],-h/2,spec)[:2],project_ring(theta[1],-h/2,spec)[:2],
              project_ring(theta[1],h/2,spec)[:2],project_ring(theta[0],h/2,spec)[:2]]
        _over(dest,face,quad)
    if occluder_alpha is not None:
        alpha=np.asarray(occluder_alpha.convert('L'),dtype=np.float32)/255
        if alpha.shape!=shape[:2]:raise ValueError('Occluder and canvas must have identical sizes.')
        rear*=1-alpha[:,:,None]
    return _straight_rgba(rear),_straight_rgba(front)


def composite_orbit(background,subject,rear,front):
    """Depth ordering preserves the unmodified subject and lettering assets."""
    if len({im.size for im in (background,subject,rear,front)})!=1:
        raise ValueError('All compositing layers must have identical dimensions.')
    image=background.convert('RGBA').copy()
    for layer in (rear,subject,front):image.alpha_composite(layer.convert('RGBA'))
    return image
