"""Profile and render the isolated Origins wordmark with exact timing elsewhere."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from .glyphs import outline, read_frame
from scipy.ndimage import gaussian_filter1d


def smooth_mark(image):
    contours,hierarchy=cv2.findContours(image,cv2.RETR_TREE,cv2.CHAIN_APPROX_NONE)
    paths=[]
    for index,contour in enumerate(contours):
        if cv2.contourArea(contour)<100:
            continue
        hole=hierarchy[0,index,3]>=0
        points=gaussian_filter1d(contour[:,0,:].astype('float64'),2.8,axis=0,mode='wrap')
        center=points.mean(axis=0)
        radial=points-center
        # Raster contours of the hole run one pixel inside the coloured stroke.
        adjustment=-.78 if hole else .34
        points+=radial/np.linalg.norm(radial,axis=1,keepdims=True)*adjustment
        paths.append({'hole':bool(hole),'xy':(points[::3]+[310.5,584.5]).round(3).tolist()})
    return paths


def extract(source):
    reader=cv2.VideoCapture(str(source))
    frame=read_frame(reader,38)
    reader.release()
    mask=(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)>150).astype('uint8')
    return {
        'viewbox':[720,1280],
        'center':[360,640],
        'mark':smooth_mark(mask[584:697,310:410]),
        'registration':outline((cv2.cvtColor(frame[586:612,407:434],cv2.COLOR_BGR2GRAY)>97).astype('uint8'),
                               407,586,27,26,regions=3),
    }


def stamp(image, paths, color, center=(180,320), scale=1):
    paths=sorted(paths,key=lambda item:item['hole'])
    if not paths:
        return
    points=[(np.asarray(path['xy'])-[360,640])*(.5*scale)+center-.50 for path in paths]
    combined=np.concatenate(points)
    bounds=np.vstack((np.floor(combined.min(axis=0)-2), np.ceil(combined.max(axis=0)+2))).astype(int)
    x0,y0=np.maximum(bounds[0],0)
    x1,y1=np.minimum(bounds[1],image.shape[1::-1])
    if x0>=x1 or y0>=y1:
        return
    mask=np.zeros(((y1-y0)*4,(x1-x0)*4),dtype='uint8')
    for path,shape in zip(paths,points):
        point_subpixels=np.rint((shape-[x0,y0])*4+1.5).astype('int32')
        cv2.fillPoly(mask,[point_subpixels],0 if path['hole'] else 255)
    paint=cv2.resize(mask,(x1-x0,y1-y0),interpolation=cv2.INTER_AREA)[...,None]/255
    section=image[y0:y1,x0:x1]
    section[:]=section*(1-paint)+np.asarray(color)*paint



if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    args.destination.write_text(json.dumps(extract(args.source),indent=1)+'\n',encoding='utf-8')
