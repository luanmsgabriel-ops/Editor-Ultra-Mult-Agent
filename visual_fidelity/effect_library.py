"""Inspect a reference and version reusable motion, color and sound presets."""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
import unicodedata

import cv2
import numpy as np

KINDS=('motion','transicao','cor','overlay','som')
SLUG=re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
VERSION=re.compile(r'^\d+\.\d+\.\d+$')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def validate(card):
    if card.get('kind') not in KINDS or not SLUG.fullmatch(card.get('id','')):
        raise ValueError('Informe uma categoria válida e um ID ASCII com hífens.')
    if not VERSION.fullmatch(card.get('version','')) or card.get('status') not in {'pronto','estudo'}:
        raise ValueError('Informe uma versão numérica e estado pronto ou estudo.')
    if not all(isinstance(card.get(key),str) and card[key].strip() for key in ('title','description')):
        raise ValueError('Título e descrição precisam ser preenchidos.')
    tags=card.get('tags')
    if not isinstance(tags,list) or not all(isinstance(value,str) and value for value in tags):
        raise ValueError('tags precisa ser uma lista de termos.')
    source=card.get('source',{})
    if not source.get('type') or not source.get('details'):
        raise ValueError('Registre a origem e como o efeito foi produzido.')
    if card['kind']=='som' and not source.get('usage'):
        raise ValueError('Descreva a licença ou condição de uso do som.')
    files=card.get('files',[])
    if not isinstance(files,list) or not files or len(set(files))!=len(files):
        raise ValueError('Liste os arquivos do efeito sem duplicação.')
    for name in files:
        path=Path(name)
        if path.is_absolute() or '..' in path.parts or name=='effect.json' or path==Path('.'):
            raise ValueError(f'Caminho de pacote inválido: {name}')
    recipe=card.get('recipe',{})
    if not recipe.get('engine') or not recipe.get('entry'):
        raise ValueError('Informe a receita de reutilização.')
    if isinstance(source.get('frames'),list):
        a,b=source['frames']
        if not(0<=a<b and source.get('fps',0)>0):
            raise ValueError('A evidência precisa de quadros e FPS válidos.')
    return card


def checksum(path):
    with path.open('rb') as stream:
        digest=sha256()
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def register(card_path, catalog_root):
    card=validate(read(card_path))
    root=card_path.parent.resolve()
    target=catalog_root/card['kind']/card['id']/card['version']
    inputs=[]
    for name in card['files']:
        path=(root/name).resolve()
        if not path.is_file() or not path.is_relative_to(root):
            raise ValueError(f'Arquivo do pacote ausente: {name}')
        inputs.append((name,path))
    enriched={**card,'sha256':{name:checksum(path) for name,path in inputs}}
    if target.exists():
        if (read(target/'effect.json')==enriched
                and all((target/name).is_file() and checksum(target/name)==enriched['sha256'][name]
                        for name,_ in inputs)):
            return target
        raise ValueError('A versão já existe com conteúdo diferente. Incremente a versão.')
    target.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=target.parent,prefix='.effect-') as staging:
        stage=Path(staging)/'payload'
        for name,path in inputs:
            dest=stage/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,dest)
        write(stage/'effect.json',enriched)
        stage.rename(target)
    return target


def index(root):
    found=[]
    for path in sorted(root.glob('*/*/*/effect.json')):
        card=validate(read(path))
        if any(not (path.parent/name).is_file() or
               checksum(path.parent/name)!=card.get('sha256',{}).get(name) for name in card['files']):
            raise ValueError(f'Conteúdo alterado em {path.parent}. Registre uma versão nova.')
        found.append({**card,'path':path.parent.relative_to(root).as_posix()})
    return {'schema':1,'effects':found}


def words(text):
    reduced=unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode('ascii').lower()
    return set(re.findall(r'[a-z0-9]+',reduced))


def recommend(catalog, query, kind=None, limit=5):
    target=words(query)
    newest={}
    for entry in catalog['effects']:
        if entry['status']!='pronto' or kind and entry['kind']!=kind:
            continue
        key=(entry['kind'],entry['id'])
        version=tuple(map(int,entry['version'].split('.')))
        if key not in newest or version>newest[key][0]:
            newest[key]=version,entry
    scored=[]
    for _,entry in newest.values():
        token_title=words(entry['title']+' '+' '.join(entry['tags']))
        token_description=words(entry['description'])
        score=3*len(target&token_title)+len(target&token_description)
        if score:
            scored.append((score,entry))
    return [{**entry,'score':score} for score,entry in
            sorted(scored,key=lambda item:(-item[0],item[1]['id']))[:limit]]


def analyze_reference(video, minimum_cut=32.):
    capture=cv2.VideoCapture(str(video))
    fps=capture.get(cv2.CAP_PROP_FPS)
    if not math.isfinite(fps) or fps<=0:
        capture.release()
        raise ValueError('Não foi possível ler a cadência do vídeo.')
    events=[]
    levels=[]
    previous=None
    try:
        while True:
            ok,frame=capture.read()
            if not ok:
                break
            sample=cv2.resize(frame,(96,54),interpolation=cv2.INTER_AREA)
            gray=cv2.cvtColor(sample,cv2.COLOR_BGR2GRAY)
            levels.append((float(gray.mean()),float(np.mean(gray>236)),
                           float(capture.get(cv2.CAP_PROP_POS_MSEC))/1000))
            if previous is not None:
                delta=cv2.absdiff(previous,sample)
                strength=float(delta.mean())
                area=float(np.mean(np.max(delta,axis=2)>42))
                if strength>=minimum_cut and area>=.38:
                    events.append({'candidate':'mudanca_forte','frame':len(levels)-1,
                                   'delta':round(strength,2),'area':round(area,3)})
            previous=sample
    finally:
        capture.release()
    if not levels:
        raise ValueError('Vídeo sem quadros.')
    for item in events:
        index_=item['frame']
        timestamp=levels[index_][2]
        item['s']=round(timestamp if timestamp>0 else index_/fps,5)
    i=1
    while i<len(levels)-1:
        if levels[i][1]<.48:
            i+=1
            continue
        a=i
        while i<len(levels) and levels[i][1]>=.48:
            i+=1
        if 1<=i-a<=round(fps*.35) and i<len(levels) and levels[a-1][0]<163 and levels[i][0]<163:
            events.append({'candidate':'insert_claro_curto','frames':[a,i],
                           's':round(levels[a][2] or a/fps,5),
                           'duration_s_approx':round((i-a)/fps,5)})
    return {'source':video.name,'fps_aproximado':fps,'frames':len(levels),
            'candidates':sorted(events,key=lambda item:item['s']),
            'note':'Mudanças visuais são pontos para revisão. Confirme a técnica e a duração antes de cadastrar.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    add=sub.add_parser('register')
    add.add_argument('card',type=Path)
    add.add_argument('catalog',type=Path)
    build=sub.add_parser('index')
    build.add_argument('catalog',type=Path)
    build.add_argument('output',type=Path)
    search=sub.add_parser('suggest')
    search.add_argument('index',type=Path)
    search.add_argument('query')
    search.add_argument('--kind',choices=KINDS)
    search.add_argument('--limit',type=int,default=5)
    probe=sub.add_parser('analyze')
    probe.add_argument('source',type=Path)
    probe.add_argument('output',type=Path)
    probe.add_argument('--min-delta',type=float,default=32.)
    args=parser.parse_args()
    try:
        match args.action:
            case 'register':
                print(register(args.card,args.catalog))
            case 'index':
                write(args.output,index(args.catalog))
            case 'suggest':
                print(json.dumps(recommend(read(args.index),args.query,args.kind,args.limit),
                                 ensure_ascii=False,indent=2))
            case 'analyze':
                write(args.output,analyze_reference(args.source,args.min_delta))
    except (ValueError,KeyError,TypeError,OSError) as error:
        parser.exit(1,f'{error}\n')


if __name__=='__main__':
    main()
