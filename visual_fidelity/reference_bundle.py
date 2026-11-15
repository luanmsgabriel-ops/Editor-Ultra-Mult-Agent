"""Freeze and verify a portable, hashed reference package with explicit scene bindings.

This checks asset integrity and declared scene wiring only. It does not measure
visual similarity, reconstruct missing art, or approve an adaptation.
"""
from __future__ import annotations
import argparse
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile

VERSION = '1.0'
DEFAULT_EXCLUDES = ('.git/**', '**/.git/**', '__pycache__/**', '**/__pycache__/**',
                    '.cache/**', '**/.cache/**', '*.pyc', '**/*.pyc', '*.log', '**/*.log')


class BundleError(ValueError):
    pass


def relative_path(value):
    """Accept one canonical portable relative file path; never resolve traversal."""
    if not isinstance(value,str) or not value or '\\' in value or '\x00' in value:
        raise BundleError('Expected a portable relative POSIX path')
    parts=value.split('/')
    if value.startswith('/') or any(p in ('','.','..') for p in parts) or ':' in parts[0]:
        raise BundleError('Unsafe/noncanonical relative path: '+value)
    return value


def asset_path(root, rel):
    rel=relative_path(rel);root=Path(root).resolve();candidate=root
    for part in PurePosixPath(rel).parts:
        candidate=candidate/part
        if candidate.is_symlink():raise BundleError('Symlinks are not portable assets: '+rel)
    if not candidate.is_file():raise BundleError('Missing asset: '+rel)
    if not candidate.resolve().is_relative_to(root):raise BundleError('Asset escaped package root: '+rel)
    return candidate


def digest_file(path):
    h=hashlib.sha256();size=0
    with Path(path).open('rb') as handle:
        while chunk:=handle.read(1024*1024):h.update(chunk);size+=len(chunk)
    return {'sha256':h.hexdigest(),'size':size}


def excluded(rel, patterns):
    return any(fnmatch.fnmatchcase(rel,p) for p in patterns)


def inventory(root, excludes=DEFAULT_EXCLUDES):
    root=Path(root).resolve()
    if not root.is_dir():raise BundleError('Package root must exist and be a directory')
    rows=[]
    for path in sorted(root.rglob('*')):
        rel=path.relative_to(root).as_posix()
        if excluded(rel,excludes):continue
        if path.is_symlink():raise BundleError('Symlinks are not portable assets: '+rel)
        if path.is_file():rows.append({'path':relative_path(rel),**digest_file(path)})
    return rows


def _json_safe(value):
    try:json.dumps(value,allow_nan=False)
    except (TypeError,ValueError) as exc:raise BundleError('Metadata must be finite JSON data') from exc


def bind_scenes(scene_map, files, verify_bound=False):
    """Validate slots and attach file hashes; all paths must be inventoried."""
    if not isinstance(scene_map,dict):raise BundleError('Scene map must be an object')
    approval=scene_map.get('user_approval','pending')
    if approval not in ('pending','rejected'):
        raise BundleError('This package cannot grant user approval; use pending or rejected')
    scenes=scene_map.get('scenes')
    if not isinstance(scenes,list) or not scenes:raise BundleError('Nonempty scenes list required')
    result=[];ids=set()
    for scene in scenes:
        if not isinstance(scene,dict):raise BundleError('Each scene must be an object')
        identity=scene.get('id')
        if not isinstance(identity,str) or not identity.strip() or identity in ids:raise BundleError('Scene IDs must be unique nonempty strings')
        ids.add(identity);required=scene.get('required_slots')
        if not isinstance(required,list) or not required or any(not isinstance(x,str) or not x.strip() for x in required) or len(set(required))!=len(required):
            raise BundleError(identity+': declare unique nonempty required_slots')
        bindings=scene.get('bindings')
        if not isinstance(bindings,list):raise BundleError(identity+': bindings list required')
        used=set();bound=[]
        for binding in bindings:
            if not isinstance(binding,dict):raise BundleError(identity+': binding must be an object')
            slot=binding.get('slot');role=binding.get('role');layer=binding.get('layer');placement=binding.get('placement')
            if not isinstance(slot,str) or not slot.strip() or slot in used:raise BundleError(identity+': binding slots must be unique strings')
            used.add(slot)
            if not isinstance(role,str) or not role.strip():raise BundleError(identity+'/'+slot+': role required')
            if isinstance(layer,bool) or not isinstance(layer,(str,int)) or layer=='':raise BundleError(identity+'/'+slot+': layer required')
            if not isinstance(placement,dict):raise BundleError(identity+'/'+slot+': placement metadata object required')
            rel=relative_path(binding.get('path'))
            if rel not in files:raise BundleError(identity+'/'+slot+': missing or excluded asset '+rel)
            record=files[rel]
            if any((verify_bound or k in binding) and binding.get(k)!=record[k] for k in ('sha256','size')):
                raise BundleError(identity+'/'+slot+': binding hash/size diverges from inventory')
            bound.append({**binding,'path':rel,'sha256':record['sha256'],'size':record['size']})
        missing=set(required)-used
        if missing:raise BundleError(identity+': missing required slots '+', '.join(sorted(missing)))
        result.append({**scene,'bindings':bound})
    _json_safe(result)
    return result,approval


def freeze(root, manifest, scene_map, excludes=DEFAULT_EXCLUDES):
    root=Path(root).resolve();manifest=Path(manifest).absolute()
    if manifest.is_symlink():raise BundleError('Output manifest cannot be a symlink')
    patterns=list(excludes)
    if any(not isinstance(p,str) or not p for p in patterns):raise BundleError('Exclusions must be nonempty glob strings')
    try:relative_manifest=manifest.resolve().relative_to(root).as_posix()
    except ValueError:relative_manifest=None
    if relative_manifest:
        # Escape glob metacharacters so the output itself is always excluded.
        patterns.append(''.join({'[':'[[]','*':'[*]','?':'[?]'}.get(c,c) for c in relative_manifest))
    patterns=sorted(set(patterns))
    rows=inventory(root,patterns);files={row['path']:row for row in rows}
    if not rows:raise BundleError('Cannot freeze an empty package')
    scenes,approval=bind_scenes(scene_map,files)
    data={'schema':'visual-fidelity-reference-bundle','version':VERSION,
          'inventory_algorithm':'sha256','excludes':patterns,'files':rows,
          'scenes':scenes,'user_approval':approval,'user_approved':False,
          'visual_similarity_certified':False,
          'verification_scope':'bytes, declared required slots, and binding metadata; no perceptual certification'}
    if 'review_note' in scene_map:data['review_note']=scene_map['review_note']
    _json_safe(data);manifest.parent.mkdir(parents=True,exist_ok=True)
    encoded=json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
    temporary=None
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=manifest.parent,prefix='.bundle-',suffix='.tmp',delete=False) as handle:
            temporary=Path(handle.name);handle.write(encoded)
        temporary.replace(manifest)
    finally:
        if temporary and temporary.exists():temporary.unlink()
    return data


def verify(manifest, root, strict=True):
    data=json.loads(Path(manifest).read_text(encoding='utf-8'))
    if data.get('schema')!='visual-fidelity-reference-bundle' or data.get('version')!=VERSION:
        raise BundleError('Unsupported reference bundle schema/version')
    if data.get('inventory_algorithm')!='sha256':raise BundleError('Unsupported inventory hash algorithm')
    if data.get('user_approved') is not False or data.get('visual_similarity_certified') is not False:
        raise BundleError('Integrity manifest cannot certify approval or visual similarity')
    rows=data.get('files');files={}
    if not isinstance(rows,list) or not rows:raise BundleError('Nonempty file inventory required')
    for row in rows:
        if not isinstance(row,dict):raise BundleError('Invalid inventory record')
        rel=relative_path(row.get('path'))
        if rel in files:raise BundleError('Duplicate inventory path: '+rel)
        sha=row.get('sha256');size=row.get('size')
        if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):raise BundleError('Invalid SHA256: '+rel)
        if not isinstance(size,int) or isinstance(size,bool) or size<0:raise BundleError('Invalid file size: '+rel)
        if digest_file(asset_path(root,rel))!={'sha256':sha,'size':size}:raise BundleError('Altered asset: '+rel)
        files[rel]=row
    scenes,approval=bind_scenes(data,files,verify_bound=True)
    patterns=data.get('excludes')
    if not isinstance(patterns,list) or any(not isinstance(p,str) or not p for p in patterns):raise BundleError('Invalid exclusion list')
    if strict:
        actual={row['path'] for row in inventory(root,patterns)}
        unexpected=actual-set(files)
        if unexpected:raise BundleError('Unexpected assets not frozen: '+', '.join(sorted(unexpected)))
    return {'integrity_verified':True,'files_verified':len(files),'scenes_verified':len(scenes),
            'user_approval':approval,'user_approved':False,'visual_similarity_certified':False,
            'strict_inventory':strict}


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('freeze');p.add_argument('root',type=Path);p.add_argument('manifest',type=Path);p.add_argument('--scene-map',required=True,type=Path)
    p.add_argument('--exclude',action='append',default=[],help='Additional POSIX glob, recorded in the manifest')
    p.add_argument('--no-default-excludes',action='store_true',help='Only exclude the output manifest and explicit globs')
    p=sub.add_parser('verify');p.add_argument('manifest',type=Path);p.add_argument('--root',required=True,type=Path);p.add_argument('--allow-extra',action='store_true')
    args=parser.parse_args()
    try:
        if args.action=='freeze':
            patterns=(() if args.no_default_excludes else DEFAULT_EXCLUDES)+tuple(args.exclude)
            data=freeze(args.root,args.manifest,json.loads(args.scene_map.read_text(encoding='utf-8')),patterns)
            result={'frozen':True,'files':len(data['files']),'scenes':len(data['scenes']),'user_approval':data['user_approval'],'user_approved':False,'visual_similarity_certified':False}
        else:result=verify(args.manifest,args.root,strict=not args.allow_extra)
    except (BundleError,OSError,json.JSONDecodeError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False));raise SystemExit(2)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
