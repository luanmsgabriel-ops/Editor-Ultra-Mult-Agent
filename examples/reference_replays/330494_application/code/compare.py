from pathlib import Path
import subprocess
R=Path(__file__).resolve().parents[1]
f='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
g=(f"[0:v]pad=720:1330:0:50:color=0x141719,drawtext=fontfile={f}:text='BRUTO FLOW':x=25:y=14:fontsize=25:fontcolor=white[a];"
   f"[1:v]pad=720:1330:0:50:color=0x141719,drawtext=fontfile={f}:text='MOTOR APLICADO':x=25:y=14:fontsize=25:fontcolor=white[b];[a][b]hstack=shortest=1[v]")
subprocess.run(['ffmpeg','-v','error','-y','-filter_complex_threads','2','-i',str(R/'media/source.mp4'),'-i',str(R/'output/Moto-Aplicacao-330494.mp4'),'-filter_complex',g,'-map','[v]','-map','1:a:0','-c:v','libx264','-crf','18','-preset','fast','-threads','3','-pix_fmt','yuv420p','-c:a','copy','-frames:v','240','-movflags','+faststart',str(R/'output/Antes-Depois-330494.mp4')],check=True)
