import numpy as np
import pytest
from visual_fidelity.motion_smear import smear


def art():
 a=np.zeros((64,64,4),np.float32);a[25:29,30:34]=[.5,.1,0,.5];return a


def run(a,**kw):
 args=dict(before=(0,0,0),current=(1,0,10),after=(2,0,20),shot=(0,3),exposure=1)
 args.update(kw);return smear(a,**args)


def cy(a):
 return (a[:,:,3]*np.arange(a.shape[0])[:,None]).sum()/a[:,:,3].sum()


def test_static_exact_noop():
 a=art();out,_=run(a,before=(0,5,9),current=(1,5,9),after=(2,5,9));assert np.array_equal(a,out)


def test_vertical_direction_and_distance():
 a=art();down,r=run(a);up,_=run(a,before=(0,0,20),current=(1,0,10),after=(2,0,0))
 assert r['offset_start_px']==[0,-10] and r['offset_end_px']==[0,0]
 assert abs(cy(down)-(cy(a)-5))<.05 and abs(cy(up)-(cy(a)+5))<.05
 assert np.all(down[:,:30]==0) and np.all(down[:,34:]==0)


def test_alpha_no_dark_or_colored_halo():
 out,_=run(art());alpha=out[:,:,3];nz=alpha>0
 assert np.all(out[~nz]==0)
 assert np.allclose(out[:,:,0][nz]/alpha[nz],1)
 assert np.allclose(out[:,:,1][nz]/alpha[nz],.2)
 assert np.all(out[:15]==0) and np.all(out[29:]==0)


def test_protected_composite_pixels_exact():
 mask=np.zeros((64,64),np.float32);mask[15:28,30:32]=1
 out,_=run(art(),protection=mask);background=np.full((64,64,3),.37,np.float32)
 composed=out[:,:,:3]+background*(1-out[:,:,3:])
 assert np.array_equal(composed[mask==1],background[mask==1])
 assert np.all(out[mask==1]==0)


@pytest.mark.parametrize('kw',[dict(cuts=[1]),dict(shot=(1,3)),dict(max_displacement=3),dict(before=(.5,0,0)),dict(exposure=2)])
def test_fail_closed(kw):
 with pytest.raises(ValueError):run(art(),**kw)


def test_reject_straight_alpha_hidden_rgb():
 a=art();a[0,0,0]=1
 with pytest.raises(ValueError):run(a)


def test_transparent_all_noop():
 a=np.zeros((64,64,4),np.float32);out,_=run(a);assert np.array_equal(a,out)
