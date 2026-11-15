"""Editor Ultra Multi-Agent: calibração, reconstrução e avaliação visual."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('typography','cap','asset','reconstruct','origins','measure','anchor','blender-anchors','glyph-profile','body-pose','body-rtmw'),
                        help='Escolha a operação; use COMANDO --help para ver as opções.')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command in {'cap','asset','blender-anchors'}:
        blender = shutil.which('blender')
        if not blender:
            parser.exit(1, 'Blender indisponível no PATH.\n')
        script = Path(__file__).with_name('blender_anchors.py' if args.command == 'blender-anchors' else f'blender_{args.command}.py')
        command = [blender, '--background', '--factory-startup', '--threads', '6',
                   '--python-exit-code', '1', '--python', str(script), '--', *args.arguments]
    else:
        module = {'origins':'origins.render','measure':'origins.measure','anchor':'video_anchor','glyph-profile':'glyph_profile','body-pose':'body_pose','body-rtmw':'body_rtmw'}.get(args.command,args.command)
        command = [sys.executable,'-m',f'visual_fidelity.{module}',*args.arguments]
    raise SystemExit(subprocess.call(command))


if __name__ == '__main__':
    main()
