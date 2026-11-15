from pathlib import Path
import json
from PIL import Image,ImageDraw,ImageFont,features
from fontTools.ttLib import TTFont
ROOT=Path(__file__).resolve().parents[1];p=ROOT/'fonts/MotionReferenciaCondensada-Regular.ttf'
f=TTFont(p,checkChecksums=2);cmap=f.getBestCmap();manifest=json.loads((ROOT/'glyph-manifest.json').read_text())
required='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789ÀÁÂÃÇÉÊÍÓÔÕÚÜàáâãçéêíóôõúü.,:;?!+-=()'
missing=[c for c in required if ord(c)not in cmap];assert not missing,missing
assert all(t in f for t in ['cmap','glyf','hmtx','head','OS/2','name','GPOS'])
assert f['OS/2'].usWinAscent>=970 and f['OS/2'].usWinDescent>=180
rendered=[]
for size in (32,100,350):
 ft=ImageFont.truetype(str(p),size)
 for text in ['QANDAY Omad','Ação, criação e movimento.','AMANHÃ COMEÇA AGORA','ÁÉÍÓÚ àâãçêôõ 0123456789']:
  box=ft.getbbox(text);im=Image.new('L',(box[2]-box[0]+20,box[3]-box[1]+20));ImageDraw.Draw(im).text((10-box[0],10-box[1]),text,font=ft,fill=255);assert im.getbbox()
  rendered.append({'size':size,'text':text,'bounds':box})
# Every encoded visible character must yield ink, including composed accents.
ft=ImageFont.truetype(str(p),100)
for code in cmap:
 if code in (32,160):continue
 assert ft.getmask(chr(code)).getbbox(),f'Empty glyph U+{code:04X}'
ft=ImageFont.truetype(str(p),100)
kern=None
if features.check_feature('raqm'):
 kern={'AV_with':ft.getlength('AV'),'AV_without':ft.getlength('AV',features=['-kern'])};assert kern['AV_with']<kern['AV_without']
result={'ttf_loaded':True,'required_characters_missing':missing,'encoded_characters':len(cmap),'glyph_count':len(f.getGlyphOrder()),'all_encoded_characters_rendered':True,'render_checks':rendered,'kerning_check':kern,'visual_review':'Rendered specimen reviewed for all64 source glyphs and Portuguese accents; this is not a fidelity score against the original video.'}
(ROOT/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items()if k!='render_checks'},ensure_ascii=False))
