"""Straight, curved and tracked text or RGBA artwork for anchor compositing."""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont, features

SIZE = 192


@lru_cache(maxsize=12)
def load_face(font_path, weight):
    if not features.check_feature('raqm'):
        raise ValueError('Use Pillow com RAQM/HarfBuzz para renderizar o texto.')
    face = ImageFont.truetype(font_path, SIZE, layout_engine=ImageFont.Layout.RAQM)
    with TTFont(font_path, lazy=True) as font:
        if 'fvar' in font:
            face.set_variation_by_axes([
                max(axis.minValue, min(weight, axis.maxValue))
                if axis.axisTag == 'wght' else axis.defaultValue
                for axis in font['fvar'].axes
            ])
    return face


def ink(font, text):
    left, top, right, bottom = font.getbbox(text, anchor='ls')
    image = Image.new('L', (max(1, right-left), max(1, bottom-top)))
    ImageDraw.Draw(image).text((-left,-top), text, font=font, fill=255, anchor='ls')
    return image


def graphemes(text):
    # Treat Portuguese combining marks as part of their base character.
    import unicodedata
    clusters = []
    for letter in text:
        if clusters and unicodedata.combining(letter):
            clusters[-1] += letter
        else:
            clusters.append(letter)
    return clusters


def stamping(target, mask, x, y, height, angle, width=None, fit_rotated=False):
    if not mask.getbbox():
        return
    width = width or height*mask.width/max(mask.height,1)
    size=(max(1,round(width)),max(1,round(height)))
    if fit_rotated:
        scaled=mask.rotate(-angle,expand=True,resample=Image.Resampling.BICUBIC)
        bounds=scaled.getbbox()
        if bounds:
            mask=scaled.crop(bounds).resize(size,Image.Resampling.LANCZOS)
    else:
        mask=mask.resize(size,Image.Resampling.LANCZOS)
        mask=mask.rotate(-angle,expand=True,resample=Image.Resampling.BICUBIC)
    target.paste(255, (round(x-mask.width/2), round(y-mask.height/2)), mask)


def curved_mask(size, font, text, arc, poses=None):
    w,h = size
    canvas = Image.new('L', size)
    letters = graphemes(text)
    visible = [letter for letter in letters if not letter.isspace()]
    if poses is not None:
        positions=[]
        run=''
        for character in letters:
            run+=character
            if not character.isspace():
                positions.append(font.getlength(run)-font.getlength(character)/2)
        if len(positions)>1:
            positions=(np.asarray(positions)-positions[0])/max(positions[-1]-positions[0],1.)
        else:
            positions=[.5]
        values = resample_glyphs(poses,len(visible),positions)
        for letter,(x,y,width,height,rotation) in zip(visible,values):
            stamping(canvas, ink(font,letter), x*w, y*h, height*h, rotation, width=width*w,fit_rotated=True)
        return canvas
    width = max(1.,font.getlength(text))
    factor = min(w*.93/width,h*.54/SIZE)
    left,top,right,bottom = font.getbbox(text,anchor='ls')
    prefix = ''
    baseline = h*.46-(top+bottom)*factor/2
    for letter in letters:
        prefix += letter
        if letter.isspace():
            continue
        a,b,c,d = font.getbbox(letter,anchor='ls')
        advance = font.getlength(prefix)-font.getlength(letter)
        local_x = ((advance+(a+c)/2)-width/2)*factor
        t = local_x/max(width*factor/2,1.)
        elevation = arc*h*t*t
        slope = 4*arc*h*t/max(width*factor,1.)
        stamping(canvas,ink(font,letter),w/2+local_x,baseline+(b+d)/2*factor+elevation,
                 (d-b)*factor,np.degrees(np.arctan(slope)),width=(c-a)*factor)
    return canvas


def resample_glyphs(poses, count, positions=None):
    source = np.asarray(poses, dtype='float64')
    if source.ndim != 2 or source.shape[1] != 5 or len(source) < 2 or not np.isfinite(source).all():
        raise ValueError('Cada amostra de letra precisa de x, y, largura, altura e rotação.')
    if count < 1:
        return np.empty((0, 5))
    original = np.linspace(0,1,len(source))
    target = (positions if positions is not None and count!=len(source) else
              np.linspace(0,1,count) if count>1 else [.5])
    result = np.array([np.interp(target,original,source[:,col]) for col in range(5)]).T
    result[:,2] *= min(1.,len(source)/count)
    return result


def make_art(effect, size, font_path, color, asset_root, poses=None, profile_aspect=None):
    if 'asset' in effect:
        with Image.open(asset_root/effect['asset']) as media:
            rgba = media.convert('RGBA')
        if effect.get('fit_asset'):
            scale = min(size[0] / rgba.width, size[1] / rgba.height)
            rgba = rgba.resize((max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))),
                               Image.Resampling.LANCZOS)
        else:
            rgba.thumbnail(size, Image.Resampling.LANCZOS)
        image = Image.new('RGBA',size)
        image.alpha_composite(rgba, ((size[0]-rgba.width)//2,(size[1]-rgba.height)//2))
        return np.asarray(image)
    font = load_face(str(font_path), float(effect.get('weight',800)))
    text = effect['text'].strip()
    arc = float(effect.get('arc',0))
    if poses is not None and profile_aspect:
        content_size=(max(2,min(size[0],round(size[1]*profile_aspect))),
                      max(2,min(size[1],round(size[0]/profile_aspect))))
        profile=curved_mask(content_size,font,text,arc,poses)
        alpha=Image.new('L',size)
        alpha.paste(profile,((size[0]-profile.width)//2,(size[1]-profile.height)//2))
    elif arc or poses is not None:
        alpha = curved_mask(size,font,text,arc,poses)
    else:
        word = ink(font,text)
        factor = min(size[0]*.94/word.width,size[1]*.83/word.height)
        fit = word.resize((max(1,round(word.width*factor)),max(1,round(word.height*factor))),
                          Image.Resampling.LANCZOS)
        alpha = Image.new('L',size)
        alpha.paste(fit,((size[0]-fit.width)//2,(size[1]-fit.height)//2))
    if effect.get('outline',True):
        edge = cv2.dilate(np.asarray(alpha),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5)))
        outline = (13,16,20) if np.mean(color)>125 else (246,247,243)
        image = Image.new('RGBA',size,(*outline,0))
        image.putalpha(Image.fromarray(edge))
    else:
        image = Image.new('RGBA',size)
    fg = Image.new('RGBA',size,(*color,255))
    fg.putalpha(alpha)
    image.alpha_composite(fg)
    return np.asarray(image)


def motion(corners, phase, style, fit_inside=False):
    corners = np.asarray(corners,dtype='float32')
    progress = min(1., max(0., phase))
    ease = 1-(1-progress)**3
    alpha = 1.
    if style == 'fade':
        alpha = ease
    elif style == 'slide':
        down = (corners[3]-corners[0])*(.27 if fit_inside else .55)*(1-ease)
        corners = corners+down
        alpha = ease
    elif style == 'pop':
        scale = .76+.24*ease+.09*np.sin(np.pi*progress)**2
        center = corners.mean(axis=0)
        corners = (corners-center)*scale+center
        alpha = ease
    return corners,float(alpha)


def warp_rgba_patch(art, corners, resolution):
    """Return the exact premultiplied BGRA patch used by composition and QC."""
    w,h = resolution
    dst = (np.asarray(corners,dtype='float32')*[w,h]).astype('float32')
    # Limit warping and blending to the visible footprint.
    xy_min=np.maximum(0,np.floor(dst.min(axis=0)).astype(int))
    xy_max=np.minimum([w,h],np.ceil(dst.max(axis=0)).astype(int)+1)
    x,y=xy_min
    width,height=xy_max-xy_min
    if width<1 or height<1:
        return None
    ah,aw=art.shape[:2]
    src=np.float32([[0,0],[aw-1,0],[aw-1,ah-1],[0,ah-1]])
    matrix=cv2.getPerspectiveTransform(src,(dst-xy_min).astype('float32'))
    bgra=art[:,:,[2,1,0,3]].astype('float32')/255
    bgra[:,:,:3]*=bgra[:,:,3,None]
    patch=cv2.warpPerspective(bgra,matrix,(int(width),int(height)),flags=cv2.INTER_LINEAR)
    return int(x),int(y),patch


def composite_shutter(frame, art, samples, opacity=1., occlusion=None):
    """Average premultiplied exposure taps before compositing onto the plate."""
    if opacity <= 0:
        return
    patches = [warp_rgba_patch(art, corners, frame.shape[1::-1]) for corners in samples]
    visible = [patch for patch in patches if patch is not None]
    if not visible:
        return
    x0, y0 = min(p[0] for p in visible), min(p[1] for p in visible)
    x1 = max(x + patch.shape[1] for x, y, patch in visible)
    y1 = max(y + patch.shape[0] for x, y, patch in visible)
    exposure = np.zeros((y1-y0, x1-x0, 4), dtype=np.float32)
    for x, y, patch in visible:
        height, width = patch.shape[:2]
        exposure[y-y0:y-y0+height, x-x0:x-x0+width] += patch / len(samples)
    _blend_patch(frame, x0, y0, exposure, opacity, occlusion)


def composite(frame, art, corners, opacity=1., occlusion=None):
    if opacity<=0:
        return
    warped=warp_rgba_patch(art,corners,frame.shape[1::-1])
    if warped is None:
        return
    _blend_patch(frame, *warped, opacity, occlusion)


def _blend_patch(frame, x, y, patch, opacity, occlusion):
    height,width=patch.shape[:2]
    gain=opacity
    if occlusion is not None:
        gain=opacity*(1-occlusion[y:y+height,x:x+width,None].astype('float32')/255)
    base=frame[y:y+height,x:x+width]
    base[:]=np.clip(base*(1-patch[:,:,3,None]*gain)+patch[:,:,:3]*gain*255.,0,255).astype('uint8')
