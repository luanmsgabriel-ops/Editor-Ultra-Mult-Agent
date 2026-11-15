"""Normalize COCO-WholeBody 133 predictions or run local RTMW ONNX models."""
import argparse
from itertools import chain, islice
import json
from math import isfinite
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np


BODY_NAMES = (
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle',
    'left_big_toe', 'left_small_toe', 'left_heel',
    'right_big_toe', 'right_small_toe', 'right_heel',
)
HAND_NAMES = (
    'hand_wrist',
    'thumb_cmc', 'thumb_mcp', 'thumb_ip', 'thumb_tip',
    'index_mcp', 'index_pip', 'index_dip', 'index_tip',
    'middle_mcp', 'middle_pip', 'middle_dip', 'middle_tip',
    'ring_mcp', 'ring_pip', 'ring_dip', 'ring_tip',
    'pinky_mcp', 'pinky_pip', 'pinky_dip', 'pinky_tip',
)
KEYPOINT_NAMES = (
    BODY_NAMES + tuple(f'face_{index}' for index in range(68))
    + tuple(f'{side}_{joint}' for side in ('left', 'right') for joint in HAND_NAMES)
)
PALM_POINTS = ('hand_wrist', 'index_mcp', 'middle_mcp', 'ring_mcp', 'pinky_mcp')


def normalize_people(instances, width, height, threshold=0.05):
    """Map MMPose pixels to top-left normalized frame coordinates."""
    people = []
    for instance in instances:
        points = np.asarray(instance['keypoints'], dtype=float)
        scores = np.asarray(instance['keypoint_scores'], dtype=float)
        if points.shape != (133, 2) or scores.shape != (133,):
            raise ValueError('Esperava COCO-WholeBody 133 em 2D, ordem MMPose e 133 escores.')
        tracked = {}
        for name, (x, y), score in zip(KEYPOINT_NAMES, points, scores):
            if not all(map(isfinite, (x, y, score))) or score < threshold:
                continue
            tracked[name] = [x / width, y / height, 0.0, min(1., float(score))]
        for side in ('left', 'right'):
            if f'{side}_big_toe' in tracked:
                tracked[f'{side}_foot_index'] = tracked[f'{side}_big_toe']
            palm = [tracked.get(f'{side}_{joint}') for joint in PALM_POINTS]
            if all(point is not None for point in palm):
                center = np.asarray(palm)
                tracked[f'{side}_palm'] = [
                    *center[:, :3].mean(axis=0).tolist(), float(center[:, 3].min())
                ]
        if tracked:
            people.append({'landmarks': tracked, 'gestures': {}})
    return people


def normalize_video(records, width, height, fps, provider, threshold):
    from .body_pose import PersonTracker

    tracker = PersonTracker(max_gap=max(2, round(fps * .4)))
    frames = {}
    for index, instances, cut in records:
        if cut:
            tracker.reset()
        people = normalize_people(instances, width, height, threshold)
        frames[str(index)] = tracker.assign(people, index, width / height)
    return {
        'provider': provider,
        'fps': fps,
        'resolution': [width, height],
        'frames': frames,
    }


def import_predictions(path, width, height, fps, frame_base, threshold):
    data = json.loads(path.read_text(encoding='utf-8'))
    records = data.get('instance_info') if isinstance(data, dict) else data
    if not isinstance(records, list) or not records:
        raise ValueError('JSON sem lista de instâncias por quadro.')
    indexed = []
    seen = set()
    for frame in records:
        if not isinstance(frame, dict) or type(frame.get('frame_id')) is not int:
            raise ValueError('Cada quadro MMPose precisa de frame_id inteiro.')
        index = frame['frame_id'] - frame_base
        if index < 0 or index in seen or not isinstance(frame.get('instances'), list):
            raise ValueError('Índice de quadro repetido/negativo ou instâncias inválidas.')
        indexed.append((index, frame['instances'], False))
        seen.add(index)
    indexed.sort(key=lambda item: item[0])
    return normalize_video(indexed, width, height, fps, 'mmpose-wholebody', threshold)


def run_rtmw(video, fps, detector, detector_size, pose, pose_size, device, threshold, start, end):
    # Optional inference dependencies are isolated from the lightweight importer.
    try:
        import cv2
        import onnxruntime
        from rtmlib import Wholebody
    except ImportError as exc:
        raise ValueError('Para inferência, instale rtmlib e onnxruntime no ambiente.') from exc
    from .video_anchor import conform, frames_of

    if device == 'cuda' and 'CUDAExecutionProvider' not in onnxruntime.get_available_providers():
        raise ValueError('O ONNX Runtime deste ambiente não oferece o provedor CUDA.')
    model = Wholebody(
        det=str(detector.resolve()), det_input_size=tuple(detector_size),
        pose=str(pose.resolve()), pose_input_size=tuple(pose_size),
        to_openpose=False, backend='onnxruntime', device=device,
    )
    with TemporaryDirectory(prefix='rtmw-video-') as tmp:
        picture = Path(tmp) / 'conformed.mp4'
        conform(video, picture, fps)
        frames = frames_of(picture)
        first = next(frames, None)
        if first is None:
            raise ValueError('Não foi possível decodificar o vídeo.')
        height, width = first.shape[:2]

        def records():
            selected = islice(chain([first], frames), start, end)
            previous = None
            for index, image in enumerate(selected, start):
                thumbnail = cv2.resize(image, (72, 48), interpolation=cv2.INTER_AREA)
                cut = False
                if previous is not None:
                    difference = cv2.absdiff(previous, thumbnail)
                    cut = difference.mean() > 32 and (difference.max(axis=2) > 38).mean() > .42
                previous = thumbnail
                boxes = model.det_model(image)
                if not len(boxes):
                    # RTMPose assumes the entire frame is a crop when passed an empty list.
                    yield index, [], cut
                    continue
                points, scores = model.pose_model(image, bboxes=boxes)
                yield index, [
                    {'keypoints': point, 'keypoint_scores': score}
                    for point, score in zip(points, scores)
                ], cut

        result = normalize_video(records(), width, height, fps, 'rtmw-onnx', threshold)
        if not result['frames']:
            raise ValueError('Nenhum quadro no intervalo pedido.')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--min-score', type=float, default=0.05)
    modes = parser.add_subparsers(dest='mode', required=True)
    exported = modes.add_parser('import', help='Importa JSON --save-predictions de uma WholeBody MMPose.')
    exported.add_argument('source', type=Path)
    exported.add_argument('output', type=Path)
    exported.add_argument('--size', nargs=2, type=int, required=True, metavar=('WIDTH', 'HEIGHT'))
    exported.add_argument('--frame-base', type=int, choices=(0, 1), default=1)
    runtime = modes.add_parser('run', help='Executa detector YOLOX e modelo RTMW ONNX locais.')
    runtime.add_argument('video', type=Path)
    runtime.add_argument('output', type=Path)
    runtime.add_argument('--detector', type=Path, required=True)
    runtime.add_argument('--detector-size', nargs=2, type=int, default=(416, 416))
    runtime.add_argument('--pose', type=Path, required=True)
    runtime.add_argument('--pose-size', nargs=2, type=int, default=(192, 256))
    runtime.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    runtime.add_argument('--frames', nargs=2, type=int, default=(0, None), metavar=('START', 'END'))
    args = parser.parse_args()
    try:
        if not 1 <= args.fps <= 120 or not 0 < args.min_score <= 1:
            raise ValueError('Informe FPS entre 1 e 120 e confiança de entrada em (0, 1].')
        if args.mode == 'import':
            if min(args.size) <= 0 or args.source.resolve() == args.output.resolve():
                raise ValueError('Informe resolução positiva e destino distinto da origem.')
            payload = import_predictions(args.source, *args.size, args.fps, args.frame_base, args.min_score)
        else:
            start, end = args.frames
            if start < 0 or (end is not None and end <= start):
                raise ValueError('Informe intervalo de quadros com fim exclusivo.')
            if min(*args.detector_size, *args.pose_size) <= 0:
                raise ValueError('Dimensões dos modelos precisam ser positivas.')
            if not all(asset.is_file() for asset in (args.video, args.detector, args.pose)):
                raise ValueError('Informe vídeo e modelos ONNX locais.')
            if args.output.resolve() in {asset.resolve() for asset in (args.video, args.detector, args.pose)}:
                raise ValueError('Escolha destino distinto de vídeo e modelos de entrada.')
            payload = run_rtmw(args.video, args.fps, args.detector, args.detector_size,
                               args.pose, args.pose_size, args.device, args.min_score, start, end)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                               encoding='utf-8')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
