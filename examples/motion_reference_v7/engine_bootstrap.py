"""Load the versioned engine snapshot supplied alongside this project."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
engine=ROOT/'engine'
if not (engine/'visual_fidelity').is_dir():
    engine=ROOT.parent/'motor-v7'  # isolated development checkout only
if not (engine/'visual_fidelity').is_dir():
    raise RuntimeError('Motor ausente: restaure o diretório engine do pacote.')
sys.path.insert(0,str(engine))
