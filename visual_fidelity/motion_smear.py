"""Shot-local exposure of premultiplied artwork, never footage.

Positions are (frame_time, x_px, y_px), in output-raster coordinates. The input
is the artwork already placed at current. Exposure trails current by default.
No color under zero alpha, border replication, or unpremultiplication is used.
"""
import math
import numpy as np
import cv2


def smear(artwork, *, before, current, after, shot, cuts=(), exposure=0.75,
          shutter_end=0.0, samples=17, max_displacement=64.0, protection=None):
    """Return float32 premultiplied RGBA and execution geometry receipt.

    Exposure and shutter_end are in frames; shutter_end=0 is trailing and .5
    centers a one-frame exposure. Path is piecewise-linear through the supplied
    observations. No extrapolation, gap filling, or shot crossing is allowed.
    protection is an optional matching float [0,1] mask (1=fully protected),
    applied after integration to the ENTIRE RGBA, including alpha.
    """
    a=np.asarray(artwork)
    if a.dtype != np.float32 or a.ndim!=3 or a.shape[2]!=4 or not np.isfinite(a).all():
        raise ValueError('artwork must be finite float32 premultiplied RGBA')
    if np.any(a<0) or np.any(a>1) or np.any(a[:,:,:3]>a[:,:,3:]+1e-7):
        raise ValueError('invalid premultiplied RGBA, including color under transparent alpha')
    keys=np.asarray([before,current,after],dtype=float)
    if keys.shape!=(3,3) or not np.isfinite(keys).all() or not (keys[0,0]<keys[1,0]<keys[2,0]):
        raise ValueError('three ordered finite observations required')
    if len(shot)!=2 or not all(math.isfinite(x) for x in shot) or not shot[0]<shot[1]:
        raise ValueError('invalid half-open shot window')
    if not all(shot[0]<=t<shot[1] for t in keys[:,0]):
        raise ValueError('observation crosses shot boundary')
    if any(not math.isfinite(c) or keys[0,0]<c<=keys[2,0] for c in cuts):
        raise ValueError('observation interval crosses declared hard cut')
    if not (math.isfinite(exposure) and 0<=exposure<=1 and math.isfinite(shutter_end)
            and 0<=shutter_end<=1 and math.isfinite(max_displacement) and 0<max_displacement<=256):
        raise ValueError('invalid bounded shutter or displacement')
    if type(samples) is not int or not 3<=samples<=65 or samples%2!=1:
        raise ValueError('use an odd integration sample count from 3 to 65')
    mask=None
    if protection is not None:
        mask=np.asarray(protection)
        if mask.shape!=a.shape[:2] or not np.isfinite(mask).all() or np.any(mask<0) or np.any(mask>1):
            raise ValueError('protection must match raster with finite values in [0,1]')
    lo=keys[1,0]+shutter_end-exposure;hi=keys[1,0]+shutter_end
    if lo<keys[0,0] or hi>keys[2,0]:
        raise ValueError('shutter requires extrapolation beyond observations')
    times=np.linspace(lo,hi,samples)
    offsets=np.column_stack([np.interp(times,keys[:,0],keys[:,i])-keys[1,i] for i in (1,2)])
    distance=np.linalg.norm(offsets,axis=1)
    if distance.max()>max_displacement:
        raise ValueError('measured shutter displacement exceeds safety bound')
    if not np.any(offsets):
        result=a.copy()
    else:
        weights=np.ones(samples,dtype=np.float64);weights[[0,-1]]=.5;weights/=weights.sum()
        result=np.zeros_like(a)
        for (dx,dy),weight in zip(offsets,weights):
            matrix=np.array([[1,0,dx],[0,1,dy]],dtype=np.float32)
            shifted=cv2.warpAffine(a,matrix,(a.shape[1],a.shape[0]),flags=cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0,0))
            result+=shifted*weight
    if mask is not None:result*=1-mask.astype(np.float32)[:,:,None]
    # Numerical canonicalization only, never a spatial expansion of alpha.
    result[:,:,:3]=np.minimum(result[:,:,:3],result[:,:,3:])
    result[result[:,:,3]==0]=0
    return result,{'schema':'premultiplied-motion-smear/1','interval':[float(lo),float(hi)],
        'offset_start_px':offsets[0].tolist(),'offset_end_px':offsets[-1].tolist(),
        'max_displacement_px':float(distance.max()),'samples':samples,
        'path':'piecewise_linear_observations','footage_modified':False,
        'protection_applied':mask is not None,'aesthetic_approved':False}
