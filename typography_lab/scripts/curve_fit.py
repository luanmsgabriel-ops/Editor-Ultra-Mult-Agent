"""Cubic least-squares fitting of closed raster contours for scalable type outlines."""
import numpy as np
from scipy.ndimage import gaussian_filter1d

def unit(v):
 n=np.linalg.norm(v);return v/max(n,1e-12)
def fit(points,error=.5):
 points=np.asarray(points,float)
 points=gaussian_filter1d(points,.85,axis=0,mode='wrap')
 # Move seam to the topmost point; preserve contour winding.
 k=np.argmin(points[:,1]);points=np.roll(points,-k,axis=0)
 a=np.vstack([points,points[:1]])
 def recursive(p,left,right,depth=0):
  if len(p)==2:
   d=np.linalg.norm(p[1]-p[0])/3;return [(p[0],p[0]+left*d,p[-1]+right*d,p[-1])]
  dist=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))];t=dist/max(dist[-1],1e-12)
  b0=(1-t)**3;b1=3*t*(1-t)**2;b2=3*t*t*(1-t);b3=t**3
  A=np.stack([b1[:,None]*left,b2[:,None]*right],axis=2).reshape(-1,2)
  rhs=(p-((b0+b1)[:,None]*p[0]+(b2+b3)[:,None]*p[-1])).ravel()
  alpha=np.linalg.lstsq(A,rhs,rcond=None)[0]
  if min(alpha)<1e-5 or max(alpha)>dist[-1]*2:alpha[:]=dist[-1]/3
  c=np.array([p[0],p[0]+left*alpha[0],p[-1]+right*alpha[1],p[-1]])
  pred=b0[:,None]*c[0]+b1[:,None]*c[1]+b2[:,None]*c[2]+b3[:,None]*c[3]
  ds=np.sum((pred-p)**2,axis=1);split=int(np.argmax(ds))
  if ds[split]<=error**2 or depth>20:return [c]
  split=max(1,min(len(p)-2,split));tangent=unit(p[split-1]-p[split+1])
  return recursive(p[:split+1],left,tangent,depth+1)+recursive(p[split:],-tangent,right,depth+1)
 return recursive(a,unit(points[1]-points[-1]),unit(points[-1]-points[1]))
