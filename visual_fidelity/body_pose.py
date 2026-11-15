"""Analyze a local video into normalized, tracked body points and masks."""
import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment


BODY = (
    'nose', 'left_eye_inner', 'left_eye', 'left_eye_outer', 'right_eye_inner',
    'right_eye', 'right_eye_outer', 'left_ear', 'right_ear', 'mouth_left',
    'mouth_right', 'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_pinky', 'right_pinky', 'left_index',
    'right_index', 'left_thumb', 'right_thumb', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle', 'left_heel',
    'right_heel', 'left_foot_index', 'right_foot_index',
)
HAND = (
    'hand_wrist', 'thumb_cmc', 'thumb_mcp', 'thumb_ip', 'thumb_tip', 'index_mcp',
    'index_pip', 'index_dip', 'index_tip', 'middle_mcp', 'middle_pip',
    'middle_dip', 'middle_tip', 'ring_mcp', 'ring_pip', 'ring_dip', 'ring_tip',
    'pinky_mcp', 'pinky_pip', 'pinky_dip', 'pinky_tip',
)
TORSO = ('left_shoulder', 'right_shoulder', 'left_hip', 'right_hip')


def point_value(point, confidence=None):
    if confidence is None:
        confidence = min(value if value is not None else 1
                         for value in (point.visibility, point.presence))
    return [round(point.x, 6), round(point.y, 6), round(point.z, 6),
            round(float(np.clip(confidence, 0, 1)), 5)]


def torso_geometry(landmarks, aspect_ratio):
    points = [landmarks[name] for name in TORSO
              if name in landmarks and landmarks[name][3] >= .3]
    if not points:
        points = [pt for pt in landmarks.values() if pt[3] >= .3]
    if not points:
        return np.zeros(2), 0.
    xy = np.asarray(points)[:, :2] * [aspect_ratio, 1]
    return np.mean(xy, axis=0), max(float(np.linalg.norm(np.ptp(xy, axis=0))), .04)


@dataclass
class Track:
    center: np.ndarray
    scale: float
    velocity: np.ndarray
    frame: int


class PersonTracker:
    """Assign short-term IDs with gated torso position, velocity and scale."""

    def __init__(self, max_gap=12):
        self.max_gap = max_gap
        self.tracks = {}
        self.next_id = 0

    def reset(self):
        self.tracks.clear()

    def assign(self, people, frame, aspect_ratio=1.0):
        self.tracks = {index: state for index, state in self.tracks.items()
                       if frame - state.frame <= self.max_gap}
        geometry = [torso_geometry(person['landmarks'], aspect_ratio)
                    for person in people]
        ids = list(self.tracks)
        cost = np.full((len(ids), len(people)), 1.e4)
        for row, index in enumerate(ids):
            old = self.tracks[index]
            guess = old.center + old.velocity * min(frame-old.frame, 4)
            for col, (center, scale) in enumerate(geometry):
                distance = np.linalg.norm(center - guess)
                if scale and old.scale and distance <= max(.055, .65*max(old.scale, scale)):
                    cost[row, col] = distance / max(scale, old.scale) + .22*abs(np.log(scale/old.scale))
        rows, cols = linear_sum_assignment(cost)
        assigned = {col: ids[row] for row, col in zip(rows, cols) if cost[row, col] < 1.e4}
        for col, (person, (center, scale)) in enumerate(zip(people, geometry)):
            index = assigned.get(col)
            if index is None:
                index = self.next_id
                self.next_id += 1
                velocity = np.zeros(2)
            else:
                old = self.tracks[index]
                velocity = .4*old.velocity + .6*(center-old.center)/max(1, frame-old.frame)
            self.tracks[index] = Track(center, scale, velocity, frame)
            person['id'] = index
        return people


def attach_hands(people, result, aspect_ratio):
    """Match detected hands to posed wrists so crossing hands do not rely on label order."""
    wrists = [(person, side, person['landmarks'].get(f'{side}_wrist'))
              for person in people for side in ('left', 'right')]
    wrists = [(person, side, point) for person, side, point in wrists
              if point is not None and point[3] >= .25]
    cost = np.full((len(wrists), len(result.hand_landmarks)), 1.e4)
    for row, (person, side, wrist) in enumerate(wrists):
        scale = torso_geometry(person['landmarks'], aspect_ratio)[1]
        for col, hand in enumerate(result.hand_landmarks):
            delta = (np.asarray(wrist[:2]) - [hand[0].x, hand[0].y]) * [aspect_ratio, 1]
            distance = float(np.linalg.norm(delta))
            if distance <= max(.035, .55*scale):
                handedness = result.handedness[col]
                mismatch = handedness and handedness[0].category_name.lower() != side
                cost[row, col] = distance + (.018 if mismatch else 0)
    rows, cols = linear_sum_assignment(cost)
    for row, col in zip(rows, cols):
        if cost[row, col] >= 1.e4:
            continue
        person, side, wrist = wrists[row]
        landmarks = person['landmarks']
        for name, point in zip(HAND, result.hand_landmarks[col]):
            # MediaPipe Hands provides no per-point visibility. Use the pose wrist
            # confidence, so this value reports association support.
            landmarks[f'{side}_{name}'] = point_value(point, wrist[3])
        palm = np.asarray([landmarks[f'{side}_{name}'] for name in (
            'hand_wrist', 'index_mcp', 'middle_mcp', 'ring_mcp', 'pinky_mcp',
        )])
        landmarks[f'{side}_palm'] = np.mean(palm, axis=0).round(6).tolist()
        category = result.gestures[col]
        if category and category[0].category_name != 'None' and category[0].score >= .55:
            person['gestures'][side] = category[0].category_name
            person.setdefault('gesture_scores', {})[side] = round(category[0].score, 5)


def video_size(source, max_dimension):
    reader = cv2.VideoCapture(str(source))
    try:
        ok, frame = reader.read()
    finally:
        reader.release()
    if not ok:
        raise ValueError('Não foi possível decodificar a mídia para extrair pose.')
    height, width = frame.shape[:2]
    factor = min(1., max_dimension / max(height, width))
    return max(2, round(width*factor)), max(2, round(height*factor))


def rgb_frames(source, fps, size, limit=None):
    width, height = size
    bytes_per_frame = width*height*3
    command = ['ffmpeg', '-nostdin', '-v', 'error', '-i', str(source),
               '-map', '0:v:0', '-an', '-vf', f'fps={fps},scale={width}:{height},setsar=1',
               '-pix_fmt', 'rgb24', '-threads', '1']
    if limit:
        command.extend(['-frames:v', str(limit)])
    command.extend(['-f', 'rawvideo', '-'])
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        try:
            for raw in iter(lambda: process.stdout.read(bytes_per_frame), b''):
                if len(raw) != bytes_per_frame:
                    raise ValueError('O FFmpeg retornou um quadro incompleto.')
                yield np.frombuffer(raw, np.uint8).reshape(height, width, 3)
            if process.wait():
                raise ValueError('O FFmpeg encerrou com erro ao preparar os quadros.')
        finally:
            if process.poll() is None:
                process.kill()


def mask_pixels(image):
    return np.rint(np.clip(image.numpy_view(), 0, 1)*255).astype('uint8')


def save_masks(masks, people, destination, frame, per_person, shape):
    masks = [mask_pixels(mask) for mask in (masks if masks is not None else [])]
    merged = np.maximum.reduce(masks) if masks else np.zeros(shape, dtype='uint8')
    name = f'{frame:06d}.png'
    if not cv2.imwrite(str(destination/name), merged):
        raise ValueError(f'Falha ao gravar máscara {name}.')
    if per_person:
        for person, mask in zip(people, masks):
            folder = destination/str(person['id'])
            folder.mkdir(exist_ok=True)
            if not cv2.imwrite(str(folder/name), mask):
                raise ValueError(f'Falha ao gravar máscara individual {name}.')


def analyze(source, output, model, gesture_model=None, masks=None,
            per_person=False, fps=30, persons=4, max_dimension=640, limit=None):
    try:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
    except ImportError as error:
        raise ValueError('Instale MediaPipe Tasks para usar este provedor de pose.') from error
    if not model.is_file() or gesture_model is not None and not gesture_model.is_file():
        raise ValueError('Informe arquivos de modelo MediaPipe existentes.')
    if masks is None and per_person:
        raise ValueError('--person-masks precisa de uma pasta --masks.')
    if masks is not None:
        masks.mkdir(parents=True, exist_ok=True)
    width, height = size = video_size(source, max_dimension)
    tracker = PersonTracker(max_gap=max(2, round(fps*.4)))
    saved, previous = {}, None
    cuts = [0]
    with ExitStack() as resources:
        pose = resources.enter_context(vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(model)), num_poses=persons,
                running_mode=vision.RunningMode.VIDEO, output_segmentation_masks=masks is not None,
            )))
        hands = resources.enter_context(vision.GestureRecognizer.create_from_options(
            vision.GestureRecognizerOptions(
                base_options=BaseOptions(model_asset_path=str(gesture_model)),
                running_mode=vision.RunningMode.VIDEO, num_hands=2*persons,
            ))) if gesture_model else None
        for index, pixels in enumerate(rgb_frames(source, fps, size, limit)):
            thumb = cv2.resize(pixels, (72, 48), interpolation=cv2.INTER_AREA)
            if previous is not None:
                difference = cv2.absdiff(previous, thumb)
                if difference.mean() > 32 and (difference.max(axis=2) > 38).mean() > .42:
                    tracker.reset()
                    cuts.append(index)
            previous = thumb
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=pixels)
            timestamp = round(index * 1000 / fps)
            result = pose.detect_for_video(image, timestamp)
            people = [{'landmarks': {name: point_value(point)
                                     for name, point in zip(BODY, path)},
                       'gestures': {}} for path in result.pose_landmarks]
            tracker.assign(people, index, width/height)
            if hands is not None and people:
                attach_hands(people, hands.recognize_for_video(image, timestamp), width/height)
            if masks is not None:
                save_masks(result.segmentation_masks, people, masks, index,
                           per_person, (height, width))
            saved[str(index)] = people
    if not saved:
        raise ValueError('Nenhum quadro foi decodificado.')
    report = {'fps': fps, 'resolution': list(size), 'provider': 'mediapipe',
              'shots': cuts, 'frames': saved}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', encoding='utf-8') as file:
        json.dump(report, file, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        file.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--gesture-model', type=Path)
    parser.add_argument('--masks', type=Path)
    parser.add_argument('--person-masks', action='store_true')
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--persons', type=int, default=4)
    parser.add_argument('--max-dimension', type=int, default=640)
    parser.add_argument('--limit', type=int, help='Analise apenas os primeiros N quadros.')
    args = parser.parse_args()
    if not (1 <= args.fps <= 120 and 1 <= args.persons <= 16
            and 96 <= args.max_dimension <= 2048 and (args.limit is None or args.limit >= 1)):
        parser.error('Limites: fps 1–120, pessoas 1–16, dimensão 96–2048 e ao menos um quadro.')
    if args.source.resolve() == args.output.resolve():
        parser.error('Escolha um destino separado do vídeo original.')
    try:
        analyze(args.source, args.output, args.model, args.gesture_model, args.masks,
                args.person_masks, args.fps, args.persons, args.max_dimension, args.limit)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
