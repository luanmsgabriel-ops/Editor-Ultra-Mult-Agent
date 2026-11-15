"""Export local BootsTAPIR point tracks for one normalized shot."""
import cv2
import numpy as np

from .video_anchor import conform, frames_of, quad


def export(source, target, checkpoint, fps, first, last, corners, device):
    if not checkpoint.is_file():
        raise ValueError('Informe o checkpoint PyTorch local do BootsTAPIR.')
    if not 0<=first<last or last-first>240:
        raise ValueError('Escolha um único plano de até 240 quadros.')
    try:
        import torch
        from tapnet.torch.tapir_model import TAPIR
    except ImportError as exc:
        raise ValueError('Instale o PyTorch e o TAPNet do Google no ambiente de execução.') from exc
    if device=='cuda' and not torch.cuda.is_available():
        raise ValueError('GPU CUDA indisponível. Use --device cpu para um teste curto.')
    box=quad(corners)
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from itertools import islice
    with TemporaryDirectory(prefix='anchor-tapir-') as temporary:
        picture=Path(temporary)/'shot.mp4'
        conform(source,picture,fps)
        size=256
        frames=np.array([cv2.cvtColor(cv2.resize(f,(size,size)),cv2.COLOR_BGR2RGB)
                         for f in islice(frames_of(picture),first,last)])
    if len(frames)!=last-first:
        raise ValueError('O intervalo ultrapassa o fim do vídeo conformado.')
    matte=np.zeros((size,size),'uint8')
    cv2.fillConvexPoly(matte,np.rint(box*size).astype('int32'),255)
    points=cv2.goodFeaturesToTrack(cv2.cvtColor(frames[0],cv2.COLOR_RGB2GRAY),
                                   70,.012,4,mask=matte)
    if points is None or len(points)<6:
        raise ValueError('Escolha uma região com mais pontos visíveis.')
    points=points[:,0,::-1]
    query=torch.from_numpy(np.column_stack((np.zeros(len(points)),points)).astype('float32')).to(device)
    tensor=torch.from_numpy(frames).to(device,dtype=torch.float32)/127.5-1
    model=TAPIR(pyramid_level=1)
    model.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True))
    model=model.to(device).eval()
    with torch.inference_mode():
        prediction=model(tensor[None],query[None])
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('wb') as stream:
        np.savez_compressed(stream,image_size=[size,size],layout='PT',
                            **{name:prediction[name][0].cpu().numpy()
                               for name in ('tracks','occlusion','expected_dist')})
