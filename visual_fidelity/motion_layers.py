"""Non-destructive ordered RGBA layers with a common animated parent."""
from dataclasses import dataclass
import math
import cv2
import numpy as np
from PIL import Image

@dataclass(frozen=True)
class Transform:
    x: float = 0
    y: float = 0
    scale: float = 1
    angle: float = 0
    opacity: float = 1
    pivot: tuple = (0,0)

def transform_layer(image, transform, size=None):
    t=transform;size=size or image.size
    if not all(math.isfinite(v) for v in (t.x,t.y,t.scale,t.angle,t.opacity,*t.pivot)):
        raise ValueError('Transform values must be finite')
    if t.scale<=0 or not 0<=t.opacity<=1:raise ValueError('Invalid scale or opacity')
    p=np.asarray(image.convert('RGBA'),dtype=np.float32)/255
    p[:,:,:3]*=p[:,:,3,None]
    mat=cv2.getRotationMatrix2D(tuple(t.pivot),t.angle,t.scale);mat[:,2]+=(t.x,t.y)
    p=cv2.warpAffine(p,mat,size,flags=cv2.INTER_CUBIC)
    alpha=np.clip(p[:,:,3],0,1);rgb=np.clip(p[:,:,:3]/np.maximum(alpha[:,:,None],1e-6),0,1)
    return Image.fromarray(np.uint8(np.rint(np.dstack([rgb,alpha*t.opacity])*255)),'RGBA')

def compose_group(size, layers, parent=None):
    """Composite back to front, then transform the parent once.

    Each entry is (image, child_transform) with image-local coordinates. Every
    source image remains intact even when fully covered in this frame.
    """
    result=Image.new('RGBA',size)
    for image,child in layers:result.alpha_composite(transform_layer(image,child,size))
    return transform_layer(result,parent,size) if parent else result
