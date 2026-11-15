from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import json
ROOT=Path(__file__).resolve().parents[1];fontpath=ROOT/'fonts/MotionReferenciaCondensada-Regular.ttf'
label='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';bold='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
im=Image.new('RGB',(1600,1780),'#f3f0e8');d=ImageDraw.Draw(im)
def text(pos,t,size=25,color='#322f2c',font=label):d.text(pos,t,font=ImageFont.truetype(str(font),size),fill=color)
text((70,45),'MOTION REFERÊNCIA CONDENSADA',38,font=bold)
text((70,102),'Versão 0.100 · fonte instalável · reconstrução experimental',24)
text((70,160),'DESENHO DA REFERÊNCIA → ATLAS GERADO → CONTORNOS → TTF',21)
text((65,210),'QANDAY',310,'#b0000a',fontpath)
text((650,230),'Omad',265,'#b0000a',fontpath)
text((65,530),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',88,'#171717',fontpath)
text((65,650),'abcdefghijklmnopqrstuvwxyz',105,'#171717',fontpath)
text((65,790),'0123456789  . , : ; ? ! + = / ( )',92,'#171717',fontpath)
text((65,925),'À Á Â Ã Ç É Ê Í Ó Ô Õ Ú Ü',105,'#171717',fontpath)
text((65,1050),'à á â ã ç é ê í ó ô õ ú ü',105,'#171717',fontpath)
text((65,1200),'AMANHÃ COMEÇA AGORA',145,'#b0000a',fontpath)
text((65,1380),'Ação, criação e movimento.',120,'#171717',fontpath)
text((70,1570),'O desenho do alfabeto foi gerado e normalizado; não é a fonte original identificada.',23)
text((70,1612),'Acentos e pontuação foram construídos em vetor. Kerning inicial em revisão óptica.',23)
text((70,1660),'Letterings do vídeo são entregues separadamente como SVGs com transparência.',23)
im.save(ROOT/'Previa-Fonte-Motion-V5.png')
print(ROOT/'Previa-Fonte-Motion-V5.png')
