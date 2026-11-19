"""Framebuffer-backed refractive glass; no background image or flat colour fill.
Rounded rectangular lens mapped through a verified convex quad. Authored 2.5D
optics, not recovered physical refractive index or a full ray tracer.
"""
import cv2
import numpy as np

def composite_liquid_glass(frame, quad, *, strength_px=10., opacity=.9, bevel_px=18.,
                           glow=0., protection=None, receipt=None):
    if frame.dtype!=np.uint8 or frame.ndim!=3 or frame.shape[2]!=3:raise ValueError('uint8 BGR frame required')
    h,w=frame.shape[:2];q=np.asarray(quad,np.float32)
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q):raise ValueError('Finite convex quad required')
    if not (0<=opacity<=1 and 0<=strength_px<=32 and 2<=bevel_px<=64 and 0<=glow<=1):raise ValueError('Invalid optical limits')
    if protection is not None and (protection.shape!=(h,w) or protection.dtype!=np.uint8):raise ValueError('Protection must match raster uint8')
    q=q*np.array([w,h],np.float32)
    width=float(np.linalg.norm(q[1]-q[0]));height=float(np.linalg.norm(q[3]-q[0]))
    if min(width,height)<20:raise ValueError('Lens too small')
    src=np.float32([[0,0],[width,0],[width,height],[0,height]])
    inv=cv2.getPerspectiveTransform(q,src)
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    denom=inv[2,0]*xx+inv[2,1]*yy+inv[2,2]
    if np.any(abs(denom)<1e-6):raise ValueError('Singular projected lens')
    u=(inv[0,0]*xx+inv[0,1]*yy+inv[0,2])/denom
    v=(inv[1,0]*xx+inv[1,1]*yy+inv[1,2])/denom
    radius=min(height*.46,width*.23)
    ax=abs(u-width/2)-(width/2-radius);ay=abs(v-height/2)-(height/2-radius)
    sdf=np.sqrt(np.maximum(ax,0)**2+np.maximum(ay,0)**2)+np.minimum(np.maximum(ax,ay),0)-radius
    coverage=np.clip(.5-sdf,0,1).astype(np.float32)
    gy,gx=np.gradient(sdf);norm=np.sqrt(gx*gx+gy*gy)+1e-6;nx=gx/norm;ny=gy/norm
    depth=np.maximum(-sdf,0);rim=np.exp(-depth/bevel_px)*coverage
    # Rim bends framebuffer rays; small interior magnification preserves visible texture.
    dx=(-nx*strength_px*rim+(xx-q[:,0].mean())*.025*coverage).astype(np.float32)
    dy=(-ny*strength_px*rim+(yy-q[:,1].mean())*.025*coverage).astype(np.float32)
    if strength_px==0:dx[:]=0;dy[:]=0
    original=frame.astype(np.float32)/255
    bent=cv2.remap(original,xx+dx,yy+dy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
    # Fresnel rim has directional highlight and opposite dark edge, not opaque badge fill.
    spec=(np.maximum(-.65*nx-.76*ny,0)**8)*rim
    opposite=(np.maximum(.65*nx+.76*ny,0)**5)*rim
    narrow=np.exp(-np.abs(sdf+1.)/1.25)*coverage
    optical=np.clip(bent*(1-.12*rim[...,None])+.27*spec[...,None]-.10*opposite[...,None]+(.16*narrow*np.maximum(-.65*nx-.76*ny,.10))[...,None],0,1)
    protect=np.zeros((h,w),np.float32) if protection is None else protection.astype(np.float32)/255
    alpha=coverage*opacity*(1-protect)
    # Glow outside body only, separately controlled and masked.
    halo=np.clip(cv2.GaussianBlur(coverage,(0,0),max(2,bevel_px*.7))-coverage,0,1)*glow*(1-protect)
    composed=original*(1-alpha[...,None])+optical*alpha[...,None]
    composed+=halo[...,None]*np.array([.12,.07,.36],np.float32)
    frame[:]=np.rint(np.clip(composed,0,1)*255).astype(np.uint8)
    if receipt is not None:
        active=(alpha>.1)&(np.sqrt(dx*dx+dy*dy)>.5)
        receipt.update({'kind':'framebuffer_refraction','active_refracted_pixels':int(active.sum()),'max_displacement_px':float(np.sqrt(dx*dx+dy*dy).max()),'mean_displacement_active_px':float(np.sqrt(dx*dx+dy*dy)[active].mean()) if active.any() else 0.,'refraction_rgb_mae_active':float(abs(bent-original)[active].mean()) if active.any() else 0.,'body_alpha_max':float(alpha.max()),'glow_alpha_max':float(halo.max()),'protected_modified_pixels':int(np.count_nonzero(np.any(frame!=np.rint(original*255).astype(np.uint8),axis=2)&(protect>=1))), 'outside_modified_pixels':int(np.count_nonzero(np.any(frame!=np.rint(original*255).astype(np.uint8),axis=2)&(alpha==0)&(halo==0)))})
    return frame

def audit_refraction(frame, quad, **options):
    """Ablation detects flat-badge regressions without treating flat video as failure."""
    options={k:v for k,v in options.items() if k!='receipt'}
    actual=frame.copy();flat=frame.copy();receipt={}
    composite_liquid_glass(actual,quad,receipt=receipt,**options)
    composite_liquid_glass(flat,quad,**{**options,'strength_px':0.})
    delta=np.max(abs(actual.astype(float)-flat),axis=2)
    changed=int(np.count_nonzero(delta>1))
    receipt['ablation_changed_pixels']=changed
    receipt['ablation_mae_8bit']=float(delta.mean())
    receipt['verdict']='verified_framebuffer_refraction' if changed>=16 and receipt['max_displacement_px']>.5 else 'inconclusive_no_visible_texture_response'
    return receipt
