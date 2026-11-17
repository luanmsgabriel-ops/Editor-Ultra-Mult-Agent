"""Measured motion must reach the pixels of the actual renderer.

Synthetic fixtures deliberately separate geometry/clock correctness from visual
approval of an edited reference. Small MP4s exercise the encoded cadence path.
"""
import copy
import json
import shutil
import subprocess
from fractions import Fraction

import cv2
import numpy as np
from PIL import Image
import pytest

from visual_fidelity.motion_profile import fit_profile, profile_digest
from visual_fidelity.motion_binding import (
    SCHEMA, MotionProfilePool, bind_timeline_motion, transform_at, source_time_at,
    validate_binding,
)
from visual_fidelity import geometric_video as gv
from visual_fidelity import studio_edit as se
from visual_fidelity.reference_cadence import apply_cadence, SCHEMA as CADENCE


def observed(rows, *, step=1, time_base='1/10'):
    samples=[]
    for index,fields in enumerate(rows):
        sample={'frame':index,'pts':500+index*step,'segment':'panel-entry',
                'position_px':[32,32],'scale':1,'angle_deg_unwrapped':0,
                'confidence':None,'status':'observed','visibility':'visible'}
        sample.update(fields);samples.append(sample)
    return {'schema':'element-motion-observations/1',
            'source':{'sha256':'a'*64,'width':64,'height':64,'time_base':time_base,
                      'first_pts':500,'coordinate_convention':'opencv_pixel_centers',
                      'rotation_ccw_applied':0},
            'elements':[{'id':'panel','model':'similarity_2d',
                         'reference':{'size_px':[16,16],'anchor':'center'},'samples':samples}]}


def binding(profile, *, pivot=(32,32), end=.4, stage='local_rgba'):
    return {'schema':SCHEMA,'profile':profile,'profile_sha256':profile_digest(profile),
            'element_id':'panel','channels':['position','scale','angle'],
            'pivot_px':list(pivot),'base_scale':1,'stage':stage,
            'time_map':[{'output_time':0,'source_time':0},
                        {'output_time':end,'source_time':end}]}


def config(*, end=5):
    return {'target':'insert','interval':[0,end],'element_id':'panel',
            'channels':['position','scale','angle'],'pivot_px':[32,32],'base_scale':1}


def timeline(root, *, count=5, fps=10):
    cv2.imwrite(str(root/'black.png'),np.zeros((64,64,3),np.uint8))
    cv2.imwrite(str(root/'white.png'),np.full((64,64,3),255,np.uint8))
    return {'width':64,'height':64,'fps':fps,'frames':count,
            'assets':{'base':{'path':'black.png','kind':'image','origin':'test'},
                      'panel':{'path':'white.png','kind':'image','origin':'test'}},
            'asset_plan':{'slots':[{'id':'panel','evidence':'Synthetic motion regression',
                                   'role':'probe','status':'ready','asset_ids':['panel'],
                                   'interval':[0,count]}]},
            'frame_bindings':[{'frame':i,'shot':'panel','base':{'source':'base'},
                               'insert':{'source':'panel'},
                               'mask':{'kind':'polygon','points':[[.375,.375],[.625,.375],[.625,.625],[.375,.625]]}}
                              for i in range(count)]}


def center(frame):
    yy,xx=np.where(frame[:,:,0]>150)
    assert len(xx)
    return np.array([xx.mean(),yy.mean()])


def test_centered_zoom_changes_pixels_and_uses_post_resize_pivot():
    profile=fit_profile(observed([{'scale':.5},{'scale':1},{'scale':2}]))
    spec={'motion':binding(profile,pivot=(10,5),end=.2)}
    image=Image.new('RGBA',(20,10),(255,50,0,255))
    small=np.asarray(se.move(image,spec,0,size=(64,64),output_time=0))
    large=np.asarray(se.move(image,spec,1,size=(64,64),output_time=.2))
    assert np.count_nonzero(large[:,:,3]>128)>10*np.count_nonzero(small[:,:,3]>128)
    transform=transform_at(spec['motion'],.2,image.size,(64,64))
    matrix=cv2.getRotationMatrix2D(transform.pivot,transform.angle,transform.scale)
    matrix[:,2]+=(transform.x,transform.y)
    np.testing.assert_allclose(matrix@np.array([10,5,1]),[32,32])
    assert transform.x==22 and transform.y==27


def test_rotation_uses_opencv_ccw_and_keeps_center_fixed():
    profile=fit_profile(observed([{}, {'angle_deg_unwrapped':90}]))
    spec={'motion':binding(profile,pivot=(10,10),end=.1)}
    image=Image.new('RGBA',(20,20));image.paste((255,255,255,255),(14,9,17,12))
    initial=np.asarray(se.move(image,spec,0,size=(64,64),output_time=0))
    rotated=np.asarray(se.move(image,spec,1,size=(64,64),output_time=.1))
    assert center(initial)[0]>32 and abs(center(initial)[1]-32)<1
    assert center(rotated)[1]<32 and abs(center(rotated)[0]-32)<1


def test_studio_rejects_ambiguous_keys_missing_clock_and_unsupported_stage():
    b=binding(fit_profile(observed([{},{}])),end=.1)
    image=Image.new('RGBA',(64,64),'white')
    with pytest.raises(ValueError,match='real output time'):
        se.move(image,{'motion':b},.5,size=(64,64))
    for authored in ({'x':0},{'keys':[{'u':0,'scale':1}]},{'pivot':[32,32]},
                     {'enter':3},{'quad_file':'points.json'}):
        with pytest.raises(ValueError):
            se.move(image,{'motion':b,**authored},0,size=(64,64),output_time=0)
    with pytest.raises(ValueError,match='local_rgba'):
        se.move(image,{'motion':{**b,'stage':'masked_canvas'}},0,size=(64,64),output_time=0)


def test_bound_channel_does_not_replace_authored_unbound_opacity():
    p=fit_profile(observed([{},{}]));b=binding(p,end=.1)
    image=Image.new('RGBA',(64,64),'white')
    result=np.asarray(se.move(image,{'motion':b,'opacity':.25},0,size=(64,64),output_time=0))
    assert result[:,:,3].max()==64


def test_studio_frame_uses_absolute_output_clock_after_shot_start_and_resize(tmp_path,monkeypatch):
    p=fit_profile(observed([{'position_px':[20+10*i,32]} for i in range(5)]))
    b=binding(p,pivot=(4,4));b['spatial_scale']=1
    Image.new('RGBA',(16,16),(240,10,10,255)).save(tmp_path/'red.png')
    editor=se.Editor.__new__(se.Editor);editor.root=tmp_path;editor.cache={}
    editor.d={'version':se.VERSION,'fps':10,'frames':5,'shots':[
        {'id':'intro','start':0,'end':2,'layers':[]},
        {'id':'body','start':2,'end':5,'layers':[{'id':'red','kind':'image','path':'red.png',
                                               'resize':[8,8],'motion':b}]}]}
    monkeypatch.setattr(se,'studio',lambda _:Image.new('RGBA',se.SIZE,'black'))
    image=np.asarray(editor.frame(2))
    yy,xx=np.where((image[:,:,0]>200)&(image[:,:,1]<20))
    assert xx.mean()==pytest.approx(39.5) and yy.mean()==pytest.approx(31.5)
    assert list(editor._motion_usage.values())[0]['frames']==[2]


def test_profile_hash_and_coefficients_are_verified_even_after_rehash():
    p=fit_profile(observed([{}, {'scale':2}]));b=binding(p,end=.1)
    changed=copy.deepcopy(b);changed['profile']['source']['sha256']='b'*64
    with pytest.raises(ValueError,match='hash'):
        validate_binding(changed)
    bad=copy.deepcopy(b)
    bad['profile']['elements'][0]['channels']['scale']['segments'][0]['coefficients'][0][2][0]+=.1
    bad['profile_sha256']=profile_digest(bad['profile'])
    with pytest.raises(ValueError,match='coefficients'):
        validate_binding(bad)


def test_profile_pool_snapshot_cannot_be_changed_by_later_manifest_mutation():
    p=fit_profile(observed([{}, {'scale':2}]));b=binding(p,end=.1)
    digest=b['profile_sha256'];pool=MotionProfilePool({digest:p});del b['profile']
    p['source']['width']=999
    assert transform_at(b,.1,(64,64),(64,64),profiles=pool).scale==2
    with pytest.raises(ValueError,match='missing'):
        transform_at(b,.1,(64,64),(64,64),profiles={})


def test_gaps_and_outside_ranges_fail_before_binding_plan_is_returned(tmp_path):
    data=timeline(tmp_path);p=fit_profile(observed([{}, {}, {'status':'missing'}, {}, {}]))
    with pytest.raises(ValueError,match='coverage missing'):
        bind_timeline_motion(data,p,[config()],time_map=[{'output_time':0,'source_time':0},{'output_time':.5,'source_time':.5}])
    assert 'element_motion' not in data and 'motion_profiles' not in data
    b=binding(fit_profile(observed([{},{}])),end=.1)
    with pytest.raises(ValueError,match='outside'):
        transform_at(b,.2,(64,64),(64,64))
    with pytest.raises(ValueError,match='increase'):
        validate_binding({**b,'time_map':[{'output_time':0,'source_time':.1},{'output_time':.1,'source_time':0}]})


def test_change_canvas_requires_explicit_uniform_mapping():
    p=fit_profile(observed([{},{}]));b=binding(p,end=.1)
    with pytest.raises(ValueError,match='Changed canvas'):
        transform_at(b,0,(64,64),(128,64))
    explicit={**b,'spatial_scale':.5,'spatial_offset_px':[48,16]}
    tr=transform_at(explicit,0,(64,64),(128,64))
    assert tr.scale==.5 and tr.x==32 and tr.y==0


def test_geometric_binding_pools_profiles_and_moves_color_with_coverage(tmp_path):
    data=timeline(tmp_path)
    p=fit_profile(observed([{'position_px':[12+10*i,32]} for i in range(5)]))
    result=bind_timeline_motion(data,p,[config()],time_map=[{'output_time':0,'source_time':0},{'output_time':.5,'source_time':.5}])
    assert len(result['motion_profiles'])==1
    assert all('profile' not in row['insert']['motion'] for row in result['frame_bindings'])
    usage={};sources=gv.Sources(tmp_path,result['assets'])
    frames=[gv.render_frame(result,row,sources,tmp_path,usage) for row in result['frame_bindings']]
    sources.close()
    np.testing.assert_allclose(center(frames[-1])-center(frames[0]),[40,0],atol=.1)
    assert len(usage)==1 and list(usage.values())[0]['frames']==[0,1,2,3,4]
    assert all(np.count_nonzero(f[:,:,0]>150)>200 for f in frames)


def test_fractional_cadence_clock_reaches_motion_without_frame_flooring(tmp_path):
    data=timeline(tmp_path,count=6,fps='24000/1001')
    p=fit_profile(observed([{'position_px':[20+3*i,32]} for i in range(8)],step=1001,time_base='1/30000'))
    reference={'schema':CADENCE,'source_sha256':'a'*64,'fps':'30000/1001','frames':8,
               'cuts':[],'markers':{'apex':{'frame':3,'time':float(Fraction(3003,30000))}},
               'status':'test','cut_detector':'test','motion_backend':'test','music':{'backend':'none'}}
    result=apply_cadence(data,reference,[{'marker':'apex','template_frame':2}],
                         motion_profile=p,motion_bindings=[config(end=6)])
    b=result['frame_bindings'][1]['insert']['motion'];t=float(Fraction(1001,24000))
    assert source_time_at(b,t)==pytest.approx(float(Fraction(15015,300000)))
    tr=transform_at(b,t,(64,64),(64,64),profiles=result['motion_profiles'])
    assert tr.x==pytest.approx(24.5-32)
    assert result['reference_cadence']['element_motion']['regional_flow_used_as_element_trajectory'] is False


@pytest.mark.parametrize('declared_vfr',[False,True])
def test_cadence_rejects_vfr_flag_or_nonuniform_pts_even_with_nominal_reference_fps(tmp_path,declared_vfr):
    data=timeline(tmp_path)
    rows=[{'pts':500+i*10} for i in range(5)]
    if not declared_vfr:rows[2]['pts']=522
    obs=observed(rows,time_base='1/100')
    obs['source']['clock_kind']='vfr' if declared_vfr else 'cfr'
    profile=fit_profile(obs)
    reference={'schema':CADENCE,'source_sha256':'a'*64,'fps':'10','frames':5,
               'cuts':[],'markers':{'middle':{'frame':2,'time':.2}},'status':'test',
               'cut_detector':'test','motion_backend':'test','music':{'backend':'none'}}
    with pytest.raises(ValueError,match='motion-profile bind with an explicit time_map'):
        apply_cadence(data,reference,[{'marker':'middle','template_frame':2}],
                      motion_profile=profile,motion_bindings=[config()])
    # A reviewed, explicit source clock remains available through general binding.
    result=bind_timeline_motion(data,profile,[config()],time_map=[{'output_time':0,'source_time':0},
                                                               {'output_time':.5,'source_time':.5}])
    assert result['element_motion']['status']=='bound_not_rendered'


def test_foreground_box_and_unsupported_targets_are_not_silently_ignored(tmp_path):
    data=timeline(tmp_path);p=fit_profile(observed([{} for _ in range(5)]))
    for row in data['frame_bindings']:
        row['foreground']={'source':'panel','matte':'matte.png','box':[0,0,1,1]}
    conf={**config(),'target':'foreground'}
    with pytest.raises(ValueError,match='box conflicts'):
        bind_timeline_motion(data,p,[conf],time_map=[{'output_time':0,'source_time':0},{'output_time':.5,'source_time':.5}])
    with pytest.raises(ValueError,match='Motion target'):
        bind_timeline_motion(data,p,[{**config(),'target':'base'}],time_map=[{'output_time':0,'source_time':0},{'output_time':.5,'source_time':.5}])


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required for encoded integration evidence')
def test_same_endpoints_different_measured_easing_changes_encoded_cadence_frames(tmp_path):
    data=timeline(tmp_path)
    reference={'schema':CADENCE,'source_sha256':'a'*64,'fps':'10','frames':5,
               'cuts':[],'markers':{'middle':{'frame':2,'time':.2}},'status':'test',
               'cut_detector':'test','motion_backend':'test','music':{'backend':'none'}}
    decoded=[]
    for name,positions in [('linear',[8,20,32,44,56]),('late',[8,10,16,30,56])]:
        profile=fit_profile(observed([{'position_px':[x,32]} for x in positions]))
        result=apply_cadence(data,reference,[{'marker':'middle','template_frame':2}],
                             motion_profile=profile,motion_bindings=[config()])
        manifest=tmp_path/(name+'-manifest.json');manifest.write_text(json.dumps(result))
        report=gv.render(manifest,tmp_path/(name+'.mp4'))
        consumed=report['element_motion']['bindings']
        assert consumed[0]['frames']==[0,1,2,3,4] and consumed[0]['profile_sha256']==profile_digest(profile)
        cap=cv2.VideoCapture(str(tmp_path/(name+'.mp4')));frames=[]
        while True:
            ok,frame=cap.read()
            if not ok:break
            frames.append(frame)
        cap.release();assert len(frames)==5;decoded.append(frames)
    np.testing.assert_allclose(center(decoded[0][0]),center(decoded[1][0]),atol=.2)
    np.testing.assert_allclose(center(decoded[0][-1]),center(decoded[1][-1]),atol=.2)
    assert center(decoded[0][2])[0]-center(decoded[1][2])[0]>15
    assert np.mean(np.abs(decoded[0][2].astype(float)-decoded[1][2]))>10


def test_render_preflight_preserves_manifest_assets_and_prior_output(tmp_path):
    data=timeline(tmp_path);manifest=tmp_path/'bound.json'
    original=json.dumps(data);manifest.write_text(original)
    with pytest.raises(ValueError,match='collides'):
        gv.render(manifest,tmp_path/'bound.mp4')
    assert manifest.read_text()==original
    with pytest.raises(ValueError,match='collides'):
        gv.render(manifest,tmp_path/'white.png')
    assert cv2.imread(str(tmp_path/'white.png')).min()==255
    prior=tmp_path/'prior.mp4';prior.write_bytes(b'preserved')
    with pytest.raises(FileExistsError,match='prior render'):
        gv.render(manifest,prior)
    assert prior.read_bytes()==b'preserved'


def test_inactive_top_level_insert_binding_is_rejected(tmp_path):
    data=timeline(tmp_path);p=fit_profile(observed([{} for _ in range(5)]))
    for row in data['frame_bindings']:
        row['layers']=[{'id':'other','depth':'behind_subject','insert':{'source':'panel'},'mask':{'kind':'full'}}]
    with pytest.raises(ValueError,match='inactive'):
        bind_timeline_motion(data,p,[config()],time_map=[{'output_time':0,'source_time':0},{'output_time':.5,'source_time':.5}])


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required for cleanup regression')
def test_render_failure_closes_sources_and_removes_partial_temporary_video(tmp_path,monkeypatch):
    data=timeline(tmp_path);manifest=tmp_path/'input.json';manifest.write_text(json.dumps(data))
    original_frame=gv.render_frame;original_close=gv.Sources.close;closed=[]
    def fail_second(*args,**kwargs):
        if args[1]['frame']==1:raise ValueError('deliberate render failure')
        return original_frame(*args,**kwargs)
    def close(sources):
        closed.append(True);original_close(sources)
    monkeypatch.setattr(gv,'render_frame',fail_second);monkeypatch.setattr(gv.Sources,'close',close)
    with pytest.raises(ValueError,match='deliberate render failure'):
        gv.render(manifest,tmp_path/'new-output.mp4')
    assert closed and not (tmp_path/'new-output-silent.mp4').exists()
    assert not (tmp_path/'new-output.mp4').exists()


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required for mux cleanup regression')
def test_audio_mux_failure_removes_partial_final_and_silent_video(tmp_path,monkeypatch):
    data=timeline(tmp_path);data['audio']={'path':'sound.wav'}
    data['music_sync']={'mode':'editorial_override','reason':'Synthetic cleanup regression'}
    audio=tmp_path/'sound.wav';audio.write_bytes(b'untouched audio fixture')
    manifest=tmp_path/'input.json';manifest.write_text(json.dumps(data))
    output=tmp_path/'new-output.mp4'
    def fail_mux(command,**kwargs):
        output.write_bytes(b'partial final file')
        raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(gv.subprocess,'run',fail_mux)
    with pytest.raises(subprocess.CalledProcessError):gv.render(manifest,output)
    assert not output.exists() and not (tmp_path/'new-output-silent.mp4').exists()
    assert audio.read_bytes()==b'untouched audio fixture'
