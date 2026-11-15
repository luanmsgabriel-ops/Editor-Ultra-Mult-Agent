"""Screen-space magnifying glass with actual sampled enlargement and metal rim."""
import math
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFilter

def magnify(canvas,center,radius=120,zoom=1.5,angle=45):
    if not all(math.isfinite(v) for v in (*center,radius,zoom,angle)) or radius<=0 or zoom<1:
        raise ValueError('Finite center, positive radius and zoom >=1 required')
    w,h=canvas.size;x,y=center;yy,xx=np.mgrid[:h,:w].astype(np.float32);r=np.hypot(xx-x,yy-y)
    pixels=np.asarray(canvas.convert('RGBA'),dtype=np.float32)/255;pixels[:,:,:3]*=pixels[:,:,3:4]
    sample=cv2.remap(pixels,x+(xx-x)/zoom,y+(yy-y)/zoom,cv2.INTER_CUBIC,borderMode=cv2.BORDER_REFLECT_101)
    sample[:,:,:3]/=np.maximum(sample[:,:,3:4],1e-5)
    inside=np.clip((radius-8-r)*1.5,0,1);sample[:,:,3]*=inside
    out=Image.new('RGBA',(w,h));d=ImageDraw.Draw(out)
    a=math.radians(angle);v=(math.cos(a),math.sin(a));p1=(x+v[0]*(radius-8),y+v[1]*(radius-8));p2=(x+v[0]*(radius+140),y+v[1]*(radius+140))
    d.line([p1,p2],fill=(25,27,29),width=35);d.line([(p1[0]-6,p1[1]+4),(p2[0]-6,p2[1]+4)],fill=(130,135,140),width=5)
    out.alpha_composite(Image.fromarray(np.uint8(np.clip(sample,0,1)*255)))
    ring=np.clip(1-np.abs(r-radius)/7,0,1);shine=np.clip(.3+.7*(1-(xx-x+yy-y)/(3*radius)),.15,1)
    metal=np.zeros((h,w,4),np.uint8);metal[:,:,:3]=(shine[:,:,None]*np.array([200,204,208])).astype(np.uint8);metal[:,:,3]=(ring*255).astype(np.uint8)
    out.alpha_composite(Image.fromarray(metal));d=ImageDraw.Draw(out);d.arc((x-radius+6,y-radius+6,x+radius-6,y+radius-6),200,290,fill=(255,255,255,190),width=4)
    return out
