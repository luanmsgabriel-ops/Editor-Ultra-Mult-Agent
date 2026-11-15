"""Seeded studio foreground extraction with flow-propagated trimaps.

Preserves source RGB; extracts alpha only. This is supervised classical matting,
not semantic inference. The initial trimap must include bright props/shoes and
exclude floor shadows. Labels use OpenCV GrabCut's 0/1/2/3 convention.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import cv2
import numpy as np


def polygon_trimap(shape, regions, default=0):
    """Paint ordered normalized polygons with labels 0=BG,1=FG,2=pBG,3=pFG."""
    h, w = shape[:2]
    result = np.full((h, w), default, np.uint8)
    for region in regions:
        label = int(region['label'])
        if label not in (0, 1, 2, 3):
            raise ValueError('Trimap labels must be 0, 1, 2, or 3')
        points = np.asarray(region['points'], float)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
            raise ValueError('Each seed needs a polygon with at least three points')
        if np.any(points < 0) or np.any(points > 1):
            raise ValueError('Seed coordinates must be normalized to [0, 1]')
        cv2.fillPoly(result, [np.rint(points * [w-1, h-1]).astype(np.int32)], label)
    return result


def alpha_bounds(alpha, threshold=127):
    y, x = np.nonzero(alpha > threshold)
    return None if not len(x) else [int(x.min()), int(y.min()), int(x.max()+1), int(y.max()+1)]


def fill_small_holes(binary, max_area=256):
    """Fill enclosed classification holes; keep exterior floor and large gaps."""
    result=binary.copy()
    count,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(binary==0),connectivity=8)
    h,w=binary.shape
    for i in range(1,count):
        x,y,bw,bh,area=stats[i]
        if area <= max_area and x > 0 and y > 0 and x+bw < w and y+bh < h:
            result[labels==i]=255
    return result


class StudioMatte:
    """Sequential extractor. Reset/reseed at each cut or camera discontinuity.

    Optical flow moves the prior silhouette; an uncertain contour band is then
    reclassified by color. Initial interior seeds remain flow-tracked to preserve bright objects.
    Enclosed small holes are filled up to the configurable max_hole_area.
    Fine transparent hair cannot be recovered by binary GrabCut classification.
    """
    def __init__(self, initial_iterations=5, tracking_iterations=1,
                 uncertainty_px=9, interior_px=3, feather_sigma=.65, flow_scale=.5, max_hole_area=256):
        self.initial_iterations = int(initial_iterations)
        self.tracking_iterations = int(tracking_iterations)
        self.uncertainty_px = int(uncertainty_px)
        self.interior_px = int(interior_px)
        self.feather_sigma = float(feather_sigma)
        self.flow_scale = float(flow_scale)
        self.max_hole_area = int(max_hole_area)
        self.reset()

    def reset(self):
        self.previous_gray = self.previous_binary = self.trusted_interior = None
        self.bg_model = np.zeros((1,65), np.float64)
        self.fg_model = np.zeros((1,65), np.float64)
        self.flow = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)

    @staticmethod
    def _kernel(radius):
        return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1,2*radius+1))

    def process(self, frame, trimap=None):
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError('Expected uint8 BGR frame')
        h,w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if trimap is not None:
            mask = np.asarray(trimap, dtype=np.uint8).copy()
            if mask.shape != (h,w) or not np.isin(mask,[0,1,2,3]).all():
                raise ValueError('Trimap must match raster and use labels 0..3')
            if not np.any(mask == 1) or not np.any(mask == 0):
                raise ValueError('Trimap needs definite foreground and background seeds')
            iterations = self.initial_iterations
            self.trusted_interior = None
        else:
            if self.previous_gray is None:
                raise ValueError('First frame requires a supervised trimap')
            if self.previous_gray.shape != gray.shape:
                raise ValueError('Raster changed: reset and supply a new trimap')
            sw,sh = max(16,round(w*self.flow_scale)),max(16,round(h*self.flow_scale))
            cur = cv2.resize(gray,(sw,sh)); prev=cv2.resize(self.previous_gray,(sw,sh))
            flow = self.flow.calc(cur,prev,None)
            flow = cv2.resize(flow,(w,h)); flow[:,:,0] *= w/sw; flow[:,:,1] *= h/sh
            y,x=np.mgrid[:h,:w].astype(np.float32)
            warped=cv2.remap(self.previous_binary,x+flow[:,:,0],y+flow[:,:,1],
                             cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)
            expanded=cv2.dilate(warped,self._kernel(self.uncertainty_px))
            interior=cv2.erode(warped,self._kernel(self.interior_px))
            mask=np.full((h,w),cv2.GC_BGD,np.uint8)
            mask[expanded>0]=cv2.GC_PR_BGD
            mask[warped>0]=cv2.GC_PR_FGD
            mask[interior>0]=cv2.GC_FGD
            # Keep the initial interior tracked, avoiding cumulative erosion of
            # light shoes/props when their colors resemble the studio floor.
            self.trusted_interior=cv2.remap(self.trusted_interior,x+flow[:,:,0],y+flow[:,:,1],
                                            cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)
            mask[self.trusted_interior>0]=cv2.GC_FGD
            iterations=self.tracking_iterations
        cv2.grabCut(frame,mask,None,self.bg_model,self.fg_model,iterations,cv2.GC_INIT_WITH_MASK)
        binary=np.uint8((mask==cv2.GC_FGD)|(mask==cv2.GC_PR_FGD))*255
        binary=fill_small_holes(binary,self.max_hole_area)
        if self.trusted_interior is None:
            self.trusted_interior=cv2.erode(binary,self._kernel(self.interior_px))
        self.previous_gray=gray; self.previous_binary=binary
        if self.feather_sigma > 0:
            return cv2.GaussianBlur(binary,(0,0),self.feather_sigma)
        return binary


def extract_video(source, initial_trimap, output, **options):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    cap=cv2.VideoCapture(str(source))
    if not cap.isOpened(): raise ValueError(f'Cannot open source: {source}')
    fps=float(cap.get(cv2.CAP_PROP_FPS)); extractor=StudioMatte(**options)
    records=[]; previous=None; index=0
    try:
        while True:
            ok,frame=cap.read()
            if not ok: break
            alpha=extractor.process(frame,initial_trimap if index==0 else None)
            if not cv2.imwrite(str(output/f'{index:04d}.png'),alpha):
                raise IOError('Failed writing alpha frame')
            binary=alpha>127; area=int(binary.sum())
            records.append({'frame':index,'bounds':alpha_bounds(alpha),'area':area,
                            'changed_pixels':None if previous is None else int(np.count_nonzero(binary!=previous))})
            previous=binary; index+=1
    finally: cap.release()
    if not records: raise ValueError('Video contains no decodable frames')
    report={'method':'supervised GrabCut with optical-flow propagated trimaps',
            'version':1,'fps':fps,'frames':index,'rgb':'untouched source pixels',
            'floor_shadow':'excluded from foreground; composite separately',
            'limitations':['Manually supervised initial trimap required',
                          'Reset and reseed at cuts or camera discontinuities',
                          'Binary edge classification with soft feather; not subpixel hair matting',
                          'Small enclosed holes are filled; lower max_hole_area when tiny real gaps matter',
                          'Temporal changed-pixel count measures motion plus segmentation; not a fidelity certificate'],
            'options':options,'records':records}
    (output/'matte-report.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source');p.add_argument('--trimap',required=True);p.add_argument('--output',required=True)
    args=p.parse_args()
    trimap=cv2.imread(args.trimap,cv2.IMREAD_GRAYSCALE)
    if trimap is None: raise ValueError('Cannot read trimap')
    report=extract_video(args.source,trimap,args.output)
    print(json.dumps({'frames':report['frames'],'output':args.output,'method':report['method']}))

if __name__=='__main__': main()
