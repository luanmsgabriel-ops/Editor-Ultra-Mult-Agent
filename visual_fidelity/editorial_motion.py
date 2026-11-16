"""Narrative motion treatments for adaptive templates on a new source plate."""

from functools import lru_cache
import math
from pathlib import Path
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .anchor_graphics import composite
from .context_art import draw_icon, fit_font

SCREEN_EFFECTS = {'kinetic_type', 'signature'}
CUTAWAYS = {'signal', 'clock', 'metric', 'location', 'status'}
EFFECTS = SCREEN_EFFECTS | CUTAWAYS
CANVAS = (540, 960)


def treatment(cue):
    visual = cue.get('editorial')
    if visual:
        if visual not in EFFECTS:
            raise ValueError(f'Unknown editorial treatment: {visual}')
        return visual
    if cue.get('gesture'):
        return 'signature'
    if cue['treatment'] == 'metric' and re.match(r'^\d+\b', cue['title']):
        return 'metric'
    return {'signal':'signal', 'clock':'clock', 'pin':'location', 'status':'status'}.get(
        cue.get('icon'), 'kinetic_type',
    )


def smooth(value):
    p = min(1., max(0., value))
    return p*p*(3-2*p)


@lru_cache(maxsize=16)
def lettering(value, font, size, width, color):
    face = fit_font(font, value, width, size)
    left, top, right, bottom = face.getbbox(value)
    ink = Image.new('RGBA', (right-left+8, bottom-top+8))
    ImageDraw.Draw(ink).text((4-left,4-top),value,font=face,fill=color)
    return ink


def title_parts(cue, style, condensed, script):
    paper, red = tuple(style['paper']), tuple(style['ink'])
    return (
        lettering(cue['title'], str(condensed), 137, 824, red),
        lettering(cue['script'], str(script), 105, 530, paper) if cue.get('script') else None,
    )


def kinetic_frame(parts, progress, duration, signature=False):
    """Animate outline, display type and script separately on transparent film."""
    art = Image.new('RGBA',(900,210))
    title, script = parts
    phase = smooth(progress/.28)
    exit_fade = smooth((duration-progress)/.21)
    reveal = round(title.width*smooth((progress+.04)/.22))
    title = title.copy()
    alpha = title.getchannel('A')
    alpha.paste(0, (reveal,0,title.width,title.height))
    glyph = title.copy()
    glyph.putalpha(alpha)
    border = Image.new('RGBA',title.size,(255,249,234))
    border.putalpha(alpha.filter(ImageFilter.MaxFilter(7)))
    x = (900-title.width)//2
    y = min(210-title.height-3,round((210-title.height)/2 + (22 if script else 0) + 27*(1-phase)))
    art.alpha_composite(border,(x,y))
    art.alpha_composite(glyph,(x,y))
    if script:
        cap = script.copy()
        cap.putalpha(cap.getchannel('A').point(lambda v:round(v*smooth((progress-.04)/.25))))
        for dx,dy in [(0,2),(2,2)]:
            dark=Image.new('RGBA',cap.size,(86,31,27));dark.putalpha(cap.getchannel('A'))
            art.alpha_composite(dark,((900-cap.width)//2+dx,4+dy))
        art.alpha_composite(cap,((900-cap.width)//2,4))
    if signature:
        length = int(660*smooth((progress-.12)/.38))
        ImageDraw.Draw(art).line((120,203,120+length,203),fill=(255,238,205,255),width=4)
    if exit_fade<1:
        art.putalpha(art.getchannel('A').point(lambda v:round(v*exit_fade)))
    return np.asarray(art)


@lru_cache(maxsize=12)
def plate(red, paper, dark):
    w,h=CANVAS
    y,x=np.ogrid[:h,:w]
    if dark:
        spotlight=np.exp(-((x-w*.56)/(w*.62))**2-((y-h*.49)/(h*.52))**2)
        pixels=np.array([31.,5,10.])+np.array([123.,15,27.])*spotlight[...,None]
    else:
        gradient=(x/w*.55+y/h*.45)[...,None]
        pixels=np.array(paper)*(1.-gradient*.10)+np.array(red)*gradient*.10
    image=Image.fromarray(np.uint8(np.clip(pixels,0,255))).convert('RGBA')
    draw=ImageDraw.Draw(image)
    muted=(138,40,48) if dark else (228,181,172)
    for i in range(5):
        draw.line((45,180+i*151,495,180+i*151),fill=muted,width=1)
    for i in range(5):
        draw.line((44+i*113,180,44+i*113,784),fill=muted,width=1)
    return image


def center(art, stamp, x, y):
    art.alpha_composite(stamp,(round(x-stamp.width/2),round(y-stamp.height/2)))


def caption(art, value, font, size, y, ink, width=447):
    center(art,lettering(value,font,size,width,ink),270,y)


def disk(art, phase, color, ink):
    """Layered graphic emblem. Depth here is drawn, independent of the source camera."""
    d=ImageDraw.Draw(art)
    offset=round(21*(1-phase))
    for i in range(18,0,-1):
        d.ellipse((141,339+i+offset,399,597+i+offset),fill=(80+i*2,10,27),outline=ink,width=1)
    d.ellipse((141,339+offset,399,597+offset),fill=color,outline=ink,width=3)
    return 468+offset


def cutaway_frame(cue, visual, style, condensed, script, elapsed):
    w,h=CANVAS
    paper,red = (tuple(style[k]) for k in ('paper','ink'))
    dark=visual in {'signal','location'}
    ink=paper if dark else red
    art=plate(red,paper,dark).copy()
    d=ImageDraw.Draw(art)
    p=smooth(elapsed/.36)
    caption(art,cue['script'] or {'metric':'Em números','signal':'No controle aéreo','status':'Acompanhe','location':'O impacto','clock':'Tempo de espera'}[visual],
            script,78,224,ink)
    if visual=='metric':
        m=re.match(r'^(\d+)\s*(.*)',cue['title'])
        number,label=m.groups() if m else ('',cue['title'])
        d.polygon((48,593,469,593,485,609,63,609),fill=(109,20,33))
        d.rounded_rectangle((48,348,469,593),20,fill=paper,outline=red,width=2)
        d.line((76,575,443,575),fill=red,width=1)
        if number:
            caption(art,number,condensed,230,489+32*(1-p),red,370)
        caption(art,label,condensed,68,686+20*(1-p),red)
    elif visual in {'signal','clock','location'}:
        y=disk(art,p,red,paper)
        if visual=='signal':
            for i in range(3):
                radius=45+29*i+round(12*(elapsed%1))
                d.arc((270-radius,y-radius,270+radius,y+radius),215,325,fill=paper,width=5)
            d.ellipse((263,y-6,277,y+8),fill=paper)
            d.line((270,y+8,270,y+69),fill=paper,width=6)
        elif visual=='clock':
            for i in range(12):
                a=i*math.tau/12
                d.line((270+96*math.sin(a),y-96*math.cos(a),270+106*math.sin(a),y-106*math.cos(a)),fill=paper,width=3)
            a=-.5+min(1.8,elapsed)*1.6
            d.line((270,y-49,270,y,270+81*math.sin(a),y-81*math.cos(a)),fill=paper,width=7,joint='curve')
            d.ellipse((264,y-6,276,y+6),fill=paper)
        else:
            # A diagram of reach, without inventing a path or geographic coordinates.
            for i in range(3):
                radius=129+17*i+round(11*math.sin(elapsed*3+i))
                d.ellipse((270-radius,y-radius,270+radius,y+radius),outline=(210,82,83),width=2)
            icon=draw_icon('pin',red,paper).resize((157,157),Image.Resampling.LANCZOS)
            center(art,icon,270,y)
        caption(art,cue['title'],condensed,81,692+20*(1-p),ink)
    else:
        # A departure/status board assembles row by row instead of a badge on the speaker.
        d.rounded_rectangle((57,347,483,601),24,fill=(61,16,24),outline=red,width=3)
        for i,(label,value) in enumerate((('VOO','•••'),('HORÁRIO','––:––'),('STATUS','CONSULTE'))):
            if elapsed+.08 < i*.15:
                break
            y=397+i*72
            d.line((81,y+29,459,y+29),fill=(156,56,66),width=1)
            art.alpha_composite(lettering(label,condensed,27,148,paper),(89,y-13))
            value=lettering(value,condensed,29,154,paper)
            art.alpha_composite(value,(449-value.width,y-13))
        caption(art,cue['title'],condensed,82,693+18*(1-p),red)
    d=ImageDraw.Draw(art)
    d.rounded_rectangle((79,823,461,828),2,fill=(156,51,55) if dark else (219,166,153))
    d.rounded_rectangle((79,823,79+int(382*smooth(elapsed/2.3)),828),2,fill=ink)
    return cv2.cvtColor(np.asarray(art),cv2.COLOR_RGBA2BGR)


def diagonal_wipe(frame, graphic, progress, entering):
    """Reveal a separate visual shot without compositing a relocated speaker."""
    h,w=frame.shape[:2]
    inset=(1-smooth(progress))*1.27
    # The angular edge mirrors the Clara palette; full coverage at progress 1.
    edge=(np.linspace(0.,.27,h)+inset-.27)
    for i,fraction in enumerate(edge):
        x=max(0,min(w,round(w*fraction)))
        if entering:
            frame[i,x:]=graphic[i,x:]
        else:
            frame[i,:w-x]=graphic[i,:w-x]


def composite_editorial(frame, layer, index, root, cache, fps):
    """Render the compiled editorial scene on the same frame clock as the source."""
    spec=layer.effect['editorial_scene']
    visual=spec['kind']
    elapsed=(index-layer.first)/fps
    duration=(layer.last-layer.first)/fps
    cue=spec['cue']
    if visual in SCREEN_EFFECTS:
        key=('lettering',layer.effect['id'])
        if key not in cache:
            cache[key]=title_parts(cue,spec['style'],spec['condensed'],spec['script'])
        art=kinetic_frame(cache[key],elapsed,duration,visual=='signature')
        composite(frame,art,layer.corners[index])
        return
    graphic=cv2.resize(cutaway_frame(cue,visual,spec['style'],spec['condensed'],spec['script'],elapsed),
                       frame.shape[1::-1],interpolation=cv2.INTER_LINEAR)
    fade=min(.25,duration*.22)
    if elapsed<fade:
        diagonal_wipe(frame,graphic,(elapsed+1/fps)/fade,True)
    elif duration-elapsed<=fade:
        diagonal_wipe(frame,graphic,(duration-elapsed-1/fps)/fade,False)
    else:
        frame[:]=graphic
