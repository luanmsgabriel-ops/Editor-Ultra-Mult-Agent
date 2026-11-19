"""Fail-closed per-effect audit for the Editor Ultra. This is a quality gate, not a detector."""
from pathlib import Path
import hashlib
import hmac
import json
import re

HEX=re.compile(r'[a-f0-9]{64}\Z')
STD={
    'source_sha256','reference_sha256','render_sha256','recipe_sha256',
    'policy_sha256','fixture_sha256','effect_id','pair','anchor','metrics','witness',
    'witness_sha256','schema','authored_asset_hash_only'
}

def load_unique(path):
    def pairs(xs):
        d={}
        for k,v in xs:
            if k in d:raise ValueError('duplicate key')
            d[k]=v
        return d
    return json.loads(Path(path).read_text(),object_pairs_hook=pairs)

def digest(path):
    with Path(path).open('rb') as fil:
        return hashlib.file_digest(fil,'sha256').hexdigest()

def same_hash(a,b):
    return bool(type(a) is str and type(b) is str and HEX.fullmatch(a) and HEX.fullmatch(b) and hmac.compare_digest(a,b))

def audit(policy_path, fixture_path, run_files, reports, *, verifier_witnesses):
    """run_files pins exact source/reference/render/recipe. verifier_witnesses are files
    produced independently by trusted QA, mapping effect_id → path. Never use artifacts
    or metrics nominated by the render recipe as verifier_witnesses.
    """
    policy=load_unique(policy_path)
    if policy.get('schema')!='ultra-effect-policy/1':raise ValueError('unsupported policy schema')
    fixture=load_unique(fixture_path)
    if fixture.get('schema')!='ultra-effect-fixture/1':raise ValueError('unsupported fixture schema')
    pairs=fixture.get('pairs')
    if not isinstance(pairs,dict) or not pairs:raise ValueError('fixture pairs are required')
    for effect_id,pair in pairs.items():
        if effect_id not in policy['effects'] or not isinstance(pair,list) or len(pair)!=2 or any(type(i) is not int or i<0 for i in pair):
            raise ValueError('unknown profile or invalid frame pair in fixture')
    expected={key+'_sha256':digest(run_files[key]) for key in ('source','reference','render','recipe')}
    expected['policy_sha256']=digest(policy_path)
    expected['fixture_sha256']=digest(fixture_path)
    extras=sorted(set(reports)-set(pairs))
    state={}
    for effect_id,pair in pairs.items():
        spec=policy['effects'][effect_id]
        report=reports.get(effect_id)
        if report is None:
            state[effect_id]={'status':'blocked','issues':['missing_effect_report']}
            continue
        failures=[];blocked=[]
        if not isinstance(report,dict):
            state[effect_id]={'status':'blocked','issues':['invalid_report_shape']};continue
        if set(report)-STD:blocked.append('unknown_report_fields')
        if report.get('schema')!='ultra-effect-proof/1':blocked.append('schema')
        if report.get('effect_id')!=effect_id:blocked.append('effect_id')
        if report.get('pair')!=pair:blocked.append('wrong_marked_frame_pair')
        for k,v in expected.items():
            if not same_hash(report.get(k),v):blocked.append(f'unbound:{k}')
        if report.get('authored_asset_hash_only') is not False:blocked.append('alpha_or_asset_not_visual_proof')
        if 'anchor' in spec and report.get('anchor')!=spec['anchor']:blocked.append('anchor_contract')
        local_path=verifier_witnesses.get(effect_id)
        witness=None
        if local_path is None:
            blocked.append('missing_independent_witness')
        else:
            try:
                witness=load_unique(local_path)
                if not same_hash(report.get('witness_sha256'),digest(local_path)):blocked.append('mismatch_independent_witness')
                if not isinstance(witness,dict) or witness.get('schema')!='ultra-independent-witness/1':
                    blocked.append('invalid_independent_witness_schema')
                    witness=None
            except (ValueError, OSError, TypeError):
                blocked.append('unreadable_independent_witness')
        contract=spec['requirements']
        declared=report.get('metrics')
        if not isinstance(declared,dict):declared={};blocked.append('no_declared_metrics')
        if witness is not None:
            for key,value in expected.items():
                if not same_hash(witness.get(key),value):blocked.append(f'witness_unbound:{key}')
            if witness.get('effect_id')!=effect_id or witness.get('pair')!=pair:blocked.append('witness_wrong_effect_or_frame_pair')
            if spec.get('anchor') and witness.get('anchor')!=spec['anchor']:blocked.append('witness_anchor_contract')
            ws=witness.get('metrics')
            if not isinstance(ws,dict):ws={};blocked.append('no_witness_metrics')
            if set(ws)-set(contract):blocked.append('unknown_witness_metrics')
        else:ws={}
        if set(declared)-set(contract):blocked.append('unknown_reported_metrics')
        for name,(lower,upper) in contract.items():
            m=declared.get(name); actual=ws.get(name)
            if (type(m) not in (int,float) or type(actual) not in (int,float)
                or not (-float('inf')<m<float('inf') and -float('inf')<actual<float('inf')) or actual!=m):
                blocked.append(f'missing_or_unverified_metric:{name}')
            elif (lower is not None and m<lower) or (upper is not None and m>upper):
                failures.append(f'out_of_bounds:{name}')
        status='blocked' if blocked else 'failed' if failures else 'witnessed_mechanics'
        state[effect_id]={'status':status,'issues':blocked+failures}
    return {'schema':'ultra-effect-audit/1',
            'sha256':expected,'effects':state,'unknown_effects':extras,
            'status':'eligible_for_review' if not extras and all(e['status']=='witnessed_mechanics' for e in state.values()) else 'changes_required',
            'aesthetic_approved':False}


def main(argv=None):
    """Exit nonzero on blocked/failing evidence; never publish or approve a video."""
    import argparse

    cli=argparse.ArgumentParser(description="Check an Editor Ultra visual delivery against independent effect evidence.")
    for name in ('source','reference','render','recipe','policy','fixture','reports','witness-dir'):
        cli.add_argument('--'+name,required=True,type=Path)
    a=cli.parse_args(argv)
    reports=load_unique(a.reports)
    if not isinstance(reports,dict):
        cli.error('reports must map effect IDs to proof objects')
    folder=a.witness_dir.resolve()
    witnesses={}
    for effect_id in reports:
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',effect_id):
            p=folder/(effect_id+'.json')
            if p.is_file() and not p.is_symlink():
                witnesses[effect_id]=p
    result=audit(a.policy,a.fixture,{k:getattr(a,k) for k in ('source','reference','render','recipe')},
                 reports,verifier_witnesses=witnesses)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='eligible_for_review' else 2


if __name__ == '__main__':
    raise SystemExit(main())
