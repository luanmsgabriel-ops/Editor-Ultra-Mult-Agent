"""Run opt-in 3D reconstruction providers in their installed environments."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def runner(executable):
    resolved = shutil.which(executable)
    if not resolved:
        raise ValueError(f'Executável indisponível: {executable}')
    return resolved


def colmap(photos, output, executable, dense=False, gpu=False):
    if not photos.is_dir() or sum(
        f.is_file() and f.suffix.lower() in {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp'}
        for f in photos.rglob('*')
    ) < 3:
        raise ValueError('Disponibilize ao menos três fotos do objeto, de ângulos sobrepostos.')
    if dense and not gpu:
        raise ValueError('O estéreo denso do COLMAP exige --gpu e uma instalação CUDA.')
    binary = runner(executable)
    output.mkdir(parents=True, exist_ok=False)
    database = output / 'matches.db'
    sparse = output / 'sparse'
    sparse.mkdir()

    def gpu_setting(command, prefix):
        help_text = subprocess.run([binary, command, '-h'], check=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True).stdout
        flag = f'--{prefix}.use_gpu'
        if flag not in help_text:
            flag = '--SiftExtraction.use_gpu' if command == 'feature_extractor' else '--SiftMatching.use_gpu'
        if flag not in help_text:
            raise ValueError(f'Opções de GPU do COLMAP desconhecidas para {command}.')
        return [flag, str(int(gpu))]

    def execute(command, *args):
        subprocess.run([binary, command, *map(str, args)], check=True)

    execute('feature_extractor', '--database_path', database, '--image_path', photos,
            *gpu_setting('feature_extractor', 'FeatureExtraction'))
    execute('exhaustive_matcher', '--database_path', database,
            *gpu_setting('exhaustive_matcher', 'FeatureMatching'))
    execute('mapper', '--database_path', database, '--image_path', photos, '--output_path', sparse)
    models = sorted(path for path in sparse.iterdir() if (path / 'images.bin').is_file())
    if not models:
        raise ValueError('Nenhum modelo esparso. Confira sobreposição, foco e textura das fotos.')
    for model in models:
        print(model)
    if dense:
        if len(models) != 1:
            raise ValueError('Vários modelos desconectados. Refaça a captura ou selecione um para densificar.')
        workspace = output / 'dense'
        execute('image_undistorter', '--image_path', photos, '--input_path', models[0],
                '--output_path', workspace, '--output_type', 'COLMAP')
        execute('patch_match_stereo', '--workspace_path', workspace, '--workspace_format', 'COLMAP')
        fused = workspace / 'fused.ply'
        execute('stereo_fusion', '--workspace_path', workspace, '--workspace_format', 'COLMAP',
                '--input_type', 'geometric', '--output_path', fused)
        mesh = workspace / 'mesh.ply'
        execute('poisson_mesher', '--input_path', fused, '--output_path', mesh)
        if not mesh.is_file() or mesh.stat().st_size == 0:
            raise ValueError('A densificação terminou sem uma malha utilizável.')
        print(mesh)


def trellis(image, output, interpreter):
    if not image.is_file():
        raise ValueError(f'Imagem não encontrada: {image}')
    if output.suffix.lower() != '.glb' or output.exists():
        raise ValueError('Informe um destino .glb novo.')
    output.parent.mkdir(parents=True, exist_ok=True)
    worker = Path(__file__).with_name('trellis_export.py')
    subprocess.run([runner(interpreter), str(worker), str(image.resolve()), str(output.resolve())], check=True)
    if not output.is_file() or output.stat().st_size == 0:
        raise ValueError('O exportador terminou sem gerar um GLB.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    backend = parser.add_subparsers(dest='provider', required=True)
    multi = backend.add_parser('colmap')
    multi.add_argument('photos', type=Path)
    multi.add_argument('output', type=Path)
    multi.add_argument('--executable', default='colmap')
    multi.add_argument('--dense', action='store_true')
    multi.add_argument('--gpu', action='store_true')
    single = backend.add_parser('trellis')
    single.add_argument('image', type=Path)
    single.add_argument('output', type=Path)
    single.add_argument('--python', default=sys.executable, help='Python do ambiente TRELLIS.2')
    args = parser.parse_args()
    try:
        if args.provider == 'colmap':
            colmap(args.photos, args.output, args.executable, args.dense, args.gpu)
        else:
            trellis(args.image, args.output, args.python)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
