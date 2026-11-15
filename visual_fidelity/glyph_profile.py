"""Calibrate an isolated bright title to editable letter placements."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from .anchor_graphics import graphemes, ink, load_face


def bbox(mask):
    x,y,w,h=cv2.boundingRect(mask)
    return mask[y:y+h,x:x+w]


def shape_library(font, letters):
    variants={}
    for char in set(letters):
        source=np.asarray(ink(font,char))
        distance=int(np.hypot(*source.shape))+8
        angles=[]
        for angle in range(-46,47,2):
            matrix=cv2.getRotationMatrix2D((source.shape[1]/2,source.shape[0]/2),angle,1)
            matrix[:,2]+=[(distance-source.shape[1])/2,(distance-source.shape[0])/2]
            rotated=cv2.warpAffine(source,matrix,(distance,distance))
            selected=bbox((rotated>100).astype('uint8'))
            if selected.size:
                angles.append((angle,cv2.resize(selected,(48,48),interpolation=cv2.INTER_AREA)>.4))
        variants[char]=angles
    return variants


def fit(target, rotations):
    sample=cv2.resize(target,(48,48),interpolation=cv2.INTER_AREA)>.4
    return -max(rotations,key=lambda pair:np.count_nonzero(sample&pair[1])/
                np.count_nonzero(sample|pair[1]))[0]


def profile(video,text,font,roi,first,last,threshold=185,min_area=800):
    letters=[char for char in graphemes(text) if not char.isspace()]
    if len(letters)<2:
        raise ValueError('Use uma palavra com pelo menos duas letras.')
    variants=shape_library(load_face(str(font),900),letters)
    reader=cv2.VideoCapture(str(video))
    result={}
    try:
        reader.set(cv2.CAP_PROP_POS_FRAMES,first)
        x,y,w,h=roi
        for number in range(first,last):
            ok,frame=reader.read()
            if not ok:
                break
            if x<0 or y<0 or x+w>frame.shape[1] or y+h>frame.shape[0]:
                raise ValueError('O recorte do título ultrapassa a imagem.')
            mask=(np.min(frame[y:y+h,x:x+w],axis=2)>=threshold).astype('uint8')
            _,ident,stats,_=cv2.connectedComponentsWithStats(mask)
            large=[(i,int(sx),int(sy),int(sw),int(sh),int(a))
                   for i,(sx,sy,sw,sh,a) in enumerate(stats[1:],1) if a>=min_area]
            large.sort(key=lambda seg:seg[1]+seg[3]/2)
            if len(large)!=len(letters):
                continue
            poses=[]
            for char,(i,sx,sy,sw,sh,_) in zip(letters,large):
                related=[i]
                if char.casefold() in 'áàâãäéêèëíïìîóôõöòúüùûçij':
                    for mark,(mx,my,mw,mh,area) in enumerate(stats[1:],1):
                        above=0<=sy-(my+mh)<=sh*.55
                        below=0<=my-(sy+sh)<=sh*.25 and char.casefold()=='ç'
                        if 18<=area<min_area and (above or below) and sx-sw*.25<mx+mw/2<sx+sw*1.25:
                            related.append(mark)
                full=np.isin(ident,related).astype('uint8')
                gx,gy,gw,gh=cv2.boundingRect(full)
                if not gw or not gh:
                    continue
                turn=fit(full[gy:gy+gh,gx:gx+gw],variants[char])
                poses.append([(gx+gw/2)/w,(gy+gh/2)/h,gw/w,gh/h,turn])
            if len(poses)==len(letters):
                result[str(number-first)]=poses
    finally:
        reader.release()
    if not result:
        raise ValueError('Nenhum quadro com componentes isolados para o texto indicado.')
    return {'text':text,'source_frames':[first,last],'aspect':roi[2]/roi[3],'frames':result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--text',required=True)
    parser.add_argument('--font',type=Path,required=True)
    parser.add_argument('--box',nargs=4,type=int,required=True,metavar=('X','Y','WIDTH','HEIGHT'))
    parser.add_argument('--frames',nargs=2,type=int,required=True,metavar=('START','END'))
    parser.add_argument('--threshold',type=int,default=185)
    parser.add_argument('--min-area',type=int,default=800)
    args=parser.parse_args()
    try:
        if min(args.box[2:])<=0 or not 0<=args.frames[0]<args.frames[1] or not 0<=args.threshold<=255:
            raise ValueError('Caixa, intervalo ou limiar inválido.')
        data=profile(args.video,args.text,args.font,args.box,*args.frames,args.threshold,args.min_area)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except (ValueError,OSError) as exc:
        parser.exit(1,f'{exc}\n')


if __name__=='__main__':
    main()
