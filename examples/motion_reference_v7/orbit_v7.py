"""Reference adaptation: cylinder-mapped belt, separate front/back alpha passes."""
from pathlib import Path
import math
from PIL import Image,ImageFilter
import arte as a
from opening_assets_v6 import people_layer
from visual_fidelity.orbit_type import OrbitSpec,render_orbit_type,composite_orbit

ROOT=Path(__file__).parent
FONT=ROOT/'fonts/Anton.ttf'

def render_orbit(frame,ev):
    background=a.spatial_asset('room_cream.png').copy()
    background.alpha_composite(people_layer(frame))
    subject=Image.new('RGBA',(720,1280))
    entry=a.progress(frame,104,7)
    a.put(subject,a.chair(),370-40*(1-entry),765,.91,alpha=entry)
    p=a.progress(frame,ev.get('faixa',108),5)
    if not p:
        background.alpha_composite(subject)
        return background
    spec=OrbitSpec(center=(355,680),radius_x=410,radius_z=320,camera_distance=1450,
                   tilt_deg=-17+2*math.sin((frame-108)/20),pitch_deg=7,
                   phase=.90+(frame-154)*.006,font_size=195,gap=130,repeats=4,
                   thickness=6,highlight_phase=.48-.018*(frame-108))
    rear,front=render_orbit_type('2kun',FONT,spec)
    if p<1:
        for im in (rear,front):im.putalpha(im.getchannel('A').point(lambda v:round(v*p)))
    return composite_orbit(background,subject,rear,front)
