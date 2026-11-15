"""Render a reconstructed identity montage from procedural assets and cue data."""
import argparse
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import cv2
import numpy as np
from PIL import Image, ImageColor
from scipy.io.wavfile import write
from scipy.signal import butter, sosfilt

from . import scenes
from .mark import extract

ROOT=Path(__file__).resolve().parent
RATE=48000


def audio(path, fps, total, cuts):
    rng=np.random.default_rng(329524)
    audio=np.zeros((round(total*RATE/fps),2),dtype='float64')

    def noise(count, low, high):
        source=rng.standard_normal(count)
        return sosfilt(butter(3,(low,high),fs=RATE,btype='bandpass',output='sos'),source)

    def add(seconds, wave, volume, pan=0):
        start=round(seconds*RATE)
        end=min(len(audio),start+len(wave))
        if end>start:
            audio[start:end]+=wave[:end-start,None]*np.sqrt((1+np.array([-pan,pan]))/2)*volume

    t=np.arange(len(audio))/RATE
    fade=np.minimum(1,t/.025)*np.minimum(1,(t[-1]-t)/.11)
    rumble=(np.sin(t*2*np.pi*49)+.37*np.sin(t*2*np.pi*96))*fade
    add(0,rumble,.014)
    # The first audible hit is anchored at the observed candidate, 10 ms before frame 33.
    for index,(frame,name) in enumerate(cuts[1:]):
        start=1.09 if frame==33 else frame/fps
        strong=index%2==0 or name in ('white','liquid','grid_out')
        time=np.arange(round(RATE*(.26 if strong else .10)))/RATE
        snap=noise(len(time),1600,9200)*np.exp(-time*(66 if strong else 111))
        wave=snap*.65
        if strong:
            phase=48*time+2.1*(1-np.exp(-33*time))
            wave+=.72*np.sin(2*np.pi*phase)*np.exp(-time*19)
        wave*=np.minimum(time/.0014,1)
        add(start,wave,.47 if strong else .26,(-1)**index*.24)

    for when in (.138,.295,.386,.527,.655,.825,4.845,4.970,5.08,5.19):
        time=np.arange(round(RATE*.045))/RATE
        tick=noise(len(time),1800,6400)*np.exp(-time*145)*np.minimum(time/.002,1)
        add(when,tick,.19,.2)
    audio*=fade[:,None]
    audio*=.78/max(.78,float(np.max(np.abs(audio))))
    write(path,RATE,np.rint(audio*32767).astype('int16'))


def render(destination, timeline, profile):
    scenes.LOGO=profile
    targets={name:getattr(scenes,name) for _,name in timeline['cuts']
             if name not in ('grid_in','grid_out')}
    stills={name:np.clip(draw(),0,255).astype('uint8') for name,draw in targets.items()}
    command=['ffmpeg','-hide_banner','-loglevel','error','-y',
             '-f','rawvideo','-pixel_format','rgb24','-framerate',str(timeline['fps']),
             '-video_size','720x1280','-i','-','-an','-c:v','libx264','-threads','3',
             '-preset','fast','-crf','15','-pix_fmt','yuv420p',str(destination)]
    with subprocess.Popen(command,stdin=subprocess.PIPE) as encoder:
        cuts=timeline['cuts']+[[timeline['frame_count'],'end']]
        for (first,scene),(last,_) in zip(cuts,cuts[1:]):
            repeated=None if scene.startswith('grid_') else cv2.resize(
                stills[scene],(720,1280),interpolation=cv2.INTER_CUBIC).tobytes()
            for index in range(first,last):
                if repeated is None:
                    frame=np.clip(scenes.grid(index, reverse=scene=='grid_out'),0,255).astype('uint8')
                    repeated_frame=cv2.resize(frame,(720,1280),interpolation=cv2.INTER_CUBIC).tobytes()
                else:
                    repeated_frame=repeated
                encoder.stdin.write(repeated_frame)
        encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError('FFmpeg did not finish rendering')


def load_rgba(path, size):
    with Image.open(path) as media:
        image=media.convert('RGBA')
        if size is not None:
            return np.asarray(image.resize(size, Image.Resampling.LANCZOS))
        return image


def load_wordmark(path, color):
    with TemporaryDirectory() as stage:
        if path.suffix.lower()=='.svg':
            rendered=Path(stage)/'wordmark.png'
            subprocess.run(['inkscape', str(path.resolve()), '--export-type=png',
                            f'--export-filename={rendered}', '--export-width=1024'], check=True)
            path=rendered
        image=load_rgba(path,None)
    if image.getbbox() is None:
        raise ValueError('O arquivo do wordmark está vazio.')
    image=image.crop(image.getbbox())
    height=max(1,round(image.height*300/image.width))
    image=image.resize((300,height),Image.Resampling.LANCZOS)
    if color:
        tinted=Image.new('RGBA',image.size,ImageColor.getrgb(color))
        tinted.putalpha(image.getchannel('A'))
        image=tinted
    return np.asarray(image)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    assets=parser.add_mutually_exclusive_group(required=True)
    assets.add_argument('--reference', type=Path, help='MP4 Origins para extrair o monograma localmente')
    assets.add_argument('--mark-profile', type=Path, help='Perfil JSON gerado por origins.mark')
    parser.add_argument('--font', type=Path, help='TTF/OTF local para texto editável')
    parser.add_argument('--wordmark', type=Path, help='Vetorial SVG ou PNG transparente já autorizado')
    parser.add_argument('--wordmark-color', default='#373d41', help='Cor de aplicação do wordmark')
    parser.add_argument('--cap-plate', type=Path, help='PNG do boné em tela vertical, preferencialmente RGBA')
    parser.add_argument('--cap-logo', choices=('overlay','baked'), default='overlay')
    args=parser.parse_args()
    args.destination.mkdir(parents=True,exist_ok=True)
    timeline=json.loads((ROOT/'timeline.json').read_text(encoding='utf-8'))
    try:
        profile=extract(args.reference) if args.reference else json.loads(args.mark_profile.read_text(encoding='utf-8'))
        if args.font:
            scenes.TEXT_FONT=str(args.font)
        if args.wordmark:
            scenes.WORDMARK=load_wordmark(args.wordmark,args.wordmark_color)
        if args.cap_plate:
            scenes.CAP_PLATE=load_rgba(args.cap_plate,(scenes.W,scenes.H))
            scenes.CAP_HAS_LOGO=args.cap_logo=='baked'
        audio(args.destination/'sfx.wav',timeline['fps'],timeline['frame_count'],timeline['cuts'])
        render(args.destination/'motion.mp4',timeline,profile)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'{exc}\n')
