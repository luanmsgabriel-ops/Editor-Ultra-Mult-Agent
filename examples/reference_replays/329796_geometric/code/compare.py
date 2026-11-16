"""Create a synchronized stacked comparison without using it as independence proof."""
from pathlib import Path
import subprocess
R=Path(__file__).resolve().parents[1]
font='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
graph=(f"[0:v]transpose=2,pad=1280:766:0:46:color=0x141719,drawtext=fontfile={font}:text='REFERENCIA':x=24:y=10:fontsize=24:fontcolor=white[a];"
       f"[1:v]pad=1280:766:0:46:color=0x141719,drawtext=fontfile={font}:text='RECONSTRUCAO POR CAMADAS':x=24:y=10:fontsize=24:fontcolor=white[b];"
       '[a][b]vstack=shortest=1[v]')
subprocess.run(['ffmpeg','-v','error','-y','-filter_complex_threads','2','-i',str(R/'media/reference.mp4'),'-i',str(R/'output/Moto-Reconstrucao-329796.mp4'),'-filter_complex',graph,'-map','[v]','-map','1:a:0','-c:v','libx264','-preset','fast','-crf','18','-threads','4','-pix_fmt','yuv420p','-c:a','copy','-frames:v','427','-movflags','+faststart',str(R/'output/Comparativo-329796.mp4')],check=True)
