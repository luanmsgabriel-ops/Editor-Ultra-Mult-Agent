"""Contour and frame extraction shared with the Órbita pilot."""
import cv2
import numpy as np


def largest_regions(mask, count):
    size, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    ranking = 1 + np.argsort(stats[1:size, cv2.CC_STAT_AREA])[::-1][:count]
    return np.isin(labels, ranking).astype('uint8')


def outline(mask, left, top, w, h, regions=1):
    mask = largest_regions(mask, regions)
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for i, contour in enumerate(contours):
        if cv2.contourArea(contour) < 12:
            continue
        polygon = cv2.approxPolyDP(contour,.85,True)[:,0,:].astype('float64') + .5
        points = polygon * [w/mask.shape[1], h/mask.shape[0]] + [left, top]
        result.append({'hole': bool(hierarchy[0,i,3] >= 0), 'xy': points.round(3).tolist()})
    return result


def read_frame(reader, number):
    reader.set(cv2.CAP_PROP_POS_FRAMES, number)
    ok, frame = reader.read()
    if not ok:
        raise ValueError(f'Frame {number} not available')
    return frame
