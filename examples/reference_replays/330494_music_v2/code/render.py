from pathlib import Path
import sys
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'engine'))
from visual_fidelity.geometric_video import render
render(R/'timeline.json',R/'output/Moto-330494-V2-Ritmo-e-Cenas.mp4')
