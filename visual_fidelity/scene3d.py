"""Prepare one shot, estimate geometry with MoGe/VGGT and build a Cycles scene."""
import argparse
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image, ImageOps


SCHEMA = 'editor-ultra.scene-geometry.v1'


@contextmanager
def destination_folder(output):
    """Publish a complete result directory, leaving failed attempts unpublished."""
    output = output.resolve()
    if output.exists():
        raise ValueError(f'O destino já existe: {output}. Use outra versão de saída.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{output.name}-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'result'
        stage.mkdir()
        yield stage
        if output.exists():
            raise ValueError(f'O destino foi criado durante o processamento: {output}')
        stage.rename(output)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def prepare(source, output, start=None, end=None, step=12, max_views=12):
    if step < 1 or max_views < 1:
        raise ValueError('Passo e limite de vistas devem ser positivos.')
    source = source.resolve(strict=True)
    frames = []
    with destination_folder(output) as stage:
        if source.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'}:
            if start is not None or end is not None:
                raise ValueError('Os limites de quadros são usados com vídeo.')
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image).convert('RGB')
                image.save(stage / 'view-000.png')
                frames.append({'image': 'view-000.png', 'source_frame': None,
                               'source_time_s': None, 'width': image.width, 'height': image.height})
            fps = None
        else:
            if start is None or end is None or not 0 <= start < end:
                raise ValueError('Selecione um único plano com --start e --end exclusivos no fim.')
            indices = range(start, end, step)
            if len(indices) > max_views:
                raise ValueError(f'O plano seleciona {len(indices)} vistas. Aumente --step ou --max-views.')
            cap = cv2.VideoCapture(str(source))
            try:
                fps = float(cap.get(cv2.CAP_PROP_FPS))
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if not cap.isOpened() or not np.isfinite(fps) or fps <= 0 or end > total:
                    raise ValueError('O vídeo ou o intervalo não pôde ser validado.')
                for i, number in enumerate(indices):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, number)
                    ok, bgr = cap.read()
                    if not ok:
                        raise ValueError(f'Falha ao decodificar o quadro {number}.')
                    name = f'view-{i:03d}.png'
                    if not cv2.imwrite(str(stage / name), bgr):
                        raise OSError(f'Falha ao salvar {name}')
                    pts = float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000
                    frames.append({'image': name, 'source_frame': number,
                                   'source_time_s': pts if np.isfinite(pts) else None,
                                   'width': bgr.shape[1], 'height': bgr.shape[0]})
            finally:
                cap.release()
        manifest = {'schema': 'editor-ultra.shot-views.v1', 'source': str(source),
                    'nominal_fps': fps, 'start': start, 'end': end, 'frames': frames,
                    'notes': ['Vistas de um plano contínuo escolhido pelo operador.',
                              'Os timestamps são os informados pelo decodificador OpenCV.',
                              'Exclua cortes, texto animado e assunto móvel da geometria estática quando necessário.']}
        write_json(stage / 'views.json', manifest)
    return output / 'views.json'


def validate_geometry(result):
    points = np.asarray(result['points'], dtype=np.float32)
    if points.ndim != 4 or points.shape[-1] != 3 or min(points.shape[:3]) < 1:
        raise ValueError('points deve ter formato N × H × W × 3.')
    n, h, w, _ = points.shape
    images = np.asarray(result['images'])
    if images.shape != points.shape or images.dtype != np.uint8:
        raise ValueError('images deve ser RGB uint8 no mesmo raster de points.')
    intrinsics = np.asarray(result['intrinsics'], dtype=np.float32)
    extrinsics = np.asarray(result['extrinsics'], dtype=np.float32)
    if intrinsics.shape != (n, 3, 3) or extrinsics.shape != (n, 3, 4):
        raise ValueError('Câmeras incompatíveis com as vistas.')
    if not np.isfinite(intrinsics).all() or not np.isfinite(extrinsics).all():
        raise ValueError('Câmera com valores não finitos.')
    if np.any(intrinsics[:, (0, 1), (0, 1)] <= 0):
        raise ValueError('As distâncias focais devem ser positivas.')
    if not np.allclose(intrinsics[:, 2], [0, 0, 1], atol=1e-5):
        raise ValueError('Matriz intrínseca fora da convenção pinhole.')
    rotations = extrinsics[:, :, :3]
    if not np.allclose(rotations @ rotations.transpose(0, 2, 1), np.eye(3), atol=1e-3) or not np.allclose(np.linalg.det(rotations), 1, atol=1e-3):
        raise ValueError('As extrínsecas devem conter rotações rígidas com determinante +1.')
    valid = np.asarray(result['valid'], dtype=bool)
    confidence = np.asarray(result.get('confidence', valid.astype(np.float32)), dtype=np.float32)
    if valid.shape != (n, h, w) or confidence.shape != valid.shape:
        raise ValueError('Máscara ou confiança incompatível com o raster.')
    valid = valid & np.isfinite(points).all(axis=-1) & np.isfinite(confidence)
    camera_points = np.einsum('nij,nhwj->nhwi', rotations, np.nan_to_num(points)) + extrinsics[:, None, None, :, 3]
    valid &= camera_points[:, :, :, 2] > 0
    if not valid.any():
        raise ValueError('O modelo não produziu pontos válidos diante da câmera.')
    points = points.copy()
    points[~valid] = np.nan
    confidence = np.where(valid, confidence, 0)
    return dict(points=points, images=images, intrinsics=intrinsics, extrinsics=extrinsics,
                valid=valid, confidence=confidence)


def estimate(manifest_path, output, model, device='auto', checkpoint=None, mask=None, resolution_level=0, num_tokens=None):
    from .scene_inference import infer

    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema') != 'editor-ultra.shot-views.v1' or not manifest.get('frames'):
        raise ValueError('Manifesto de vistas inválido.')
    paths = [(manifest_path.parent / row['image']).resolve(strict=True) for row in manifest['frames']]
    if model == 'moge' and len(paths) != 1:
        raise ValueError('MoGe usa uma vista por reconstrução. Para câmera compartilhada, escolha VGGT.')
    with destination_folder(output) as stage:
        result = infer(model, paths, device=device, checkpoint=checkpoint,
                       resolution_level=resolution_level, num_tokens=num_tokens)
        arrays = validate_geometry(result)
        if mask:
            # This explicit mask is in the MODEL raster, after resize/padding.
            with Image.open(mask) as image:
                valid = np.asarray(image.convert('L')) > 127
            if arrays['valid'].shape[0] != 1 or valid.shape != arrays['valid'].shape[1:]:
                raise ValueError('--mask deve corresponder ao raster de uma única vista processada.')
            arrays['valid'][0] &= valid
            arrays = validate_geometry(arrays)
        if len(paths) != arrays['points'].shape[0]:
            raise ValueError('O modelo mudou o número de vistas.')
        np.savez_compressed(stage / 'geometry.npz', **arrays)
        write_json(stage / 'geometry.json', {
            'schema': SCHEMA, 'provider': model, 'source_manifest': manifest,
            'coordinate_system': 'OpenCV world; x right, y down, z forward at reference camera',
            'extrinsics': 'world-to-camera', 'intrinsics': 'pixel units of processed images',
            'model': result.get('metadata', {}),
            'shape': list(arrays['points'].shape), 'valid_points': int(arrays['valid'].sum()),
            'limitations': ['A geometria é uma estimativa. Revise superfícies e áreas sem observação.',
                            'A cor projetada contém a iluminação da imagem. A iluminação PBR exige ajuste próprio.',
                            'Pessoas e efeitos móveis podem contaminar o ambiente.']})
    return output / 'geometry.npz'


def render(args):
    binary = shutil.which(args.blender)
    if not binary:
        raise ValueError('Blender indisponível. Instale-o ou informe --blender.')
    script = Path(__file__).with_name('blender_scene.py')
    command = [binary, '--background', '--factory-startup', '--threads', '4',
               '--python-exit-code', '1', '--python', str(script), '--',
               str(args.geometry.resolve(strict=True)), str(args.output.resolve()),
               '--view', str(args.view), '--stride', str(args.stride), '--samples', str(args.samples),
               '--material', args.material, '--max-edge-ratio', str(args.max_edge_ratio),
               '--min-confidence', str(args.min_confidence)]
    if args.render:
        command += ['--render', str(args.render.resolve())]
    if args.objects:
        command += ['--objects', str(args.objects.resolve(strict=True))]
    if args.all_views:
        command += ['--all-views']
    if args.animate_cameras:
        command += ['--animate-cameras']
    subprocess.run(command, check=True)


def doctor():
    states = {name: importlib.util.find_spec(name) is not None for name in ('torch', 'moge', 'vggt')}
    cuda = False
    if states['torch']:
        import torch
        cuda = torch.cuda.is_available()
    return {'python': sys.executable, 'blender': shutil.which('blender'), 'packages': states,
            'cuda': cuda, 'note': 'Importabilidade não confirma pesos disponíveis nem inferência executada.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor')
    inputs = commands.add_parser('prepare')
    inputs.add_argument('source', type=Path)
    inputs.add_argument('output', type=Path)
    inputs.add_argument('--start', type=int)
    inputs.add_argument('--end', type=int)
    inputs.add_argument('--step', type=int, default=12)
    inputs.add_argument('--max-views', type=int, default=12)
    inference = commands.add_parser('infer')
    inference.add_argument('views', type=Path)
    inference.add_argument('output', type=Path)
    inference.add_argument('--model', required=True, choices=('moge', 'vggt'))
    inference.add_argument('--device', default='auto', choices=('auto', 'cpu', 'cuda'))
    inference.add_argument('--checkpoint')
    inference.add_argument('--mask', type=Path)
    inference.add_argument('--resolution-level', type=int, default=0, choices=range(10))
    inference.add_argument('--num-tokens', type=int)
    inference.add_argument('--python', help='Python do ambiente opcional de reconstrução.')
    renderer = commands.add_parser('render')
    renderer.add_argument('geometry', type=Path)
    renderer.add_argument('output', type=Path)
    renderer.add_argument('--render', type=Path)
    renderer.add_argument('--blender', default='blender')
    renderer.add_argument('--view', type=int, default=0)
    renderer.add_argument('--stride', type=int, default=4)
    renderer.add_argument('--samples', type=int, default=16)
    renderer.add_argument('--max-edge-ratio', type=float, default=.08)
    renderer.add_argument('--material', choices=('projected', 'pbr'), default='projected')
    renderer.add_argument('--objects', type=Path)
    renderer.add_argument('--all-views', action='store_true')
    renderer.add_argument('--animate-cameras', action='store_true')
    renderer.add_argument('--min-confidence', type=float, default=0)
    args = parser.parse_args()
    try:
        if args.command == 'doctor':
            print(json.dumps(doctor(), ensure_ascii=False, indent=2))
        elif args.command == 'prepare':
            print(prepare(args.source, args.output, args.start, args.end, args.step, args.max_views))
        elif args.command == 'infer':
            if args.python:
                command = [args.python, '-m', 'visual_fidelity.scene3d', 'infer', str(args.views.resolve()),
                           str(args.output.resolve()), '--model', args.model, '--device', args.device,
                           '--resolution-level', str(args.resolution_level)]
                if args.num_tokens is not None:
                    command += ['--num-tokens', str(args.num_tokens)]
                if args.checkpoint:
                    command += ['--checkpoint', args.checkpoint]
                if args.mask:
                    command += ['--mask', str(args.mask.resolve())]
                env = os.environ.copy()
                env['PYTHONPATH'] = str(Path(__file__).resolve().parent.parent)
                subprocess.run(command, check=True, env=env)
            else:
                print(estimate(args.views, args.output, args.model, args.device, args.checkpoint, args.mask,
                               args.resolution_level, args.num_tokens))
        else:
            render(args)
    except (ValueError, OSError, ImportError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
