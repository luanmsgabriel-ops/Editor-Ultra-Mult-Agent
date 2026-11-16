from pathlib import Path
import subprocess
R=Path(__file__).resolve().parents[1]
f='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
g=(f"[0:v]pad=720:1330:0:50:color=0x141719,drawtext=fontfile={f}:text='V1 - ANTERIOR':x=25:y=14:fontsize=25:fontcolor=white[a];"
   f"[1:v]pad=720:1330:0:50:color=0x141719,drawtext=fontfile={f}:text='V2 - RITMO E CENAS':x=25:y=14:fontsize=25:fontcolor=white[b];[a][b]hstack=shortest=1[v]")
subprocess.run(['ffmpeg','-v','error','-y','-filter_complex_threads','2','-i',str(R/'media/v1-review.mp4'),'-i',str(R/'output/Moto-330494-V2-Ritmo-e-Cenas.mp4'),'-filter_complex',g,'-map','[v]','-map','1:a:0','-c:v','libx264','-crf','18','-preset','fast','-threads','3','-pix_fmt','yuv420p','-c:a','copy','-frames:v','240','-movflags','+faststart',str(R/'output/Comparacao-V1-V2-330494.mp4')],check=True)
