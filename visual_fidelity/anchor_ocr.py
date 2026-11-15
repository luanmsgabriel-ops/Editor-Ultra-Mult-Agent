"""Optional local OCR for on-screen text protection and duplicate suppression."""
import csv
from io import StringIO
import re
import shutil
import subprocess
import unicodedata

import cv2


def engine(language):
    binary=shutil.which('tesseract')
    if not binary:
        raise ValueError('Instale Tesseract para detectar texto queimado no vídeo.')
    available=subprocess.run([binary,'--list-langs'],check=True,capture_output=True,text=True)
    if any(item not in available.stdout.splitlines() for item in language.split('+')):
        raise ValueError(f'Idioma OCR ausente no Tesseract: {language}')
    return binary


def detect(frame,binary,language):
    h,w=frame.shape[:2]
    gain=max(1,round(810/max(h,w)))
    image=cv2.resize(frame,(w*gain,h*gain),interpolation=cv2.INTER_CUBIC) if gain>1 else frame
    ok,encoded=cv2.imencode('.png',image)
    if not ok:
        raise ValueError('Não foi possível preparar a imagem para o OCR.')
    response=subprocess.run([binary,'stdin','stdout','-l',language,'--psm','11','tsv'],
                            input=encoded.tobytes(),check=True,capture_output=True)
    blocks={}
    bounds=[]
    for row in csv.DictReader(StringIO(response.stdout.decode('utf-8',errors='replace')),
                              delimiter='\t'):
        text=row.get('text','').strip()
        if not text or float(row['conf'])<48:
            continue
        x,y,width,height=[int(row[key]) for key in ('left','top','width','height')]
        if width<=0 or height<=0:
            continue
        frame_w,frame_h=w*gain,h*gain
        bounds.append([max(0,(x-4)/frame_w),max(0,(y-4)/frame_h),
                      min(1,(x+width+4)/frame_w),min(1,(y+height+4)/frame_h)])
        key=tuple(row[field] for field in ('block_num','par_num','line_num'))
        blocks.setdefault(key,[]).append(text)
    return {'lines':[' '.join(words) for words in blocks.values()],'boxes':bounds}


def tokens(text):
    normalized=unicodedata.normalize('NFKD',text.casefold())
    return re.findall(r'[a-z0-9]+',normalized.encode('ascii','ignore').decode('ascii'))


def contains(lines,text):
    query=tokens(text)
    if not query or not any(len(word)>2 for word in query):
        return False
    for line in lines:
        words=tokens(line)
        if any(words[index:index+len(query)]==query for index in range(len(words)-len(query)+1)):
            return True
    return False
