"""Replay a measured reference composition with explicit replacement layers.

Source clocks, final-screen matte transforms and physical camera reprojection
are independent. A new subject never implies a new layout or a proxy chair.
"""
from dataclasses import dataclass
from pathlib import Path
import math
import cv2
import numpy as np
from PIL import Image, ImageFilter
from .motion_layers import Transform, transform_layer

VERSION = "1.0"

@dataclass(frozen=True)
class SourceClock:
    output_start: int
    output_end: int
    source_start: int
    speed: float = 1.
    def frame(self, output_frame, source_count):
        if not self.output_start <= output_frame < self.output_end:
            raise ValueError('Frame outside bound scene')
        if not math.isfinite(self.speed) or self.speed <= 0:
            raise ValueError('Source speed must be positive and finite')
        n=self.source_start+math.floor((output_frame-self.output_start)*self.speed+1e-8)
        if not 0<=n<source_count:raise ValueError('Source clock exceeds footage; no implicit loop/freeze')
        return n

class MatteFootage:
    def __init__(self, video, masks, edge_decontamination=0):
        self.video=Path(video);self.masks=Path(masks);self.edge_decontamination=edge_decontamination
        self.capture=cv2.VideoCapture(str(video))
        if not self.capture.isOpened():raise FileNotFoundError(video)
        self.count=int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT));self.next_frame=0
    def read(self,n):
        if not 0<=n<self.count:raise ValueError('Source frame out of range')
        if self.next_frame!=n:self.capture.set(cv2.CAP_PROP_POS_FRAMES,n)
        ok,bgr=self.capture.read();self.next_frame=n+1
        if not ok:raise RuntimeError(f'Unable to decode source frame {n}')
        rgba=Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)).convert('RGBA')
        with Image.open(self.masks/f'{n:04d}.png') as mask:
            if mask.size!=rgba.size:raise ValueError('Matte and footage resolution differ')
            rgba.putalpha(mask.convert('L').filter(ImageFilter.GaussianBlur(.45)) if self.edge_decontamination else mask.convert('L'))
        if self.edge_decontamination:rgba=decontaminate_matte_edge(rgba,self.edge_decontamination)
        return rgba
    def layer(self, clock, frame, transform, size=(720,1280)):
        return transform_layer(self.read(clock.frame(frame,self.count)),transform,size)
    def close(self):self.capture.release()

def camera_plane_homography(rotation, translation, focal, principal, origin, u, v):
    """Plane (u,v,1) to screen using the SAME physical-camera pass as background."""
    R=np.asarray(rotation,dtype=float);t=np.asarray(translation,dtype=float)
    K=np.array([[focal,0,principal[0]],[0,focal,principal[1]],[0,0,1.]])
    H=K@np.column_stack((R@np.asarray(u),R@np.asarray(v),R@np.asarray(origin)+t))
    if not np.isfinite(H).all() or abs(np.linalg.det(H))<1e-10:raise ValueError('Degenerate camera/plane')
    return H/H[2,2]

def warp_rgba(image, homography, size):
    p=np.asarray(image.convert('RGBA'),dtype=np.float32)/255
    p[:,:,:3]*=p[:,:,3,None]
    p=cv2.warpPerspective(p,np.asarray(homography,dtype=float),size,flags=cv2.INTER_CUBIC)
    alpha=np.clip(p[:,:,3:4],0,1)
    rgb=np.clip(p[:,:,:3]/np.maximum(alpha,1e-6),0,1)
    return Image.fromarray(np.uint8(np.rint(np.concatenate((rgb,alpha),axis=2)*255)))

def compose_bound_layers(size, ordered_roles, callbacks, frame):
    """Missing reference roles fail visibly instead of silently dropping assets."""
    if len(set(ordered_roles))!=len(ordered_roles):raise ValueError('Duplicate layer role')
    missing=set(ordered_roles)-set(callbacks)
    if missing:raise ValueError('Unbound reference roles: '+', '.join(sorted(missing)))
    out=Image.new('RGBA',size)
    for role in ordered_roles:
        layer=callbacks[role](frame)
        if layer.mode!='RGBA' or layer.size!=size:raise ValueError(f'Invalid layer {role}')
        out.alpha_composite(layer)
    return out


def decontaminate_matte_edge(image, radius=2):
    """Extend nearby foreground color into the soft boundary; keep alpha/interior.

    This treats a narrow edge band only. It is not neural hair reconstruction.
    Radius is source pixels, before final-screen magnification.
    """
    if radius<1 or radius>8:raise ValueError('Edge radius must be 1..8 source pixels')
    p=np.asarray(image.convert('RGBA')).copy();alpha=p[:,:,3]
    solid=cv2.erode(np.uint8(alpha>=250),np.ones((2*radius+1,2*radius+1),np.uint8))
    if not solid.any():return image.copy()
    _,labels=cv2.distanceTransformWithLabels(np.uint8(solid==0),cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
    colors=p[:,:,:3][solid>0]
    band=(alpha>0)&(solid==0)
    p[:,:,:3][band]=colors[np.maximum(labels[band]-1,0)]
    return Image.fromarray(p)
