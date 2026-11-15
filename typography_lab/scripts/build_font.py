"""Build a real TTF from the generated alpha glyph atlas; no source font substituted."""
from pathlib import Path
import json,unicodedata,math,argparse
import cv2,numpy as np
from PIL import Image
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.cu2quPen import Cu2QuPen
from curve_fit import fit
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
ROOT=Path(__file__).resolve().parents[1]
ATLAS=None
ROWS=['ABCDEFGH','IJKLMNOP','QRSTUVWX','YZabcdef','ghijklmn','opqrstuv','wxyz0123','456789?!']

def bands(proj,threshold):
 ids=np.where(proj>threshold)[0];out=[]
 for i in ids:
  if not out or i>out[-1][-1]+1:out.append([int(i)])
  else:out[-1].append(int(i))
 return [(r[0],r[-1]+1)for r in out]

def poly(pen,pts):
 # Retain measured geometry, round only up to 2 font units at traced vertices.
 pts=np.array(pts,float);starts=[];ends=[]
 for i,p in enumerate(pts):
  before=pts[(i-1)%len(pts)]-p;after=pts[(i+1)%len(pts)]-p
  nb=np.linalg.norm(before);na=np.linalg.norm(after)
  starts.append(p+before*min(.2,2/max(nb,.01)));ends.append(p+after*min(.2,2/max(na,.01)))
 pen.moveTo(tuple(starts[0]))
 for i,p in enumerate(pts):
  pen.qCurveTo(tuple(p),tuple(ends[i]));pen.lineTo(tuple(starts[(i+1)%len(pts)]))
 pen.closePath()

def glyph_from_polys(polys):
 if polys and isinstance(polys[0][0],(int,float)):polys=[polys]
 pen=TTGlyphPen(None)
 for pts in polys:poly(pen,pts)
 return pen.glyph()

def rect(x,y,w,h):return [[x,y],[x,y+h],[x+w,y+h],[x+w,y]]

def ellipse(x,y,rx,ry):return [[x+rx*math.cos(t),y+ry*math.sin(t)]for t in np.linspace(2*math.pi,0,32,endpoint=False)]

def name(ch):return 'uni%04X'%ord(ch)

def build():
 atlas=Path(ATLAS) if ATLAS else ROOT/'assets/glyph-atlas-generated.png'
 image=Image.open(atlas)
 if image.mode!='RGBA':raise ValueError('Atlas must be RGBA with real transparency')
 alpha=np.asarray(image.getchannel('A'))
 if alpha.min()!=0 or alpha.max()<200:raise ValueError('Atlas has no usable transparent background')
 mask=np.uint8(alpha>160)*255
 rowbands=bands((mask>0).sum(1),8);assert len(rowbands)==8
 outlines={};metrics={};cmap={};provenance=[];glyphs={};order=['.notdef','space'];metrics['space']=(170,0)
 glyphs['space']=TTGlyphPen(None).glyph()
 glyphs['.notdef']=glyph_from_polys([rect(30,0,240,800),list(reversed(rect(65,40,170,720)))]);metrics['.notdef']=(300,30)
 cmap[32]='space';cmap[160]='space'
 for row,(ya,yb)in zip(ROWS,rowbands):
  columns=bands((mask[ya:yb]>0).sum(0),1);assert len(columns)==8,(row,columns)
  for ch,(xa,xb)in zip(row,columns):
   sub=mask[ya:yb,xa:xb];yy,xx=np.where(sub>0);gy0,gy1=yy.min(),yy.max()+1;gx0,gx1=xx.min(),xx.max()+1
   crop=sub[gy0:gy1,gx0:gx1];height,width=crop.shape
   if ch.isupper()or ch.isdigit()or ch in '?!':top,bottom=800,(-45 if ch=='Q' else 0)
   elif ch in 'bdfhkl':top,bottom=800,0
   elif ch in 'gjpqy':top,bottom=(720 if ch=='j' else 560),-180
   elif ch=='i':top,bottom=720,0
   elif ch=='t':top,bottom=720,0
   else:top,bottom=560,0
   sy=(top-bottom)/height
   # Vertical proportions normalized independently; coherent widths use a shared grid scale.
   sx=3.30*1254/image.width
   contours,hierarchy=cv2.findContours(crop,cv2.RETR_TREE,cv2.CHAIN_APPROX_NONE)
   paths=[];curvepen=TTGlyphPen(None);cubicpen=Cu2QuPen(curvepen,max_err=.8,reverse_direction=False)
   for idx,c in enumerate(contours):
    if abs(cv2.contourArea(c))<2:continue
    c=c[:,0,:].astype(float)
    depth=0;parent=hierarchy[0,idx,3]
    while parent>=0:depth+=1;parent=hierarchy[0,parent,3]
    pts=np.c_[32+c[:,0]*sx,top-c[:,1]*sy]
    area=np.sum(pts[:,0]*np.roll(pts[:,1],-1)-np.roll(pts[:,0],-1)*pts[:,1])/2
    if (area>0)==(depth%2==0):pts=pts[::-1]
    paths.append(pts.tolist())
    # Fit in raster units, then transform; this avoids magnifying pixel stair steps.
    raw=np.c_[(pts[:,0]-32)/sx,(top-pts[:,1])/sy]
    curves=fit(raw,.45)
    def tr(point):return (32+point[0]*sx,top-point[1]*sy)
    cubicpen.moveTo(tr(curves[0][0]))
    for q in curves:cubicpen.curveTo(tr(q[1]),tr(q[2]),tr(q[3]))
    cubicpen.closePath()
   gn=name(ch);outlines[gn]=paths;glyphs[gn]=curvepen.glyph();metrics[gn]=(round(width*sx+64),32);order.append(gn);cmap[ord(ch)]=gn
   provenance.append({'character':ch,'source':'generated atlas, reference-inspired; not recovered original','atlas_bbox':[int(xa+gx0),int(ya+gy0),int(xa+gx1),int(ya+gy1)],'normalization':{'top':top,'bottom':bottom,'x_scale':sx}})
 # Authored punctuation uses the same stroke weight, independent of a third-party font.
 symbols={'.':[ellipse(60,28,28,28)],',':[ellipse(60,28,28,28),[[45,22],[75,22],[50,-85],[26,-85]]],':':[ellipse(60,120,28,28),ellipse(60,440,28,28)],';':[ellipse(60,440,28,28),ellipse(60,120,28,28),[[45,115],[75,115],[50,15],[26,15]]],'-':[rect(25,260,145,55)],'–':[rect(25,260,240,55)],'—':[rect(25,260,350,55)],'_':[rect(25,-90,220,55)],'+':[rect(25,300,210,55),rect(102,222,55,210)],'=':[rect(25,220,210,55),rect(25,380,210,55)],'/':[[25,-30],[78,-30],[230,820],[177,820]],'\\':[[25,820],[78,820],[230,-30],[177,-30]],'(':[[130,-80],[78,-80],[35,80],[25,360],[35,670],[78,820],[130,820],[87,660],[77,360],[87,90]],')':[[25,-80],[77,-80],[120,80],[130,360],[120,670],[77,820],[25,820],[68,660],[78,360],[68,90]],'[':[rect(25,-70,55,890),rect(25,765,110,55),rect(25,-70,110,55)],']':[rect(80,-70,55,890),rect(25,765,110,55),rect(25,-70,110,55)],"'":[rect(35,620,48,160)],'"':[rect(25,620,42,160),rect(98,620,42,160)]}
 for ch,paths in symbols.items():
  if isinstance(paths[0][0],(int,float)):paths=[paths]
  gn=name(ch);glyphs[gn]=glyph_from_polys(paths);outlines[gn]=paths;metrics[gn]=(round(max(p[0]for path in paths for p in path)+28),25);order.append(gn);cmap[ord(ch)]=gn
  provenance.append({'character':ch,'source':'authored vector punctuation'})
 # Portuguese and common Western-European accented letters, kept as true composites.
 accentpaths={
 'acute':[[0,15],[55,15],[145,130],[65,130]],
 'grave':[[0,130],[80,130],[145,15],[90,15]],
 'circumflex':[[0,10],[50,10],[82,60],[114,10],[164,10],[110,130],[54,130]],
 'tilde':[[0,40],[23,90],[60,102],[110,73],[145,90],[164,60],[142,32],[112,25],[60,53],[30,42]],
 'dieresis':[ellipse(35,65,28,28),ellipse(130,65,28,28)],
 'cedilla':[[45,0],[95,0],[75,-40],[110,-65],[110,-120],[75,-155],[15,-155],[15,-112],[60,-112],[65,-84],[35,-60]]}
 accents={chr(0x301):'acute',chr(0x300):'grave',chr(0x302):'circumflex',chr(0x303):'tilde',chr(0x308):'dieresis',chr(0x327):'cedilla'}
 for mark,paths in accentpaths.items():
  gn='accent.'+mark;glyphs[gn]=glyph_from_polys(paths);metrics[gn]=(0,0);order.append(gn)
 for ch in 'ÀÁÂÃÄÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝàáâãäçèéêëìíîïñòóôõöùúûüý':
  decomposed=unicodedata.normalize('NFD',ch);base,mark=decomposed[0],accents[decomposed[1]];bn=name(base)
  # Remove the dot before accenting i.
  if base=='i':
   bn='i.dotless'
   if bn not in glyphs:
    paths=[p for p in outlines[name('i')]if max(pt[1]for pt in p)<610];glyphs[bn]=glyph_from_polys(paths);metrics[bn]=metrics[name('i')];order.append(bn)
  pen=TTGlyphPen(glyphs);pen.addComponent(bn,(1,0,0,1,0,0));advance=metrics[bn][0];offset=(advance-164)/2
  yoff=-5 if mark=='cedilla'else(840 if base.isupper()else 600)
  pen.addComponent('accent.'+mark,(1,0,0,1,offset,yoff));gn=name(ch);glyphs[gn]=pen.glyph();metrics[gn]=metrics[bn];order.append(gn);cmap[ord(ch)]=gn
  provenance.append({'character':ch,'source':'generated base + authored vector accent'})
 # Typographic apostrophe aliases.
 for src,dst in [('’',"'"),('‘',"'"),('“','"'),('”','"')]:cmap[ord(src)]=cmap[ord(dst)]
 fb=FontBuilder(1000,isTTF=True);fb.setupGlyphOrder(order);fb.setupCharacterMap(cmap);fb.setupGlyf(glyphs);fb.setupHorizontalMetrics(metrics);fb.setupHorizontalHeader(ascent=1020,descent=-220)
 fb.setupNameTable({'familyName':'Motion Referencia Condensada','styleName':'Regular','uniqueFontIdentifier':'MotionReferenciaCondensada-0.100','fullName':'Motion Referencia Condensada Regular','psName':'MotionReferenciaCondensada-Regular','version':'Version 0.100','description':'Experimental reference-inspired family. Generated glyph designs, normalized vector outlines and authored accents. Not the identified original font.'})
 fb.setupOS2(sTypoAscender=1020,sTypoDescender=-220,sTypoLineGap=0,usWinAscent=1020,usWinDescent=220,sxHeight=560,sCapHeight=800,usWeightClass=900,usWidthClass=1)
 fb.setupPost();fb.setupMaxp()
 pairs={'AV':-20,'AW':-15,'AY':-20,'AT':-12,'VA':-20,'WA':-15,'YA':-20,'TA':-18,'To':-16,'Te':-16,'Ta':-16,'Yo':-14,'LT':-12,'LY':-16,'FA':-10}
 features='languagesystem DFLT dflt; languagesystem latn dflt; feature kern {\n'+'\n'.join(f'pos {name(k[0])} {name(k[1])} {v};'for k,v in pairs.items())+'\n} kern;'
 addOpenTypeFeaturesFromString(fb.font,features)
 dest=ROOT/'fonts/MotionReferenciaCondensada-Regular.ttf';dest.parent.mkdir(exist_ok=True);fb.save(dest)
 gs=fb.font.getGlyphSet();svgdir=ROOT/'glyphs';svgdir.mkdir(exist_ok=True)
 for code,gn in cmap.items():
  if code in (32,160):continue
  pen=SVGPathPen(gs);gs[gn].draw(pen);svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -1020 {metrics[gn][0]} 1240"><g transform="scale(1,-1)"><path d="{pen.getCommands()}"/></g></svg>'
  (svgdir/f'U{code:04X}.svg').write_text(svg)
 (ROOT/'glyph-manifest.json').write_text(json.dumps({'font':dest.name,'version':'0.100','characters':''.join(chr(c)for c in sorted(cmap)),'encoded_characters':len(cmap),'glyph_count':len(order),'glyphs':provenance,'kerning_pairs':pairs,'limits':['Reference-inspired reconstruction, not original typeface identification.','Atlas letter design is generated, not a recovered vector of the reference.','Accents and punctuation authored; kerning initial and needs optical proofing.']},ensure_ascii=False,indent=2))
 print(dest,'characters',len(cmap),'glyphs',len(order))
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--atlas',type=Path,help='RGBA atlas with the documented64-glyph reading order')
 parser.add_argument('--output-dir',type=Path,default=ROOT,help='Output package directory')
 args=parser.parse_args();ROOT=args.output_dir.resolve();ROOT.mkdir(parents=True,exist_ok=True);ATLAS=args.atlas
 build()
