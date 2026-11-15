"""Avalie quadros-chave e exporte a velocidade do movimento em pixels por segundo."""

from argparse import ArgumentParser
import csv
from dataclasses import dataclass
import json
from math import hypot, isclose, isfinite
from pathlib import Path
import sys


CURVES = {
    'linear': (0, 0, 1, 1),
    'ease-in': (.42, 0, 1, 1),
    'ease-out': (0, 0, .58, 1),
    'ease-in-out': (.42, 0, .58, 1)
}


def _component(t, a, b):
    inv = 1 - t
    return 3 * inv**2 * t * a + 3 * inv * t**2 * b + t**3


def controls(curve):
    if isinstance(curve, str):
        if curve not in CURVES:
            raise ValueError(f'Curva de movimento não reconhecida: {curve}')
        curve = CURVES[curve]
    if not isinstance(curve, (list, tuple)) or len(curve) != 4:
        raise ValueError('Use um nome de easing ou quatro controles Bézier.')
    if any(type(value) not in (int, float) or not isfinite(value) for value in curve):
        raise ValueError('Os controles precisam ser números finitos.')
    if any(not 0 <= value <= 1 for value in (curve[0], curve[2])):
        raise ValueError('Os controles x da Bézier devem estar entre 0 e 1.')
    return curve


def ease(p, curve):
    if p in (0, 1):
        return p
    x1, y1, x2, y2 = curve
    if x1 == y1 and x2 == y2:
        return p
    lo, hi = 0., 1.
    for _ in range(25):
        mid = (lo + hi) / 2
        if _component(mid, x1, x2) < p:
            lo = mid
        else:
            hi = mid
    return _component((lo + hi) / 2, y1, y2)


@dataclass(frozen=True)
class Keyframe:
    frame: int
    x: float
    y: float
    easing: str | list
    cut: bool


def _keyframes(payload, canvas, normalized):
    if normalized and canvas is None:
        raise ValueError('Coordenadas normalizadas exigem resolution [largura, altura].')
    width, height = canvas if normalized else (1, 1)
    keys = []
    for key in payload:
        try:
            frame, x, y = key['frame'], key['x'], key['y']
        except KeyError as exc:
            raise ValueError('Cada quadro-chave precisa de frame, x e y.') from exc
        if type(frame) is not int or frame < 0:
            raise ValueError('frame deve ser um inteiro não negativo.')
        if keys and keys[-1].frame >= frame:
            raise ValueError('Os quadros-chave precisam estar em ordem estritamente crescente.')
        if any(type(value) not in (int, float) or not isfinite(value) for value in (x, y)):
            raise ValueError('As posições precisam ser números finitos.')
        keys.append(Keyframe(frame, x * width, y * height, key.get('ease', 'linear'),
                             bool(key.get('cut_before', False))))
    return keys


def _anchor_tracks(report):
    cuts = sorted(report.get('shot_starts', []))
    tracks = []
    for index, effect in enumerate(report['effects']):
        centers = sorted((int(frame), xy) for frame, xy in effect.get('sample_centers', {}).items())
        before = None
        keys = []
        for frame, xy in centers:
            keys.append({'frame': frame, 'x': xy[0], 'y': xy[1],
                         'cut_before': before is not None and any(before < cut <= frame for cut in cuts)})
            before = frame
        if keys:
            tracks.append({'id': effect.get('layer', str(index)), 'keyframes': keys,
                           'normalized': True, 'mode': 'observed'})
    return tracks


def _sample(track_id, fps, frame, x, y, vx=None, vy=None):
    return {'track': track_id, 'frame': frame, 'time_s': round(frame / fps, 6),
            'x_px': round(x, 5), 'y_px': round(y, 5),
            'vx_px_s': None if vx is None else round(vx, 5),
            'vy_px_s': None if vy is None else round(vy, 5),
            'speed_px_s': None if vx is None else round(hypot(vx, vy), 5)}


def track_motion(track, canvas, fps):
    track_id = track['id']
    keys = _keyframes(track['keyframes'], canvas, bool(track.get('normalized')))
    if not keys:
        raise ValueError(f'A trilha {track_id!r} não tem quadros-chave.')
    mode = track.get('mode', 'design')
    if mode not in ('design', 'observed'):
        raise ValueError('mode deve ser design ou observed.')
    observed = mode == 'observed'
    first = keys[0]
    samples = [_sample(track_id, fps, first.frame, first.x, first.y)]
    segments = []
    for start, end in zip(keys, keys[1:]):
        n = end.frame - start.frame
        span = {'from_frame': start.frame, 'to_frame': end.frame, 'duration_s': round(n / fps, 6)}
        if end.cut:
            samples.append(_sample(track_id, fps, end.frame, end.x, end.y))
            segments.append({**span, 'status': 'cut'})
            continue
        dx, dy = end.x - start.x, end.y - start.y
        if observed:
            sample = _sample(track_id, fps, end.frame, end.x, end.y, dx * fps / n, dy * fps / n)
            samples.append(sample)
            segments.append({**span, 'status': 'between_observations' if n > 1 else 'measured',
                             'mean_displacement_speed_px_s': sample['speed_px_s']})
            continue

        curve = controls(start.easing)
        series = []
        old_x, old_y = start.x, start.y
        for i in range(1, n + 1):
            weight = ease(i / n, curve)
            x, y = start.x + dx * weight, start.y + dy * weight
            sample = _sample(track_id, fps, start.frame + i, x, y,
                             (x - old_x) * fps, (y - old_y) * fps)
            samples.append(sample)
            series.append(sample['speed_px_s'])
            old_x, old_y = x, y
        peak = max(series)
        span['peak_speed_px_s'] = peak
        span['first_speed_px_s'], span['last_speed_px_s'] = series[0], series[-1]
        span.update(status='calculated', easing=start.easing)
        warnings = []
        if n >= 4 and peak > 1 and not track.get('continuous'):
            if all(isclose(speed, peak, rel_tol=.0001) for speed in series):
                warnings.append('velocidade_constante')
            if series[0] / peak > .60 and (start is keys[0] or start.cut):
                warnings.append('entrada_rapida')
            if series[-1] / peak > .60 and end is keys[-1]:
                warnings.append('chegada_rapida')
        span['warnings'] = warnings
        segments.append(span)
    return {'id': track_id, 'mode': 'observed' if observed else 'design', 'segments': segments}, samples


def audit(data):
    fps = data.get('fps')
    if type(fps) not in (int, float) or not isfinite(fps) or not 0 < fps <= 240:
        raise ValueError('Informe fps como número positivo de até 240.')
    canvas = data.get('resolution')
    if canvas is not None and (not isinstance(canvas, list) or len(canvas) != 2
                               or any(type(value) is not int or value <= 0 for value in canvas)):
        raise ValueError('resolution deve conter largura e altura positivas em inteiros.')
    tracks = data.get('tracks')
    tracks = _anchor_tracks(data) if tracks is None and 'effects' in data else tracks
    if not isinstance(tracks, list) or not tracks:
        raise ValueError('Informe tracks com quadros-chave ou um relatório anchor com amostras.')
    audits = []
    rows = []
    for track in tracks:
        result, samples = track_motion(track, canvas, fps)
        audits.append(result)
        rows.extend(samples)
    return {'fps': fps, 'resolution': canvas, 'tracks': audits}, rows


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='JSON de quadros-chave ou relatório produzido por anchor.')
    parser.add_argument('--output', type=Path, help='Grava o relatório JSON neste caminho.')
    parser.add_argument('--csv', type=Path, help='Grava as posições e velocidades por quadro.')
    args = parser.parse_args(argv)
    paths = [path.resolve() for path in (args.source, args.output, args.csv) if path is not None]
    if len(set(paths)) != len(paths):
        parser.error('Use caminhos distintos para o JSON de entrada, o relatório e o CSV.')
    try:
        data = json.loads(args.source.read_text(encoding='utf-8'))
        report, samples = audit(data)
        result = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result, encoding='utf-8')
        else:
            print(result, end='')
        if args.csv:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            with args.csv.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(samples[0]))
                writer.writeheader()
                writer.writerows(samples)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
