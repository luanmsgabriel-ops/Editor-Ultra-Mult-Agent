from pathlib import Path
import json,subprocess,copy
import numpy as np,pytest
from editorial_engine.native import native_catalog,implementation_fingerprint,render_bundle,BUNDLE_SCHEMA
from editorial_engine.contracts import file_sha256,ValidationError
from editorial_engine.planner import build_plan

@pytest.fixture
def setup(tmp_path):
 source=tmp_path/'s.mp4';y,x=np.mgrid[:100,:160];g=((x//5+y//5)%2*150+30).astype(np.uint8);frames=np.repeat(g[None,:,:,None],3,axis=3).repeat(4,axis=0)
 subprocess.run(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','160x100','-r','10','-i','-','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)],input=frames.tobytes(),check=True)
 sha=file_sha256(source);loc={'source_id':'source','source_sha256':sha,'clock':'source','interval':{'start_s':0,'end_s':.4}}
 ev={'id':'visual',**loc,'kind':'visual','observation':'Authored test textured region, left stripe protected.','provenance':{'kind':'human','actor':'QA','method':'synthetic fixture'}}
 caps=[]
 for id,name,payload in [('runtime','renderer:native:liquid_glass',{'kind':'native_runtime','implementation':implementation_fingerprint(),'cut_candidates':[]}),('protection','protected_regions',{'kind':'protected_regions','fps':'10','frame_count':4,'frames':{str(i):[[.2,.2,.35,.8]] for i in range(4)}})]:
  p=tmp_path/(id+'.json');p.write_text(json.dumps({'source_sha256':sha,**payload}))
  caps.append({'id':id,'name':name,**loc,'status':'verified','evidence_ids':['visual'],'verification':{'by':'QA','method':'synthetic','artifact_path':str(p),'artifact_sha256':file_sha256(p)}})
 a={'schema_version':'1.0','sources':[{'id':'source','sha256':sha,'path':str(source),'duration_s':.4,'fps':'10','frame_count':4}],'evidence':[ev],'events':[{'id':'event',**loc,'intent':'Refract fixture texture','evidence_ids':['visual'],'opportunities':[{'id':'r','function':'reveal','why':'Texture supports optical demonstration'}]}],'capabilities':caps}
 c={'id':'choice','event_id':'event','effect_id':'native.liquid_glass',**loc,'evidence_ids':['visual'],'why':'Explicit optical fixture','scores':dict.fromkeys(['intent_fit','visual_fit','style_fit','timing_fit'],.9),'score_provenance':{'kind':'model','actor':'QA','method':'fixture'},'anchor':{'space':'screen'},'bindings':{'protection':'protection'},'params':{'bevel_px':4,'strength_px':8},'region':[.15,.2,.7,.6],'addresses':['r']}
 return a,c,tmp_path

def bundle(a,c):
 cat=native_catalog();p=build_plan(a,cat,{'schema_version':'1.0','candidates':[c]},verify_files=True);return {'schema':BUNDLE_SCHEMA,'analysis':a,'catalog':cat,'plan':p}

def test_plans_and_encodes_without_background_asset(setup):
 a,c,p=setup;b=bundle(a,c)
 assert b['plan']['validation']['executable'], json.dumps(b['plan'])
 out=render_bundle(b,p/'out.mp4');rows=out['liquid_glass_execution']['decision:choice'] if 'decision:choice' in out['liquid_glass_execution'] else next(iter(out['liquid_glass_execution'].values()))
 assert [r['frame'] for r in rows]==[0,1,2,3]
 assert all(r['protected_modified_pixels']==0 and r['outside_modified_pixels']==0 for r in rows)
 assert any(r['active_refracted_pixels']>0 for r in rows)
 assert out['user_approval']=='pending'

def test_no_binding_is_not_invented(setup):
 a,c,p=setup;c['bindings']={};b=bundle(a,c)
 assert not b['plan']['validation']['executable']

def test_explicit_region_required(setup):
 a,c,p=setup;c.pop('region');b=bundle(a,c)
 with pytest.raises(ValidationError):render_bundle(b,p/'out.mp4')

def test_missing_frame_protection_fails(setup):
 a,c,p=setup;proof=p/'protection.json';v=json.loads(proof.read_text());v['frames'].pop('2');proof.write_text(json.dumps(v));a['capabilities'][1]['verification']['artifact_sha256']=file_sha256(proof)
 with pytest.raises(ValidationError):render_bundle(bundle(a,c),p/'out.mp4')

def test_unknown_background_asset_rejected(setup):
 a,c,p=setup;c['bindings']['asset']='protection';b=bundle(a,c)
 assert not b['plan']['validation']['executable']

def test_entirely_hidden_does_not_publish(setup):
 a,c,p=setup;proof=p/'protection.json';v=json.loads(proof.read_text());v['frames']={str(i):[[0,0,1,1]] for i in range(4)};proof.write_text(json.dumps(v));a['capabilities'][1]['verification']['artifact_sha256']=file_sha256(proof)
 with pytest.raises(ValidationError,match='hide the entire'):render_bundle(bundle(a,c),p/'out.mp4')
 assert not (p/'out.mp4').exists()

def test_insufficient_halo_envelope_fails(setup):
 a,c,p=setup;c['params'].update(glow=1,bevel_px=18)
 with pytest.raises(ValidationError,match='lens and glow'):render_bundle(bundle(a,c),p/'out.mp4')

def test_no_runtime_evidence_no_execution(setup):
 a,c,p=setup;a['capabilities']=a['capabilities'][1:]
 assert not bundle(a,c)['plan']['validation']['executable']

def test_no_execution_receipt_does_not_publish(setup,monkeypatch):
 import visual_fidelity.video_anchor as va
 a,c,p=setup
 def fake(source,output,*args,**kwargs):
  import shutil
  shutil.copyfile(source,output)
 monkeypatch.setattr(va,'render',fake)
 with pytest.raises(ValidationError,match='every requested frame'):render_bundle(bundle(a,c),p/'out.mp4')
 assert not (p/'out.mp4').exists()
