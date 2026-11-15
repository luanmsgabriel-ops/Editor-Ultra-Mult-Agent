"""Render a procedural iridescent surface, optionally clipped by an alpha matte."""
import argparse
from pathlib import Path
import subprocess

import cv2
import numpy as np
from PIL import Image


def frame(x,y,t,strength):
    drift=x*8.2+y*3.9+2*np.sin(x*7.3-t*3)
    bands=.5+.5*np.sin(drift+t*7.8)
    grain=.5+.5*np.cos(x*22-y*11+3*np.cos(drift)+5*t)
    beam=np.exp(-((x-.72-.11*np.sin(7*t))/.085)**2-((y-.53+.09*np.sin(x*9))/.44)**2)
    glint=np.exp(-((x-.76+.16*(y-.5))/.018)**2)*(.64+.36*np.sin(y*8+t*5))
    rgb=np.stack([47+113*bands+50*grain,39+54*bands+53*grain+93*beam,
                  61+51*bands+78*(1-grain)+64*beam],axis=2)
    return np.rint(np.clip(128+(rgb+glint[...,None]*[69,107,94]-128)*strength,0,255)).astype('uint8')


def render(output,width,height,fps,seconds,strength,mask=None):
    if width<=0 or height<=0 or width%2 or height%2 or not 1<=fps<=120 or seconds<=0 or not 0<=strength<=2:
        raise ValueError('Use dimensões pares, duração positiva e intensidade entre 0 e 2.')
    alpha=output.suffix.lower()=='.mov'
    if not alpha and output.suffix.lower()!='.mp4':
        raise ValueError('Use MP4 para prévia ou MOV para RGBA.')
    matte=np.full((height,width),255,'uint8')
    if mask:
        with Image.open(mask) as source:
            if 'A' in source.getbands():
                ink=np.asarray(source.getchannel('A'))
            else:
                ink=np.asarray(source.convert('L'))
        matte=cv2.resize(ink,(width,height),interpolation=cv2.INTER_AREA)
    xx,yy=np.meshgrid(np.linspace(0,1,width,dtype='float32'),np.linspace(0,1,height,dtype='float32'))
    args=['ffmpeg','-nostdin','-v','error','-y','-f','rawvideo','-pix_fmt','rgba' if alpha else 'rgb24',
          '-s',f'{width}x{height}','-r',str(fps),'-i','-','-an',
          '-c:v','qtrle','-pix_fmt','argb'] if alpha else [
          'ffmpeg','-nostdin','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24',
          '-s',f'{width}x{height}','-r',str(fps),'-i','-','-an',
          '-c:v','libx264','-pix_fmt','yuv420p','-crf','18','-movflags','+faststart']
    output.parent.mkdir(parents=True,exist_ok=True)
    with subprocess.Popen(args+['-threads','4',str(output)],stdin=subprocess.PIPE) as writer:
        for i in range(max(1,round(seconds*fps))):
            rgb=frame(xx,yy,i/fps,strength)
            if alpha:
                rgb=np.dstack((rgb,matte))
            else:
                power=matte[...,None]/255
                rgb=np.rint(rgb*power+np.array([10,13,15])*(1-power)).astype('uint8')
            writer.stdin.write(rgb.tobytes())
        writer.stdin.close()
        if writer.wait():
            raise RuntimeError('Não foi possível renderizar o overlay.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path)
    p.add_argument('--mask',type=Path)
    p.add_argument('--size',nargs=2,type=int,default=(720,1280))
    p.add_argument('--fps',type=int,default=30)
    p.add_argument('--seconds',type=float,default=2.4)
    p.add_argument('--strength',type=float,default=1.)
    a=p.parse_args()
    try:
        render(a.output,*a.size,a.fps,a.seconds,a.strength,a.mask)
    except (ValueError,OSError) as e:
        p.exit(1,f'{e}\n')


if __name__=='__main__':
    main()
