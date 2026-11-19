"""Explicit independently tracked foreground-layer keyframes."""
from dataclasses import dataclass
from math import isfinite
@dataclass(frozen=True)
class Pose:
    frame:int
    x:float
    y:float
    scale:float
    angle:float
    opacity:float

def poses(keys, *, start, end, cuts=()):
    keys=tuple(keys)
    if len(keys)<2 or any(type(k.frame) is not int or not all(isfinite(v) for v in (k.x,k.y,k.scale,k.angle,k.opacity)) or not .2<=k.scale<=3 or not 0<=k.opacity<=1 for k in keys):
        raise ValueError("invalid foreground layer pose")
    if keys[0].frame!=start or keys[-1].frame!=end-1 or any(a.frame>=b.frame for a,b in zip(keys,keys[1:])):
        raise ValueError("keyframes must be strictly ordered and bound the active window")
    if any(start<c<end for c in cuts):
        raise ValueError("layer path crosses declared shot boundary")
    if keys[0].opacity or keys[-1].opacity:
        raise ValueError("bookends must be neutral")
    table={}
    for a,b in zip(keys,keys[1:]):
        for f in range(a.frame,b.frame+1):
            u=(f-a.frame)/(b.frame-a.frame)
            e=u*u*(3-2*u)
            old,new=(a.x,a.y,a.scale,a.angle,a.opacity),(b.x,b.y,b.scale,b.angle,b.opacity)
            table[f]=Pose(f,*(x+(y-x)*e for x,y in zip(old,new)))
    return table
