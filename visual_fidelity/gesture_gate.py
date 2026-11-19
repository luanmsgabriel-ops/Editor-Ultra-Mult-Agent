"""Eligibility of independently measured hand anchors; never a pose detector."""
from math import isfinite
from numbers import Real

def _finite(value):
    return not isinstance(value,bool) and isinstance(value,Real) and isfinite(value)

def gesture_gate(observations, *, threshold=.85, min_consecutive=3):
    if not _finite(threshold) or not 0<=threshold<=1 or type(min_consecutive) is not int or min_consecutive<1:
        raise ValueError("invalid gesture gate thresholds")
    rows=list(observations)
    if any(not isinstance(row,dict) or type(row.get('frame')) is not int or row['frame']<0 for row in rows):
        raise ValueError("an explicit nonnegative frame is required")
    if len({row['frame'] for row in rows})!=len(rows):
        raise ValueError("supply one hand stream with unique frames")
    accepted={}
    last=None
    count=0
    for row in sorted(rows,key=lambda item:item['frame']):
        f=row['frame']
        track,shot=row.get('track'),row.get('shot')
        p,c=row.get('point'),row.get('confidence')
        if (row.get('visible') is not True or row.get('in_frame') is not True
                or type(track) is not str or not track
                or type(shot) not in (str,int) or shot==''
                or not _finite(c) or not threshold<=c<=1
                or not isinstance(p,(tuple,list)) or len(p)!=2 or not all(_finite(x) and 0<=x<=1 for x in p)):
            last=None
            count=0
            continue
        count=count+1 if last==(f-1,track,shot) else 1
        last=(f,track,shot)
        if count>=min_consecutive:
            accepted[f]=tuple(p)
    return accepted
