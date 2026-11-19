"""Shot-local optical accents without changing the frame/audio clock.

No inferred camera, matte, or interpolation across shots. A screen-space focus
pulse changes the source frame before independent type and editorial layers.
"""
from dataclasses import dataclass
from math import isfinite, pi, sin
from numbers import Real

import cv2
import numpy as np


@dataclass(frozen=True)
class FocusPulse:
    """An authored [start, end) window; first/last included frames are neutral."""
    start: int
    end: int
    sigma_px: float = 3.0
    zoom: float = 0.0
    center: tuple[float, float] = (.5, .5)
    protect_right_at: float | None = None
    protection_feather: float = .10

    def validate(self):
        if any(type(n) is not int for n in (self.start, self.end)) or self.start < 0 or self.end-self.start < 5:
            raise ValueError("Focus window needs >= 5 frames with strict integer bounds.")
        for key, v, lo, hi in (
            ("sigma_px", self.sigma_px, 0, 12), ("zoom", self.zoom, 0, .08),
            ("protection_feather", self.protection_feather, .01, .35),
        ):
            if isinstance(v, bool) or not isinstance(v, Real) or not isfinite(v) or not lo<=v<=hi:
                raise ValueError(f"Invalid focus pulse {key}.")
        if not isinstance(self.center, tuple) or len(self.center) != 2 or any(
            isinstance(v, bool) or not isinstance(v, Real) or not isfinite(v) or not .15 <= v <= .85 for v in self.center
        ):
            raise ValueError("Center must be a normalized pair with safe image margins.")
        if self.protect_right_at is not None:
            edge=self.protect_right_at
            if (isinstance(edge, bool) or not isinstance(edge, Real) or not isfinite(edge)
                    or not .36<=edge<1 or self.protection_feather>=edge):
                raise ValueError("Protected edge must be normalized inside the frame.")
            if self.zoom:
                raise ValueError("Partial zoom can split objects; right protection supports blur only.")
        return self

    def strength(self, index):
        if index <= self.start or index >= self.end-1:
            return 0.0
        return sin(pi*(index-self.start)/(self.end-self.start-1))**2


def compile_pulses(pulses, *, frame_count, tracking_breaks=(), protected_intervals=()):
    """Validate all supplied windows before calling the renderer."""
    if type(frame_count) is not int or frame_count < 1:
        raise ValueError("An explicit positive decoded-frame count is required.")
    pulses=tuple(pulses)
    tracking_breaks=tuple(tracking_breaks)
    protected_intervals=tuple(protected_intervals)
    if any(not isinstance(v,FocusPulse) for v in pulses):
        raise ValueError("Invalid focus pulse definition.")
    if any(type(v) is not int or not 0<v<frame_count for v in tracking_breaks):
        raise ValueError("Invalid tracking boundary.")
    if any(not isinstance(v,(list,tuple)) or len(v)!=2 or any(type(i) is not int for i in v) or not 0<=v[0]<v[1]<=frame_count
           for v in protected_intervals):
        raise ValueError("Invalid protected interval.")
    prior_end=0
    compiled=[]
    for pulse in pulses:
        pulse.validate()
    for pulse in sorted(pulses,key=lambda x:x.start):
        if pulse.end>frame_count or prior_end>pulse.start:
            raise ValueError("Focus pulses must fit the source and may not overlap.")
        if any(pulse.start<cut<pulse.end for cut in tracking_breaks):
            raise ValueError("Focus pulse crossed a protected shot or tracking boundary.")
        if any(pulse.start<b and a<pulse.end for a,b in protected_intervals):
            raise ValueError("Focus pulse touches a protected transition interval.")
        compiled.append(pulse)
        prior_end=pulse.end
    return tuple(compiled)


def apply_focus_pulses(frame, index, pulses):
    """Apply the selected optical transform, or return the original array."""
    pulse=next((p for p in pulses if p.start<index<p.end-1),None)
    if pulse is None:
        return frame
    s=pulse.strength(index)
    h,w=frame.shape[:2]
    work=frame
    if pulse.zoom:
        center=(pulse.center[0]*(w-1),pulse.center[1]*(h-1))
        matrix=cv2.getRotationMatrix2D(center,0,1+pulse.zoom*s)
        # Zoom in only; never reveal pixels outside the real raster.
        work=cv2.warpAffine(work,matrix,(w,h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REFLECT_101)
    if pulse.sigma_px*s >= .15:
        sigma=pulse.sigma_px*s
        softened=cv2.GaussianBlur(work,(0,0),sigmaX=sigma,sigmaY=sigma*.82,borderType=cv2.BORDER_REFLECT_101)
        if pulse.protect_right_at is None:
            return softened
        xpos=np.arange(w,dtype=np.float32)/(max(1,w-1))
        q=np.clip((pulse.protect_right_at-xpos)/pulse.protection_feather,0,1)
        wgt=(q*q*(3-2*q))[None,:,None]
        work=np.rint(work*(1-wgt)+softened*wgt).astype(np.uint8)
    return work
