"""Code-generated materials for the Origins match cut. Coordinates are 360×640."""
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.interpolate import CubicSpline

from .annulus import band_mesh, paint_bands
from .mark import stamp

W,H=360,640
Y,X=np.mgrid[:H,:W].astype('float32')
CENTER=(180,320)
RNG=np.random.default_rng(329524)
GRAIN=RNG.normal(0,1,(H,W)).astype('float32')
SMOOTH=cv2.resize(RNG.normal(0,1,(24,15)).astype('float32'),(W,H),interpolation=cv2.INTER_CUBIC)
FRACTAL=SMOOTH*.27
for step,amplitude in [(48,.24),(94,.17),(153,.15),(280,.12)]:
    FRACTAL += cv2.resize(RNG.normal(0,1,(step,step)).astype('float32'),
                          (W,H),interpolation=cv2.INTER_CUBIC)*amplitude
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
MONO='/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
LOGO=None
TEXT_FONT=FONT
WORDMARK=None
CAP_PLATE=None
CAP_HAS_LOGO=False


def rgb(gray):
    return np.repeat(np.asarray(gray)[...,None],3,axis=-1).astype('float32')


def flat(level=0):
    return np.full((H,W,3),level,dtype='float32')


def gauss(cx,cy,sx,sy):
    return np.exp(-((X-cx)/sx)**2-((Y-cy)/sy)**2)


def text(canvas, runs):
    layer=Image.fromarray(np.clip(canvas,0,255).astype('uint8'))
    draw=ImageDraw.Draw(layer)
    for x,y,content,size,color,face in runs:
        for index,line in enumerate(content.splitlines()):
            draw.text((x,y+index*round(size*1.17)),line,font=font(TEXT_FONT if face==FONT else face,size),fill=color,anchor='lt')
    canvas[:]=np.asarray(layer)


@lru_cache(maxsize=32)
def font(face,size):
    return ImageFont.truetype(face,size)


def mark(image, color, center=CENTER, scale=1, registered=False):
    stamp(image,LOGO['mark'],color,center,scale)
    if registered:
        stamp(image,LOGO['registration'],color,center,scale)


def poly(vertices):
    layer=np.zeros((H,W),'uint8')
    cv2.fillPoly(layer,[np.rint(vertices).astype('int32')],255,cv2.LINE_AA)
    return layer


def mix(image, layer, mask):
    alpha=mask.astype('float32')[...,None]/255
    image[:]=image*(1-alpha)+layer*alpha


def rounded(image, bounds, radius, color):
    left,top,right,bottom=map(int,bounds)
    pad=np.zeros((H,W),'uint8')
    cv2.rectangle(pad,(left+radius,top),(right-radius,bottom),255,-1)
    cv2.rectangle(pad,(left,top+radius),(right,bottom-radius),255,-1)
    for cx,cy in [(left+radius,top+radius),(right-radius,top+radius),
                  (left+radius,bottom-radius),(right-radius,bottom-radius)]:
        cv2.circle(pad,(cx,cy),radius,255,-1,cv2.LINE_AA)
    mix(image,np.asarray(color),pad)


def small_legend(image, ink):
    text(image,[(56,166,'NAME: ORIGINS OF\nYEAR: 2026',5,ink,MONO),
                (263,166,'MONOGRAM',5,ink,MONO),
                (55,466,'SLSH DESIGN\nSTUDIO',5,ink,MONO),
                (253,466,"11.08555° N\n76.96612° E",5,ink,MONO)])


def grid(frame, reverse=False):
    img=flat()
    if reverse:
        level=9 if frame<=144 else 8 if frame<=146 else 6 if frame<=148 else 5 if frame<=149 else 4 if frame<=150 else 3 if frame<=152 else 2 if frame<=154 else 1
    else:
        level=sum(frame>=start for start in (4,6,8,11,12,16,20,25))
    lines=[((157,0),(157,639)),((203,0),(203,639)),
           ((0,294),(359,294)),((0,346),(359,346))]
    for start,end in lines[:min(level,4)]:
        cv2.line(img,start,end,(35,)*3,1,cv2.LINE_AA)
    if level>=5:
        cv2.line(img,(157,320),(203,320),(31,)*3,1)
        cv2.line(img,(180,298),(180,342),(31,)*3,1)
        guides=flat()
        mark(guides,(28,)*3)
        dx=np.maximum(0,np.max(guides,axis=2))
        contour=(dx>8).astype('uint8')
        border=cv2.morphologyEx(contour,cv2.MORPH_GRADIENT,np.ones((2,2),'uint8'))
        img[border>0]=31
    if level>=6:
        cv2.ellipse(img,CENTER,(12,19),0,0,360,(26,)*3,1)
    if level>=7:
        for dx in (-8,8):
            cv2.line(img,(180+dx,299),(180+dx,341),(29,)*3,1)
    if level>=8:
        mark(img,(231,)*3)
    return img


def white():
    img=flat(255)
    mask=flat()
    mark(mask,(255,)*3,scale=9.8)
    veil=cv2.GaussianBlur(mask[:,:,0],(0,0),6)
    falloff=np.clip((Y-360)/370,0,.8)
    img-=((mask[:,:,0]*(1-falloff)+veil*falloff)*.108)[...,None]
    mark(img,(7,)*3)
    return img


def black():
    img=flat()
    mark(img,(249,)*3,registered=True)
    return img


def aura():
    fog=gauss(17,15,111,118)+gauss(319,632,176,98)
    img=np.stack((51*fog,70*fog,72*fog),axis=-1)
    mark(img,(249,)*3,registered=True)
    return img


def metal_mark(img,position=CENTER,size=1):
    x,y=position
    ang=np.linspace(0,2*np.pi,16,endpoint=False)
    profile=np.stack((np.cos(ang),np.sin(ang)),axis=1)
    # band_mesh projects in quarter-size units.
    band=band_mesh((x/2,y/2,11.9*size,10.12*size,89),1.45*size,1.8*size,0,
                   (0,2*np.pi),profile=profile)
    hi=cv2.resize(img,(720,1280))
    original=hi.copy()
    paint_bands(hi,[band],albedo=(111,112,116),edge=(231,229,219),bloom=(2,2,2))
    ridge=hi-original
    yy,xx=np.indices(hi.shape[:2])
    env=.68+.42*np.sin((xx-y*.13)*.052)+.28*np.cos(yy*.091+xx*.026)
    weight=np.clip(np.max(np.abs(ridge),axis=2)/59,0,1)
    hi=hi*(1-weight[...,None])+np.clip(hi*env[...,None],0,255)*weight[...,None]
    img[:]=cv2.resize(hi,(W,H),interpolation=cv2.INTER_AREA)


def chrome():
    img=flat(255)
    mix(img, (np.array([139,136,141])),(100*gauss(180,342,21,13)).astype('uint8'))
    metal_mark(img)
    small_legend(img,(10,)*3)
    return img


def palette():
    img=flat()
    rounded(img,(72,-100,510,432),75,(131,)*3)
    rounded(img,(84,-110,510,420),63,(193,)*3)
    rounded(img,(118,253,485,385),27,(241,)*3)
    for x,color in [(134,(13,)*3),(244,(126,)*3),(353,(239,75,71))]:
        rounded(img,(x,274,x+93,367),16,color)
    mark(img,(252,)*3)
    return img


def stone():
    img=flat()
    angles=np.linspace(0,2*np.pi,102,endpoint=False)
    edge=1+.045*np.sin(angles*13)+.08*np.cos(angles*4+.4)+.12*np.sin(angles*2+.4)
    points=np.stack((180+86*edge*np.cos(angles)-10*np.sin(angles),
                     320+92*edge*np.sin(angles)-7*np.cos(angles)),axis=1)
    shape=poly(points)
    dist=cv2.distanceTransform(shape,cv2.DIST_L2,5)
    dx,dy=(X-180)/90,(Y-320)/100
    noise=FRACTAL*.76+.05*GRAIN
    hx=cv2.Sobel(dist*.17+noise,cv2.CV_32F,1,0)
    hy=cv2.Sobel(dist*.17+noise,cv2.CV_32F,0,1)
    gray=(67-25*dy-17*dx+57*noise+np.clip(16*hx+19*hy,-49,57)
          +31*np.exp(-dist/5)*np.clip(-dx-dy,.04,1.4))
    markgray=flat()
    mark(markgray,(255,)*3)
    ident=markgray[:,:,0]/255
    bevel=np.roll(ident,1,axis=1)-ident
    gray=gray*(1-ident*.62)+bevel*32-8*ident
    mix(img,rgb(gray),shape)
    small_legend(img,(214,)*3)
    return img


def apply_asset(canvas, asset, left, top):
    width=min(asset.shape[1], W-left)
    height=min(asset.shape[0], H-top)
    if width<=0 or height<=0:
        return
    pixels=asset[:height,:width]
    alpha=pixels[:,:,3,None].astype('float32')/255
    target=canvas[top:top+height,left:left+width]
    target[:]=target*(1-alpha)+pixels[:,:,:3]*alpha


def board():
    img=flat(255)
    rounded(img,(73,126,521,725),49,(128,)*3)
    rounded(img,(88,141,512,722),37,(217,)*3)
    for cx in [115,159,207,222,236,262,284,319,341]:
        cv2.line(img,(cx,146),(cx,639),(210,)*3,1)
    for cy in (270,280,295,341,359):
        cv2.line(img,(90,cy),(359,cy),(209,)*3,1)
    if WORDMARK is None:
        text(img,[(157,279,'origins of',68,(35,42,47),TEXT_FONT)])
    else:
        apply_asset(img,WORDMARK,157,276)
    text(img,[(157,428,'Origins Of is a home\nfragrance brand built around\na waterless fragrance\ndiffuser. The diffuser uses no\nwater and no heat. It\natomises pure fragrance oil\nat a steady rate, so the scent\nin a room stays level from\nmorning to night.',15,(80,)*3,TEXT_FONT)])
    return img


def card(back):
    img=flat()
    rounded(img,(0,0,179,116),2,(52,)*3)
    rounded(img,(3,3,176,113),2,(19,)*3)
    if back:
        mark(img,(101,)*3,(89,59),.91)
    else:
        text(img,[(11,13,'ORIGINS OF\nIDENTITY STUDY',6,(163,)*3,MONO),
                  (102,12,'origins of',12,(215,)*3,FONT),
                  (11,70,'EMAIL\nPHONE\nWEBSITE',5,(173,)*3,MONO),
                  (90,70,'ORIGINS OF\nFRAGRANCE\nSTUDIO',5,(139,)*3,MONO)])
        for y in (66,78,87,97):
            cv2.line(img,(9,y),(169,y),(56,)*3,1)
    return img[:117,:180].astype('uint8')


def cards():
    img=flat()
    front,back=card(False),card(True)
    for x,y,angle,isback in [
        (317,42,-10,False),(65,183,19,True),(205,144,13,True),(218,237,25,False),
        (36,405,-11,False),(180,320,0,True),(210,441,0,False),(342,548,21,False),
        (193,577,18,True),(68,608,16,False),(318,352,17,True)]:
        mat=cv2.getRotationMatrix2D((90,58),angle,1)
        mat[:,2]+=[x-90,y-58]
        pixels=cv2.warpAffine(back if isback else front,mat,(W,H))
        opacity=cv2.warpAffine(np.full((117,180),255,'uint8'),mat,(W,H))
        shadow=cv2.GaussianBlur(opacity,(0,0),6)*.45
        mix(img,(2,2,2),shadow)
        mix(img,pixels,opacity)
    return img


def keychain():
    gray=(127+19*gauss(53,62,330,340)-56*gauss(193,347,56,88)
          -12*gauss(331,560,165,181)+1.35*GRAIN+.8*SMOOTH)
    img=rgb(gray)
    cv2.circle(img,(180,207),18,(190,)*3,1,cv2.LINE_AA)
    cv2.ellipse(img,(180,207),(17,17),-13,-140,45,(224,)*3,1,cv2.LINE_AA)
    for i in range(9):
        cy=229+i*6
        cv2.ellipse(img,(180+(i%2)*2,cy),(3,5),(-1)**i*22,0,360,(161,)*3,1,cv2.LINE_AA)
    metal_mark(img)
    text(img,[(59,312,'FUNCTIONAL',5,(222,)*3,MONO),
              (258,312,'FRAGRANCES',5,(222,)*3,MONO),
              (159,408,'ORIGINS OF\nKEYCHAIN',5,(222,)*3,MONO)])
    return img


def bottle():
    img=flat()
    tilt=-.30
    angle=np.arctan(tilt)
    u=(X-210)*np.cos(angle)+(Y-310)*np.sin(angle)
    v=-(X-210)*np.sin(angle)+(Y-310)*np.cos(angle)
    drum=(u>-50)&(np.abs(v)<145)
    value=(21+120*np.exp(-((v+111)/26)**2)+99*np.exp(-((v-110)/34)**2)
           +46*np.exp(-((v-77)/22)**2)+15*np.exp(-((v+142)/5)**2))
    img[drum]=rgb(value)[drum]
    lip=((u+51)/16)**2+(v/145)**2
    seam=(lip>.91)&(lip<1.08)
    img[seam]=rgb(value*.62+25)[seam]
    neck=(u>-99)&(u<=-50)&(np.abs(v)<72)
    knurl=(.5+.5*np.cos(u*1.85+v*1.4))*(.5+.5*np.cos(u*1.8-v*1.4))
    neck_gray=(25+105*np.exp(-((v-34)/23)**2)+73*np.exp(-((v+33)/12)**2))*(.71+.38*knurl)
    img[neck]=rgb(neck_gray)[neck]
    for dx,width in [(-107,12),(-112,8)]:
        hollow=((u-dx)/width)**2+(v/95)**2
        mask=(hollow>.60)&(hollow<1.04)
        img[mask]=rgb(15+144*np.exp(-((v-37)/29)**2)+117*np.exp(-((v+69)/10)**2))[mask]
    stamp(img,LOGO['mark'],(214,)*3)
    return img


def social():
    gray=(155-32*(Y/H)+32*gauss(42,148,186,182))
    img=rgb(gray)
    edge=X-(290-.67*(Y-141)+.0011*(Y-305)**2)
    img+=(-94*np.exp(-((edge+28)/23)**2)+95*np.exp(-((edge-4)/11)**2)
          -45*np.exp(-((edge-17)/14)**2)+26*np.exp(-((edge-33)/8)**2))[...,None]
    rounded(img,(102,261,516,727),52,(100,)*3)
    rounded(img,(111,270,513,721),42,(3,)*3)
    cv2.circle(img,(180,320),42,(246,)*3,-1,cv2.LINE_AA)
    mark(img,(6,)*3)
    text(img,[(255,279,'Origins_of_',13,(245,)*3,FONT),
              (225,323,'Origins of',15,(240,)*3,FONT),
              (226,353,'100       10',13,(252,)*3,FONT),
              (226,369,'Posts       Following',7,(160,)*3,FONT),
              (125,401,'Origins of',13,(245,)*3,FONT),
              (125,420,'Retail Company',9,(180,)*3,FONT),
              (125,438,'Elevate your homes and offices with\nfragrances for a sensory experience.',10,(233,)*3,FONT),
              (125,474,'www.originsof.com',10,(76,135,233),FONT)])
    for left,right in [(125,222),(234,336)]:
        rounded(img,(left,502,right,530),8,(77,)*3)
        rounded(img,(left+1,503,right-1,529),7,(4,)*3)
    text(img,[(149,511,'Following',8,(235,)*3,FONT),(267,511,'Message',8,(235,)*3,FONT)])
    for i in range(3):
        x0=122+i*84
        thumb=gauss(x0+36,591,27,52)*np.exp(-((Y-578)/139)**2)
        swatch=(thumb[...,None]*np.array([118,66,38])+np.array([13,14,15]))
        img[550:640,x0:x0+79]=swatch[550:640,x0:x0+79]
    return img


def folder():
    img=rgb(14+10*gauss(293,255,140,189)+.9*GRAIN)
    outline=poly([(-20,225),(81,225),(102,218),(111,197),(120,194),
                  (226,194),(239,201),(241,211),(241,551),(-20,551)])
    mix(img,rgb(64+18*gauss(145,220,140,148)+2*FRACTAL+GRAIN),outline)
    rim=outline-cv2.erode(outline,np.ones((3,3),'uint8'))
    img[rim>130]+=28
    rounded(img,(-30,254,239,552),11,(7,)*3)
    rounded(img,(-30,254,236,549),11,(30,)*3)
    pattern=poly([(-25,264),(235,264),(235,538),(-25,540)])
    mix(img,rgb(27+8*gauss(38,282,173,100)+3*FRACTAL+.55*GRAIN),pattern)
    mark(img,(226,)*3)
    return img


def cap():
    img=rgb(151+31*gauss(100,106,270,200)+2*SMOOTH+GRAIN)
    if CAP_PLATE is not None:
        apply_asset(img,CAP_PLATE,0,0)
        if not CAP_HAS_LOGO:
            mark(img,(240,)*3)
        return img
    perimeter=[(-5,319),(25,205),(87,137),(161,119),(221,128),(268,155),(324,209),(357,315),
               (354,382),(315,470),(286,515),(236,528),(127,528),(67,503),(32,444),(10,399),(-5,319)]
    spline=CubicSpline(np.arange(len(perimeter)),perimeter,bc_type='periodic')
    mask=poly(spline(np.linspace(0,len(perimeter)-1,130)))
    lt=gauss(134,279,163,193)
    stripe=.9*np.sin((X-Y*.7)*2.1)+.7*np.sin((X+Y*.38)*1.9)
    gray=57+84*lt+8*FRACTAL+2.5*GRAIN+stripe
    # Directional seams and crown panels.
    for side in (-1,1):
        d=X-(179+side*(.004*(Y-126)**2+1))
        gray-=13*np.exp(-(d/2.7)**2)*(Y<400)*(Y>120)
        gray+=7*np.exp(-((d-side*4)/2)**2)*(Y<401)*(Y>121)
        dd=X-(180+side*(1.08*(Y-124)-.0023*(Y-124)**2))
        gray-=11*np.exp(-(dd/2.5)**2)*(Y<340)*(Y>123)
    visor=370+40*np.exp(-((X-178)/129)**2)
    gray+=np.where(Y>visor,7+12*gauss(139,458,124,109),0)
    gray-=22*np.exp(-((Y-visor)/3.6)**2)
    for inset in range(1,5):
        seam=(Y-visor-inset*8)
        gray-=2*np.exp(-(seam/1.25)**2)
    mix(img,rgb(gray),mask)
    for center in [(127,267),(228,267)]:
        cv2.ellipse(img,center,(5,7),0,0,360,(92,)*3,2,cv2.LINE_AA)
    mark(img,(240,)*3)
    return img


def liquid():
    top=296+20*np.sin(X/59)+8*np.sin(X/22+.9)
    bottom=329+21*np.sin(X/63-.9)+6*np.sin(X/31)
    decay=np.clip(1-(Y-top)/298,0,1)
    light=decay**1.9*(Y>top)+.14*np.exp(-((Y-top)/7)**2)
    img=light[...,None]*np.array([225,76,10],dtype='float32')
    for phase,shift in [(0,0),(1.9,7),(3.3,14)]:
        warp=top+shift+8*np.sin(X/28+phase)
        ridge=np.exp(-((Y-warp)/2.8)**2)
        img+=ridge[...,None]*np.array([93,65,43])
    body=np.exp(-((Y-bottom)/5.5)**2)
    img*=1-(.95*body)[...,None]
    img+=np.exp(-((Y-bottom-5)/2.4)**2)[...,None]*np.array([99,40,10])
    mark(img,(111,206,247))
    small_legend(img,(218,)*3)
    return img
