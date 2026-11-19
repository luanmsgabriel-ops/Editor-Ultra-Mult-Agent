#!/usr/bin/env python3
"""Full-frame decoded pixel audit. Requires FFmpeg/FFprobe and NumPy."""
import argparse
import hashlib
import json
import subprocess
import sys
from fractions import Fraction
from itertools import zip_longest
from pathlib import Path

import numpy as np


def probe(path):
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
           '-show_streams', '-show_entries',
           'stream=width,height,time_base,nb_frames,r_frame_rate,avg_frame_rate:frame=best_effort_timestamp,width,height',
           '-of', 'json', str(path)]
    info = json.loads(subprocess.check_output(cmd))
    if not info.get('streams') or not info.get('frames'):
        raise ValueError(f'no probed video frames: {path}')
    stream, frames = info['streams'][0], info['frames']
    wh = (stream['width'], stream['height'])
    if any((f.get('width'), f.get('height')) != wh for f in frames):
        raise ValueError(f'variable or unreported raster: {path}')
    if any('best_effort_timestamp' not in f for f in frames):
        raise ValueError(f'missing presentation timestamp: {path}')
    clock = [Fraction(f['best_effort_timestamp']) * Fraction(stream['time_base']) for f in frames]
    if any(a >= b for a, b in zip(clock, clock[1:])):
        raise ValueError(f'nonmonotone/duplicate presentation timestamps: {path}')
    with path.open('rb') as handle:
        sha = hashlib.file_digest(handle, 'sha256').hexdigest()
    stream.update(file=str(path), sha256=sha, probed_frames=len(frames),
                  first_pts=str(clock[0]), last_pts=str(clock[-1]),
                  distinct_frame_intervals=sorted({str(b-a) for a,b in zip(clock, clock[1:])}))
    return stream, clock


def decode(path, width, height):
    """Yield independently allocated lossless RGB decode samples, not frame seeks."""
    n = width * height * 3
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-noautorotate',
           '-threads', '2', '-i', str(path), '-map', '0:v:0', '-an', '-sn', '-dn',
           '-fps_mode', 'passthrough', '-c:v', 'rawvideo', '-threads:v', '1',
           '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as process:
        try:
            while block := process.stdout.read(n):
                if len(block) != n:
                    raise ValueError(f'incomplete decoded frame: {path}')
                yield np.frombuffer(block, np.uint8).reshape(height, width, 3)
            if process.wait() != 0:
                raise ValueError(f'FFmpeg decode error: {path}')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def scopes(numbers):
    runs = []
    for n in numbers:
        if runs and n == runs[-1][1]:
            runs[-1][1] = n + 1
        else:
            runs.append([n, n + 1])
    return runs


def bounds(mask):
    ys = np.flatnonzero(mask.any(axis=1))
    xs = np.flatnonzero(mask.any(axis=0))
    return [int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1] if len(ys) else None


def audit(args, output):
    prior, a_clock = probe(args.input)
    output['inputs'] = [prior]
    expected_counts = [args.expected_frames]
    current = b_clock = None
    if args.compare:
        current, b_clock = probe(args.compare)
        output['inputs'].append(current)
        expected_counts.append(args.compare_expected_frames or args.expected_frames)
        mismatch = next((i for i,(a,b) in enumerate(zip_longest(a_clock,b_clock)) if a!=b), None)
        output['comparison_clock'] = {'equal': mismatch is None, 'first_mismatch_index': mismatch}
        if mismatch is not None:
            raise ValueError(f'frame count or presentation clock mismatch at frame {mismatch}; not compared')
        if (prior['width'],prior['height']) != (current['width'],current['height']):
            raise ValueError('raster mismatch; not compared')
    for entry, expected in zip(output['inputs'], expected_counts):
        if expected is not None and expected != entry['probed_frames']:
            raise ValueError(f'expected {expected} frames, found {entry["probed_frames"]}: {entry["file"]}')
        if str(entry.get('nb_frames','N/A')).isdigit() and int(entry['nb_frames']) != entry['probed_frames']:
            raise ValueError(f'stream frame count differs from parsed frames: {entry["file"]}')
        if args.require_cfr and len(entry['distinct_frame_intervals']) > 1:
            raise ValueError(f'presentation timestamp spacing is not constant; check dropped frame or VFR: {entry["file"]}')
    shape = prior['width'], prior['height']
    a = decode(args.input, *shape)
    b = decode(args.compare, *shape) if args.compare else None
    items = zip_longest(a,b) if b is not None else ((f,None) for f in a)
    rows = []
    parent = None
    try:
        for i,(x,y) in enumerate(items):
            if i>=len(a_clock) or x is None or (b is not None and y is None):
                raise ValueError(f'frame count mismatch in decoded sequence at frame {i}')
            row = {'index':i,'pts':str(a_clock[i])}
            if y is not None:
                d = np.abs(x.astype(np.int16) - y.astype(np.int16))
                m = d.max(axis=2)
                exact = m > 0
                strong = m >= args.threshold
                row.update(exact=int(exact.sum()), strong=int(strong.sum()),
                           abs_rgb_mean=round(float(d.mean()),8), peak=int(m.max()), strong_bbox=bounds(strong))
            else:
                row['mean_rgb'] = [round(float(x[:,:,c].mean()),6) for c in range(3)]
                row['previous_frame_strong_pixels'] = (
                    int((np.abs(x.astype(np.int16)-parent).max(axis=2)>=args.threshold).sum())
                    if parent is not None else None)
                parent = x.astype(np.int16)
            rows.append(row)
    finally:
        a.close()
        if b is not None:
            b.close()
    if len(rows) != len(a_clock):
        raise ValueError(f'decoded {len(rows)} frames, expected probed {len(a_clock)}')
    output.update(decoded_frames=len(rows), decoded_coverage={'decoded':len(rows),'probed':len(a_clock)},
                  frame_table=rows)
    if b is not None:
        output.update(comparison={
            'pixel_count_per_frame':shape[0]*shape[1],
            'exact_changed_frame_count':sum(r['exact']>0 for r in rows),
            'exact_changed_frame_scopes_half_open':scopes(r['index'] for r in rows if r['exact']),
            'strong_changed_frame_count':sum(r['strong']>=args.min_pixels for r in rows),
            'strong_changed_frame_scopes_half_open':scopes(r['index'] for r in rows if r['strong']>=args.min_pixels),
            'strong_pixel_threshold':args.threshold,'strong_frame_min_pixels':args.min_pixels,
            'global_mean_absolute_rgb_delta':round(sum(r['abs_rgb_mean'] for r in rows)/len(rows),8)
        })
    else:
        output['raster_scan'] = {
            'pixel_count_per_frame':shape[0]*shape[1],
            'frames_with_rgb_mean':len(rows),
            'consecutive_pairs_measured':len(rows)-1,
            'adjacent_strong_pixel_threshold':args.threshold,
            'adjacent_delta_definition':'count of pixels where max absolute change in RGB between consecutive decoded frames is at least threshold. A cue, not an effect or cut verdict.'
        }
    output['status']='complete'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path)
    p.add_argument('--compare',type=Path)
    p.add_argument('--same-edit-clock',action='store_true',help='declare both files are the same edit/timebase content, not reference vs new footage')
    p.add_argument('--expected-frames',type=int)
    p.add_argument('--compare-expected-frames',type=int)
    p.add_argument('--require-cfr',action='store_true',help='require exactly uniform PTS intervals, rejecting even timestamp quantization')
    p.add_argument('--threshold',type=int,default=24,help='minimum maximum RGB channel delta (1–255)')
    p.add_argument('--min-pixels',type=int,default=1,help='minimum strong pixels for a frame marked strong')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.resolve() in {z.resolve() for z in (a.input, a.compare) if z is not None}:
        p.error('--out must not overwrite any input video')
    if a.compare_expected_frames is not None and not a.compare:
        p.error('--compare-expected-frames requires --compare')
    if a.compare and not a.same_edit_clock:
        p.error('--compare also requires --same-edit-clock; no automatic alignment')
    if not 1<=a.threshold<=255 or a.min_pixels<1 or any(v is not None and v<1 for v in [a.expected_frames,a.compare_expected_frames]):
        p.error('invalid audit thresholds or expected count')
    receipt={'mode':'same-clock-decode-delta' if a.compare else 'decode-coverage',
             'interpretation':'Decoded RGB code-value diagnostic only, not an effect match or similarity score. Codec differences can change inactive pixels. Bounding boxes enclose all flagged points, including disjoint bands; they are not coverage masks. Same clock requires caller-verified same edit; not automatically aligned.'}
    err=None
    try:
        audit(a,receipt)
    except (ValueError, subprocess.SubprocessError, OSError) as e:
        err=str(e)
        receipt.update(status='blocked',error=err)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(receipt,indent=2)+'\n')
    if err:
        print(err,file=sys.stderr)
        return 2
    return 0


if __name__=='__main__':
    raise SystemExit(main())
