"""Install the optional MoGe-2/VGGT stack in a dedicated Python environment."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import venv

MOGE_REVISION = 'b942f00bdc2a2a23ebb474fbe034d487e6dcceec'
VGGT_REVISION = 'a288dd0f14786c93483e45524328726ab7b1b4ce'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', type=Path)
    parser.add_argument('--backend', choices=('cpu', 'cu124'), default='cpu')
    args = parser.parse_args()
    environment = args.environment.expanduser().resolve()
    if environment == Path(sys.prefix).resolve():
        parser.error('Escolha um ambiente dedicado, diferente do Python em execução.')
    if environment.exists() and not (environment/'pyvenv.cfg').is_file():
        parser.error('O destino já existe e não é um ambiente virtual Python.')
    if not environment.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    python = environment/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    pip = [str(python), '-m', 'pip', 'install']
    subprocess.run(pip + ['--upgrade', 'pip'], check=True)
    installed = subprocess.run(
        [str(python), '-c', 'import torch; print(torch.version.cuda or "cpu")'],
        text=True, capture_output=True, check=False)
    requested_backend = 'cpu' if args.backend == 'cpu' else '12.4'
    torch_options = []
    if installed.returncode == 0 and installed.stdout.strip() != requested_backend:
        torch_options.append('--force-reinstall')
    subprocess.run(pip + torch_options + ['torch==2.6.0', 'torchvision==0.21.0', '--index-url',
                          f'https://download.pytorch.org/whl/{args.backend}'], check=True)
    subprocess.run(pip + ['-r', str(Path(__file__).with_name('scene3d-requirements.txt'))], check=True)
    # Upstream demo dependencies include Gradio, GUI OpenCV variants and optional
    # training utilities. The adapters use only the inference dependencies above.
    sources = [
        f'git+https://github.com/microsoft/MoGe.git@{MOGE_REVISION}',
        f'git+https://github.com/facebookresearch/vggt.git@{VGGT_REVISION}',
    ]
    subprocess.run(pip + ['--no-deps', *sources], check=True)
    probe = 'import torch; from moge.model.v2 import MoGeModel; from vggt.models.vggt import VGGT; print(torch.__version__)'
    subprocess.run([str(python), '-c', probe], check=True)
    record = {'python': str(python), 'backend': args.backend,
              'moge_revision': MOGE_REVISION, 'vggt_revision': VGGT_REVISION,
              'weights_downloaded_by_installer': False}
    (environment/'editor-scene-models.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
