"""Render portable anchor match cuts, brief flashes and SDR monochrome looks."""

import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile


def valid_io(inputs, output):
    for source in inputs:
        if not source.is_file():
            raise ValueError(f'Arquivo de entrada ausente: {source}')
    if output.resolve() in {source.resolve() for source in inputs}:
        raise ValueError('O destino precisa ser distinto dos arquivos de entrada.')
    output.parent.mkdir(parents=True, exist_ok=True)


def video_geometry(source):
    args = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,sample_aspect_ratio:stream_side_data=rotation',
        '-of', 'json', str(source),
    ]
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    streams = json.loads(result.stdout).get('streams', [])
    if not streams or not all(streams[0].get(key) for key in ('width', 'height')):
        raise ValueError(f'Nenhum quadro de vídeo em {source}.')
    meta = streams[0]
    width, height = meta['width'], meta['height']
    sar = meta.get('sample_aspect_ratio', '1:1').split(':')
    if len(sar) == 2 and all(item.isdecimal() and int(item) for item in sar):
        width = width * int(sar[0]) / int(sar[1])
    if any(abs(side.get('rotation', 0)) % 180 == 90 for side in meta.get('side_data_list', [])):
        width, height = height, width
    return width, height


def fit_anchor(source_size, output_size, anchor, target):
    """Return a cover scale and crop to align an image point to the destination."""
    width, height = source_size
    out_w, out_h = output_size
    axes = zip((width, height), (out_w, out_h), anchor, target)
    scale = max(out_w / width, out_h / height)
    for original, output, position, goal in axes:
        if not all(math.isfinite(x) and 0 <= x <= 1 for x in (position, goal)):
            raise ValueError('As âncoras usam coordenadas normalizadas entre 0 e 1.')
        for current, desired in ((position, goal), (1 - position, 1 - goal)):
            if desired == 0:
                continue
            if current == 0:
                raise ValueError('Uma âncora na borda da origem precisa coincidir com a borda do destino.')
            scale = max(scale, output * desired / (original * current))
    scaled_w = 2 * math.ceil(width * scale / 2)
    scaled_h = 2 * math.ceil(height * scale / 2)
    crop_x = min(scaled_w - out_w, max(0, round(scaled_w * anchor[0] - out_w * target[0])))
    crop_y = min(scaled_h - out_h, max(0, round(scaled_h * anchor[1] - out_h * target[1])))
    return scaled_w, scaled_h, crop_x, crop_y


def transition(a, b, output, size, fps, anchors, target, flash_frames=0, flash_mark=None):
    """Render two prepared shots with a matched point and an optional flash insert."""
    valid_io([a, b] + ([flash_mark] if flash_mark else []), output)
    width, height = size
    if min(size) < 2 or width % 2 or height % 2 or not 1 <= fps <= 120:
        raise ValueError('Informe largura e altura pares e FPS entre 1 e 120.')
    if flash_frames < 0:
        raise ValueError('O número de quadros do flash não pode ser negativo.')
    if flash_mark and not flash_frames:
        raise ValueError('Use pelo menos um quadro para inserir uma marca no flash.')
    ffmpeg = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(a), '-i', str(b)]
    stages = []
    for index, (source, anchor) in enumerate(zip((a, b), anchors)):
        w, h, x, y = fit_anchor(video_geometry(source), size, anchor, target)
        stages.append(
            f'[{index}:v]fps={fps},scale={w}:{h},crop={width}:{height}:{x}:{y}:exact=1,'
            f'setsar=1,format=yuv420p,setpts=PTS-STARTPTS[p{index}]'
        )
    if flash_frames:
        stages.append(
            f'color=c=white:s={width}x{height}:r={fps},trim=end_frame={flash_frames},'
            'setsar=1,setpts=PTS-STARTPTS[white]'
        )
        if flash_mark:
            ffmpeg += ['-i', str(flash_mark)]
            mark_w = max(2, 2 * round(width * .128 / 2))
            stages += [
                f'[2:v]scale={mark_w}:-2,format=rgba[mark]',
                '[white][mark]overlay='
                f'x={width*target[0]:.6f}-overlay_w/2:y={height*target[1]:.6f}-overlay_h/2:'
                'eof_action=repeat[flash]',
            ]
        else:
            stages.append('[white]null[flash]')
        sequence = '[p0][flash][p1]'
        count = 3
    else:
        sequence = '[p0][p1]'
        count = 2
    stages.append(
        f'{sequence}concat=n={count}:v=1:a=0,settb=1/{fps},setpts=N[display]'
    )
    ffmpeg += [
        '-filter_complex_threads', '2', '-filter_complex', ';'.join(stages),
        '-map', '[display]', '-an', '-r', str(fps), '-fps_mode', 'cfr', '-c:v', 'libx264', '-threads', '3',
        '-preset', 'fast', '-crf', '17', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', str(output),
    ]
    subprocess.run(ffmpeg, check=True)


def monochrome(red, green, blue, contrast, pivot, black, white):
    luminance = .2126 * red + .7152 * green + .0722 * blue
    curve = min(1, max(0, (luminance - pivot) * contrast + pivot))
    return black + (white - black) * curve


def write_cube(destination, side=17, contrast=1.26, pivot=.46, black=.012, white=.992):
    """Write an authored SDR look. Red is the fastest-moving .cube coordinate."""
    if not 2 <= side <= 65:
        raise ValueError('Informe tamanho de LUT entre 2 e 65.')
    if not all(math.isfinite(x) for x in (contrast, pivot, black, white)):
        raise ValueError('Use parâmetros de cor finitos.')
    if not (0 < contrast and 0 <= pivot <= 1 and 0 <= black < white <= 1):
        raise ValueError('O contraste precisa ser positivo e pivô e limites devem estar entre 0 e 1.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    points = [n / (side - 1) for n in range(side)]
    with destination.open('w', encoding='ascii', newline='\n') as lut:
        lut.write('TITLE "Editor Ultra - Monochrome High Contrast"\n')
        lut.write(f'LUT_3D_SIZE {side}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        for blue in points:
            for green in points:
                for red in points:
                    gray = monochrome(red, green, blue, contrast, pivot, black, white)
                    lut.write(f'{gray:.7f} {gray:.7f} {gray:.7f}\n')


def apply_cube(source, lut, destination):
    """Apply a local .cube to SDR source, retaining the optional audio streams."""
    valid_io([source, lut], destination)
    if lut.suffix.lower() != '.cube':
        raise ValueError('Informe um LUT em formato .cube.')
    with tempfile.TemporaryDirectory(prefix='editor-lut-') as stage:
        shutil.copyfile(lut, Path(stage) / 'look.cube')
        command = [
            'ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source.resolve()),
            '-map', '0:v:0', '-map', '0:a?',
            '-vf', 'format=gbrp,lut3d=file=look.cube:interp=tetrahedral,format=yuv420p',
            '-c:v', 'libx264', '-threads', '3', '-preset', 'fast', '-crf', '17',
            '-c:a', 'aac', '-movflags', '+faststart', str(destination.resolve()),
        ]
        subprocess.run(command, cwd=stage, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='mode', required=True)
    cut = commands.add_parser('transition', help='Corta entre dois clipes com âncora alinhada.')
    cut.add_argument('before', type=Path)
    cut.add_argument('after', type=Path)
    cut.add_argument('output', type=Path)
    cut.add_argument('--size', type=int, nargs=2, default=(720, 1280), metavar=('W', 'H'))
    cut.add_argument('--fps', type=int, default=30)
    cut.add_argument('--anchor-before', type=float, nargs=2, default=(.5, .5))
    cut.add_argument('--anchor-after', type=float, nargs=2, default=(.5, .5))
    cut.add_argument('--target', type=float, nargs=2, default=(.5, .5))
    cut.add_argument('--flash-frames', type=int, default=0)
    cut.add_argument('--flash-mark', type=Path, help='PNG RGBA opcional, separado da referência.')
    cube = commands.add_parser('cube', help='Gera um LUT autoral P&B de alto contraste.')
    cube.add_argument('output', type=Path)
    cube.add_argument('--side', type=int, default=17)
    cube.add_argument('--contrast', type=float, default=1.26)
    cube.add_argument('--pivot', type=float, default=.46)
    cube.add_argument('--black', type=float, default=.012)
    cube.add_argument('--white', type=float, default=.992)
    color = commands.add_parser('color', help='Aplica um arquivo .cube a um clipe SDR.')
    color.add_argument('source', type=Path)
    color.add_argument('lut', type=Path)
    color.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.mode == 'transition':
            transition(args.before, args.after, args.output, args.size, args.fps,
                       (args.anchor_before, args.anchor_after), args.target, args.flash_frames, args.flash_mark)
        elif args.mode == 'cube':
            write_cube(args.output, args.side, args.contrast, args.pivot, args.black, args.white)
        else:
            apply_cube(args.source, args.lut, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
