"""Measure cut frames and silhouette matches in a decoded video pair."""
import argparse
import json

import cv2
import numpy as np


def decode(path):
    reader=cv2.VideoCapture(path)
    frames=[]
    try:
        while True:
            ok,bgr=reader.read()
            if not ok:
                return frames
            frames.append(cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY))
    finally:
        reader.release()


def score(reference, remake):
    def cuts(images):
        return [frame for frame in range(33,144)
                if cv2.absdiff(images[frame],images[frame-1]).mean()>2.4]

    def mask(img,inverse):
        patch=img[584:699,309:408]
        return patch<103 if inverse else patch>150

    selected=[28,35,39,47,138,141]
    overlap,shift=[],[]
    for frame in selected:
        a,b=[mask(images[frame],frame in (35,141)) for images in (reference,remake)]
        overlap.append(round(float(np.count_nonzero(a&b)/np.count_nonzero(a|b)),4))
        shift.append(round(float(np.linalg.norm(np.argwhere(a).mean(axis=0)-
                                               np.argwhere(b).mean(axis=0))),3))
    source_cuts,clone_cuts=cuts(reference),cuts(remake)
    return {
        'reference_frames':len(reference), 'render_frames':len(remake),
        'reference_main_cut_frames':source_cuts,
        'render_main_cut_frames':clone_cuts,
        'identical_main_cut_frames':len(set(source_cuts)&set(clone_cuts)),
        'logo_frames':selected,
        'logo_iou':overlap, 'logo_iou_median':round(float(np.median(overlap)),4),
        'logo_center_error_px':shift, 'logo_center_error_px_median':round(float(np.median(shift)),3)
    }


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference')
    parser.add_argument('render')
    args=parser.parse_args()
    print(json.dumps(score(decode(args.reference),decode(args.render)),indent=2))
