"""Project editable world-space planes using registered, undistorted cameras."""
import numpy as np
from scipy.spatial.transform import Rotation


def shape(value, expected):
    matrix=np.asarray(value,dtype='float64')
    if matrix.shape!=expected or not np.isfinite(matrix).all():
        raise ValueError(f'Matriz precisa ser finita com formato {expected}.')
    return matrix


def project(corners,camera):
    world=shape(corners,(4,3))
    if not camera:
        return None
    intrinsics=shape(camera['K'],(3,3))
    rotation=shape(camera['R'],(3,3))
    translation=shape(camera['t'],(3,))
    size=shape(camera['size'],(2,))
    if np.any(size<=0):
        raise ValueError('Dimensão de câmera inválida.')
    points=world@rotation.T+translation
    if np.any(points[:,2]<=1e-7):
        return None
    pixels=points@intrinsics.T
    return (pixels[:,:2]/pixels[:,2,None]/size).astype('float32')


def parse_colmap(model, frame_map):
    by_id={}
    for line in (model/'cameras.txt').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        id_,kind,w,h,*params=line.split()
        if kind=='PINHOLE':
            fx,fy,cx,cy=map(float,params)
        elif kind=='SIMPLE_PINHOLE':
            fx,cx,cy=map(float,params)
            fy=fx
        else:
            continue
        by_id[id_]={'K':[[fx,0,cx],[0,fy,cy],[0,0,1]],'size':[int(w),int(h)]}
    rows=(line for line in (model/'images.txt').read_text(encoding='utf-8').splitlines()
          if not line.startswith('#'))
    output={}
    for row in rows:
        if not row.strip():
            continue
        _,qw,qx,qy,qz,tx,ty,tz,cam,name=row.split(maxsplit=9)
        next(rows,None)  # 2D observations line, empty when the image has none.
        if name not in frame_map:
            continue
        if cam not in by_id:
            raise ValueError(f'{name}: use um modelo COLMAP PINHOLE sem distorção.')
        rotation=Rotation.from_quat(list(map(float,(qx,qy,qz,qw)))).as_matrix()
        output[str(frame_map[name])]={**by_id[cam], 'R':rotation.tolist(),
                                      't':list(map(float,(tx,ty,tz)))}
    if not output:
        raise ValueError('Nenhum nome de imagem foi pareado com quadros da timeline.')
    return output
