"""Editable graphic assets for the source-aware template renderer."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ICON_KINDS = {'plane', 'clock', 'signal', 'pin', 'cancel', 'check', 'status'}


def draw_icon(kind, color, ink):
    """Generate a transparent pictogram from the concept chosen by the planner."""
    if kind not in ICON_KINDS:
        raise ValueError(f'Unknown pictogram: {kind}')
    icon = Image.new('RGBA', (192, 192))
    d = ImageDraw.Draw(icon)
    d.rounded_rectangle((6, 6, 185, 185), 45, fill=color)
    if kind == 'plane':
        path = [(96,40),(106,54),(106,76),(145,103),(145,114),(106,101),
                (106,130),(121,142),(121,150),(96,142),(71,150),(71,142),
                (86,130),(86,101),(47,114),(47,103),(86,76),(86,54)]
        d.polygon(path, fill=ink)
    elif kind == 'clock':
        d.ellipse((46,46,146,146), outline=ink, width=10)
        d.line((96,63,96,96,119,111), fill=ink, width=10, joint='curve')
    elif kind == 'signal':
        for r in (23, 43, 64):
            d.arc((96-r,105-r,96+r,105+r), 218, 322, fill=ink, width=7)
        d.ellipse((90,99,102,111), fill=ink)
        d.line((96,111,96,146), fill=ink, width=8)
    elif kind == 'pin':
        d.polygon([(61,95),(131,95),(96,145)], fill=ink)
        d.ellipse((58,44,134,120), fill=ink)
        d.ellipse((83,68,109,94), fill=color)
    elif kind == 'status':
        d.rounded_rectangle((40,53,152,139), 14, outline=ink, width=8)
        for y in (76, 96, 116):
            d.line((58,y,86,y), fill=ink, width=6)
            d.line((103,y,133,y), fill=ink, width=6)
    elif kind == 'cancel':
        d.line((65,65,127,127), fill=ink, width=11)
        d.line((127,65,65,127), fill=ink, width=11)
    else:
        d.line((54,99,83,128,139,66), fill=ink, width=12, joint='curve')
    return icon


def fit_font(path, text, width, size):
    font = ImageFont.truetype(str(path), size)
    if font.getlength(text) > width:
        font = ImageFont.truetype(str(path), max(10, int(size * width / font.getlength(text))))
    return font


def make_card(cue, style, condensed, script, root):
    """Use the template's palette and hierarchy for content tied to the new speech."""
    cream, accent = (tuple(style[k]) for k in ('paper', 'ink'))
    transparent = Image.new('RGBA', (900, 210))
    art = ImageDraw.Draw(transparent)
    treatment = cue.get('treatment','headline')
    ink, paper = (cream, accent) if treatment == 'alert' else (accent, cream)
    art.rounded_rectangle((5, 8, 895, 203), 27, fill=(*paper, 246), outline=(*ink, 235), width=3)
    if treatment == 'metric':
        art.line((35, 180, 865, 180), fill=ink, width=3)
    else:
        art.rounded_rectangle((25, 43, 34, 168), 4, fill=ink)
    icon = None
    if cue.get('icon'):
        icon = draw_icon(cue['icon'], ink, paper)
    elif cue.get('icon_asset'):
        with Image.open(Path(root) / cue['icon_asset']) as image:
            if 'A' not in image.getbands() or image.getchannel('A').getextrema()[0] == 255:
                raise ValueError('A custom icon must have a transparent alpha channel')
            icon = image.convert('RGBA')
    width = 688 if icon else 815
    center = 385 if icon else 450
    title = cue['title']
    cap = cue.get('script', '')
    if cap:
        face = fit_font(script, cap, width-14, 51)
        art.text((center, 52), cap, font=face, fill=ink, anchor='mm')
    face = fit_font(condensed, title, width, 90)
    art.text((center, 121 if cap else 106), title, font=face, fill=ink, anchor='mm')
    if icon:
        icon.thumbnail((135, 135), Image.Resampling.LANCZOS)
        transparent.alpha_composite(icon, (814-icon.width//2, 105-icon.height//2))
    return transparent
