from pathlib import Path
import sys
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'engine'))
from visual_fidelity.geometric_video import render
render(R/'timeline.json',R/'output/Moto-Aplicacao-330494.mp4')
