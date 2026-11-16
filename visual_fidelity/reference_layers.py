"""Read occlusion and content changes within separately tracked reference masks."""

import argparse
from bisect import bisect_right
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path

import cv2
import numpy as np

from .geometric_replay import evaluate, mask
from .reference_cadence import digest, video_clock, video_frames

SCHEMA = 'reference-layers/1'
DEPTHS = ('behind_subject', 'in_front_of_subject')


def _support(region, min_pixels):
    return np.count_nonzero(region) >= min_pixels


def _quantile(values, region, min_pixels, q=.70):
    return float(np.quantile(values[region], q)) if _support(region, min_pixels) else None


def _appearance(image, region):
    return np.quantile(image[region], [.25, .50, .75], axis=0).ravel()


def _isolate(shapes, width, height):
    """Suppress antialiased edges and pixels shared by two tracks."""
    full = [mask(shape, width, height) > .90 for shape in shapes]
    kernel = np.ones((5, 5), np.uint8)
    interiors = [cv2.erode(region.astype(np.uint8), kernel) > 0 for region in full]
    overlap = np.sum(full, axis=0) > 1
    return [region & ~overlap for region in interiors], ~np.logical_or.reduce(full)


def _read_gray(path, size):
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f'Cannot decode subject matte: {path}')
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def analyze_layers(video, samples, subject_matte, clean_frame, *, rotation=None,
                   content_threshold=.10, min_pixels=180):
    """Infer layer order from holdout evidence, and estimate each content clock.

    samples supplies stable shape identities as children of a tracked union
    in consistent order, or a single shape. subject_matte may be one PNG or a
    path containing a Python {frame:04d} field. clean_frame is a low-opacity
    anchor from the same shot. It must show the subject and original setting.
    """
    if not 0 < content_threshold <= 1 or min_pixels < 1:
        raise ValueError('Invalid content threshold or minimum sample size')
    rate, count = video_clock(video)
    indexes = [row['frame'] for row in samples]
    if (not indexes or any(type(i) is not int or not 0 <= i < count for i in indexes)
            or indexes != list(range(indexes[0], indexes[-1] + 1))):
        raise ValueError('Tracked layer samples must form a contiguous reference interval')
    if not 0 <= clean_frame < count:
        raise ValueError('Clean frame is outside the video')
    geometry = {}
    for row in samples:
        frame = row['frame']
        shape = evaluate(row['mask'], frame)
        children = shape.get('shapes') if shape['kind'] == 'union' else [shape]
        if not children:
            raise ValueError('Tracked masks cannot be empty')
        geometry[frame] = [
            {'id': f'layer-{i + 1}', 'mask': {**child, 'opacity': child.get('opacity', 1)
                                               * (shape.get('opacity', 1) if shape['kind'] == 'union' else 1)}}
            for i, child in enumerate(children)
        ]
    track_count = len(geometry[indexes[0]])
    if any(len(row) != track_count for row in geometry.values()):
        raise ValueError('Layer identity changes across geometry samples')

    selected = set(indexes) | {clean_frame}
    last_selected = max(selected)
    pictures = {}
    for index, image in enumerate(video_frames(video, rotation)):
        if index in selected:
            height, width = image.shape[:2]
            size = (min(width, 480), max(1, round(height * min(width, 480) / width)))
            pictures[index] = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        if index == last_selected:
            break
    if len(pictures) != len(selected):
        raise ValueError('Could not decode every reference layer sample')
    plate = pictures[clean_frame].astype(np.float32)
    height, width = plate.shape[:2]
    tracks = [{'id': f'layer-{i+1}', 'observations': [], 'switches': []}
              for i in range(track_count)]
    previous_picture = previous_regions = previous_bg = None
    for index in indexes:
        picture = pictures[index].astype(np.float32)
        subject = _read_gray(str(subject_matte).format(frame=index), (width, height))
        kernel = np.ones((7, 7), np.uint8)
        foreground = cv2.erode(subject, kernel) > 200
        background = cv2.dilate(subject, kernel) < 30
        shapes = [layer['mask'] for layer in geometry[index]]
        regions, control = _isolate([{**shape, 'opacity': 1} for shape in shapes], width, height)
        delta = np.abs(picture - plate).mean(axis=2) / 255
        step = None if previous_picture is None else np.abs(picture - previous_picture).mean(axis=2) / 255
        fg_noise = _quantile(delta, control & foreground, min_pixels, .80)
        bg_noise = _quantile(delta, control & background, min_pixels, .80)
        for j, (track, region, shape) in enumerate(zip(tracks, regions, shapes)):
            inside = _quantile(delta, region & foreground, min_pixels)
            outside = _quantile(delta, region & background, min_pixels)
            row = {'frame': index}
            if _support(region & background, min_pixels):
                row['appearance_bgr'] = _appearance(picture, region & background).round(3).tolist()
            if shape.get('opacity', 1) >= .8 and None not in (inside, outside, fg_noise, bg_noise):
                inside = max(0., inside - fg_noise)
                outside = max(0., outside - bg_noise)
                row.update(subject_change=round(inside, 5), background_change=round(outside, 5))
                if outside >= .09 or inside >= .12:
                    if inside >= .10:
                        row['occlusion'] = DEPTHS[1]
                    elif outside >= .10 and inside <= .045:
                        row['occlusion'] = DEPTHS[0]
            if step is not None and min(shape.get('opacity', 1),
                                        geometry[index - 1][j]['mask'].get('opacity', 1)) >= .8:
                # Compare the same screen pixels visible in this strip in both
                # frames, outside the subject and any intersecting strip.
                shared = region & previous_regions[j] & background & previous_bg
                score = _quantile(step, shared, min_pixels, .72)
                if score is not None:
                    row['content_change'] = round(score, 5)
            track['observations'].append(row)
        previous_picture, previous_regions, previous_bg = picture, regions, background

    for track in tracks:
        votes = Counter(row['occlusion'] for row in track['observations'] if 'occlusion' in row)
        depth = None
        if votes:
            top, votes_for_top = votes.most_common(1)[0]
            if votes_for_top >= 4 and votes_for_top / votes.total() >= .70:
                depth = top
        track['depth'] = depth
        track['depth_votes'] = dict(votes)
        track['switches'] = [
            {'frame': row['frame'], 'score': row['content_change']}
            for row in track['observations'] if row.get('content_change', 0) >= content_threshold
        ]
        starts = [indexes[0], *(row['frame'] for row in track['switches'])]
        slots = []
        for i, (start, end) in enumerate(zip(starts, [*starts[1:], indexes[-1] + 1])):
            fingerprints = [row['appearance_bgr'] for row in track['observations'][start-indexes[0]:end-indexes[0]]
                            if 'appearance_bgr' in row]
            slot = {'id': f"{track['id']}-content-{i+1}", 'start': start, 'end': end}
            if fingerprints:
                slot['appearance_bgr'] = np.median(fingerprints, axis=0).round(3).tolist()
            slots.append(slot)
        track['content_slots'] = slots
    return {
        'schema': SCHEMA, 'reference_sha256': digest(video), 'fps': str(rate),
        'interval': [indexes[0], indexes[-1] + 1], 'clean_frame': clean_frame,
        'content_threshold': content_threshold, 'tracks': tracks,
        'geometry': [{'frame': index, 'layers': geometry[index]} for index in indexes],
        'method': 'Per-track photometric evidence on a clean anchor and same-pixel temporal comparisons',
    }


def bind_palette(timeline, effect, palette, root):
    """Fill content slots from curated media, estimating visual matches for stills."""
    from .geometric_video import Sources, viewport

    if not palette:
        raise ValueError('Provide a palette with approved replacement assets')
    loader = Sources(root, timeline['assets'])
    candidates = []
    try:
        for item in palette:
            rgb = loader.frame(item)
            image = viewport(rgb, item.get('view', [.5, .5, 1]), 160, 90)
            candidates.append((item, _appearance(image, np.ones(image.shape[:2], bool))))
    finally:
        loader.close()
    choices = {}
    distinct_sources = len({item['source'] for item, _ in candidates})
    for track in effect['tracks']:
        previous = None
        for slot in track['content_slots']:
            eligible = [i for i, (item, _) in enumerate(candidates)
                        if previous is None or (
                            item['source'] != candidates[previous][0]['source']
                            if distinct_sources > 1 else item != candidates[previous][0]
                        )]
            if not eligible:
                raise ValueError('The reference has content changes; provide two distinct palette bindings')
            signature = slot.get('appearance_bgr')
            index = eligible[0] if signature is None else min(
                eligible, key=lambda i: np.mean(abs(candidates[i][1] - np.asarray(signature))),
            )
            choices[slot['id']] = candidates[index][0]
            previous = index
    return choices


def apply_layers(timeline, effect, content, *, reference_start_frame=None, subject=None):
    """Reapply measured geometry, depth and cut timing with replacement assets."""
    if effect.get('schema') != SCHEMA:
        raise ValueError('Expected a reference layers template')
    result = deepcopy(timeline)
    cadence = result.get('reference_cadence', {})
    if cadence.get('source_sha256', effect['reference_sha256']) != effect['reference_sha256']:
        raise ValueError('Layer and cadence maps must describe the same reference video')
    reference_fps = Fraction(effect['fps'])
    output_fps = Fraction(str(result['fps']))
    if reference_start_frame is None:
        reference_start_frame = cadence.get('reference_start_frame', 0)
    geometry = {row['frame']: row['layers'] for row in effect['geometry']}
    tracks = {track['id']: track for track in effect['tracks']}
    starts = {}
    for track_id, track in tracks.items():
        if track['depth'] not in DEPTHS:
            raise ValueError(f'Unresolved depth for {track_id}; review the occlusion evidence')
        slots = track['content_slots']
        if any(slot['id'] not in content for slot in slots):
            raise ValueError(f'Unbound photographic content for {track_id}')
        starts[track_id] = [slot['start'] for slot in slots]
    used_slots = set()
    first, last = effect['interval']
    if subject:
        subject_fps = Fraction(str(subject['fps']))
        if subject_fps <= 0 or type(subject['start_frame']) is not int or subject['start_frame'] < 0:
            raise ValueError('Invalid subject source clock')
        if '{frame' not in subject['matte_pattern']:
            raise ValueError('Subject matte pattern must contain the source frame field')
        if result['assets'][subject['source']]['kind'] != 'video':
            raise ValueError('Subject source must be a video asset')
    for binding in result['frame_bindings']:
        ref = binding.get('reference_mask_frame',
                          reference_start_frame + int(binding['frame'] * reference_fps / output_fps))
        if not first <= ref < last:
            continue
        if subject:
            src_frame = subject['start_frame'] + int((ref - first) * subject_fps / reference_fps)
            src = {'source': subject['source'], 'frame': src_frame,
                   'view': deepcopy(subject.get('view', [.5, .5, 1]))}
            binding['base'] = src
            binding['foreground'] = dict(src, matte=subject['matte_pattern'].format(frame=src_frame))
        if not binding.get('foreground'):
            raise ValueError(f"Frame {binding['frame']} requires a bound subject matte")
        layers = []
        for item in geometry[ref]:
            track = tracks[item['id']]
            slot = track['content_slots'][bisect_right(starts[item['id']], ref) - 1]
            insert = deepcopy(content[slot['id']])
            if 'start_frame' in insert:
                video_rate = Fraction(str(insert.pop('fps')))
                insert['frame'] = insert.pop('start_frame') + int((ref - slot['start']) * video_rate / reference_fps)
            used_slots.add(slot['id'])
            layers.append(dict(item, depth=track['depth'], insert=insert, content_slot=slot['id']))
        binding['layers'] = layers
        for key in ('insert', 'mask', 'mask_file', 'mask_opacity', 'fit_insert_to_mask'):
            binding.pop(key, None)
    if not used_slots:
        raise ValueError('The effect does not intersect the output timeline')
    result['reference_layers'] = {
        'reference_sha256': effect['reference_sha256'], 'interval': effect['interval'],
        'tracks': [{'id': t['id'], 'depth': t['depth'], 'switches': t['switches']}
                   for t in effect['tracks']],
        'sampled_content_slots': sorted(used_slots),
        'unsampled_content_slots': sorted(set(content) - used_slots),
        'content_bindings': {key: content[key] for key in sorted(used_slots)},
    }
    if subject:
        result['reference_layers']['subject_binding'] = deepcopy(subject)
    from .geometric_video import VERSION
    result['video_engine'] = VERSION
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    analyze = sub.add_parser('analyze')
    analyze.add_argument('video', type=Path)
    analyze.add_argument('geometry', type=Path, help='JSON list of {frame, mask} samples')
    analyze.add_argument('subject_matte', help='Clean subject matte or a {frame:04d} path pattern')
    analyze.add_argument('output', type=Path)
    analyze.add_argument('--clean-frame', required=True, type=int)
    analyze.add_argument('--rotation', choices=(0, 90, 180, 270), type=int)
    analyze.add_argument('--content-threshold', type=float, default=.10)
    apply = sub.add_parser('apply')
    for name in ('timeline', 'effect', 'content', 'output'):
        apply.add_argument(name, type=Path)
    apply.add_argument('--reference-start-frame', type=int)
    apply.add_argument('--palette', action='store_true',
                       help='Interpret content JSON as a list of approved candidate asset bindings')
    apply.add_argument('--subject', type=Path,
                       help='JSON with replacement video, source clock, crop and matte pattern')
    apply.add_argument('--render', type=Path)
    args = parser.parse_args()

    def load(path):
        return json.loads(path.read_text())

    if args.command == 'analyze':
        result = analyze_layers(args.video, load(args.geometry), args.subject_matte, args.clean_frame,
                                rotation=args.rotation, content_threshold=args.content_threshold)
    else:
        from .edit_contract import validate_edit
        if args.output.resolve().parent != args.timeline.resolve().parent or args.output.resolve() == args.timeline.resolve():
            parser.error('Use a new manifest in the same directory as the source timeline')
        timeline, effect, content = load(args.timeline), load(args.effect), load(args.content)
        if args.palette:
            content = bind_palette(timeline, effect, content, args.timeline.parent)
        result = apply_layers(timeline, effect, content,
                              reference_start_frame=args.reference_start_frame,
                              subject=load(args.subject) if args.subject else None)
        validate_edit(result, args.output.parent)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    if args.command == 'apply' and args.render:
        from .geometric_video import render
        render(args.output, args.render)


if __name__ == '__main__':
    main()
