"""Reusable alpha-preserving highlight sweep in linear light.

This is a compositing effect, not a physically rendered reflection. For a real
surface use a beveled mesh, Principled material and an animated area light.
"""
from dataclasses import dataclass
import math
import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Sweep:
    angle: float = -12.0
    width: float = .12
    intensity: float = .78
    edge_boost: float = .15
    tint: tuple = (1., .95, .88)

    def validate(self):
        values=(self.angle,self.width,self.intensity,self.edge_boost,*self.tint)
        if len(self.tint)!=3 or not all(math.isfinite(v) for v in values):
            raise ValueError('Sweep parameters must be finite RGB numbers.')
        if not 0 < self.width <= 1 or not 0 <= self.intensity <= 1 or not 0 <= self.edge_boost <= 1:
            raise ValueError('width must be in (0,1]; intensity/edge_boost in [0,1].')
        if any(not 0<=v<=1 for v in self.tint):
            raise ValueError('tint must be linear RGB in [0,1].')


def to_linear(rgb):
    return np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)


def to_srgb(rgb):
    return np.where(rgb<=.0031308,12.92*rgb,1.055*np.maximum(rgb,0)**(1/2.4)-.055)


def light_sweep(image, phase, settings=None, surface_mask=None):
    """Sweep phase 0..1 across the visible bounding box, retaining exact alpha.

    Supply the whole unoccluded word, apply this effect, then transform and
    composite it behind other layers. surface_mask can restrict highlights to
    the colored face without changing alpha or lighting neighboring accents.
    Out-of-interval phase yields an unchanged copy (one-shot, no implicit loop).
    """
    cfg=settings or Sweep();cfg.validate()
    if not math.isfinite(phase):raise ValueError('phase must be finite')
    im=image.convert('RGBA');p=np.array(im);alpha=p[:,:,3]
    if surface_mask is not None:
        if surface_mask.size!=im.size:raise ValueError('surface_mask size mismatch')
        mask=np.array(surface_mask.convert('L'),dtype=float)/255
    else:mask=alpha.astype(float)/255
    yy,xx=np.where((alpha>0)&(mask>0))
    if not len(xx) or phase<0 or phase>1 or cfg.intensity==0:return im.copy()
    x0,x1=int(xx.min()),int(xx.max())+1;y0,y1=int(yy.min()),int(yy.max())+1
    y,x=np.mgrid[y0:y1,x0:x1];theta=math.radians(cfg.angle)
    axis=((x-x0)*math.cos(theta)+(y-y0)*math.sin(theta))
    lo,hi=float(axis.min()),float(axis.max());span=max(hi-lo,1)
    sigma=span*cfg.width/2.355
    center=lo-3*sigma+phase*(span+6*sigma)
    strength=np.exp(-.5*((axis-center)/sigma)**2)*cfg.intensity
    distance=cv2.distanceTransform((alpha[y0:y1,x0:x1]>127).astype(np.uint8),cv2.DIST_L2,3)
    edge=np.exp(-distance/max(1,span*.006))
    strength=np.clip(strength*(1+cfg.edge_boost*edge),0,1)*mask[y0:y1,x0:x1]
    rgb=to_linear(p[y0:y1,x0:x1,:3]/255.)
    # A glossy bright reflection blends toward the light without painting alpha.
    target=np.maximum(rgb,np.array(cfg.tint))
    lit=rgb+(target-rgb)*strength[:,:,None]
    p[y0:y1,x0:x1,:3]=np.uint8(np.rint(np.clip(to_srgb(lit),0,1)*255))
    return Image.fromarray(p,'RGBA')
