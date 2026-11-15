"""Optional MoGe-2 and VGGT inference in one explicit camera/geometry contract.

Install the separate scene-model environment before calling infer(). This module
keeps torch and the upstream packages out of the base editor's import path.
"""
from contextlib import nullcontext
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

MOGE_REVISION = 'b942f00bdc2a2a23ebb474fbe034d487e6dcceec'
VGGT_REVISION = 'a288dd0f14786c93483e45524328726ab7b1b4ce'
MOGE_CHECKPOINT = 'Ruicheng/moge-2-vits-normal'
VGGT_CHECKPOINT = 'facebook/VGGT-1B'
MOGE_WEIGHTS_REVISION = '26b477f41595707c5db6770294c0d1721e8ed4ed'
VGGT_WEIGHTS_REVISION = '860abec7937da0a4c03c41d3c269c366e82abdf9'


def _device(torch, requested):
    if requested == 'auto':
        requested = 'cuda' if torch.cuda.is_available() else 'cpu'
    selected = torch.device(requested)
    if selected.type not in {'cuda', 'cpu'}:
        raise ValueError('Use device=auto, cpu, cuda ou cuda:N.')
    if selected.type == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA solicitada, mas indisponível neste ambiente.')
    return selected


def _numpy(tensor):
    return tensor.detach().float().cpu().numpy()


def normalized_to_pixel_intrinsics(intrinsics, width, height):
    """MoGe UV coordinates use pixel centers (i+.5)/size; exports use i."""
    matrix = np.asarray(intrinsics, dtype=np.float32).copy()
    matrix[0] *= width
    matrix[1] *= height
    matrix[0, 2] -= .5
    matrix[1, 2] -= .5
    return matrix


def pad_content_mask(paths, side=518):
    """Mask the white padding introduced by VGGT's official mode='pad'."""
    masks = []
    boxes = []
    for path in paths:
        with Image.open(path) as image:
            width, height = image.size
        if width >= height:
            new_width = side
            new_height = round(height * side / width / 14) * 14
        else:
            new_height = side
            new_width = round(width * side / height / 14) * 14
        if min(new_width, new_height) < 14:
            raise ValueError(f'Proporção extrema de imagem incompatível com VGGT: {path}')
        x, y = (side-new_width)//2, (side-new_height)//2
        mask = np.zeros((side, side), dtype=bool)
        mask[y:y+new_height, x:x+new_width] = True
        masks.append(mask)
        boxes.append([x, y, x+new_width, y+new_height])
    return np.stack(masks), boxes


def _moge(torch, paths, device, checkpoint, resolution_level, num_tokens):
    try:
        from moge.model.v2 import MoGeModel
    except ImportError as error:
        raise RuntimeError('MoGe-2 ausente. Execute o instalador de modelos em ambiente isolado.') from error
    with Image.open(paths[0]) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        rgb = np.asarray(image).copy()
    height, width = rgb.shape[:2]
    weights = {'revision': MOGE_WEIGHTS_REVISION} if checkpoint is None else {}
    model = MoGeModel.from_pretrained(checkpoint or MOGE_CHECKPOINT, **weights).to(device).eval()
    tensor = torch.from_numpy(rgb).to(device=device, dtype=torch.float32).permute(2, 0, 1)/255
    with torch.inference_mode():
        result = model.infer(tensor, resolution_level=resolution_level, num_tokens=num_tokens,
                             use_fp16=device.type == 'cuda', force_projection=True, apply_mask=True)
    points = _numpy(result['points'])
    valid = result['mask'].detach().cpu().numpy().astype(bool)
    valid &= np.isfinite(points).all(axis=-1) & (points[..., 2] > 0)
    points[~valid] = np.nan
    intrinsics = normalized_to_pixel_intrinsics(_numpy(result['intrinsics']), width, height)
    metadata = {
        'provider': 'moge-2', 'upstream_revision': MOGE_REVISION,
        'checkpoint': str(checkpoint or MOGE_CHECKPOINT), 'device': str(device),
        'weights_revision': MOGE_WEIGHTS_REVISION if checkpoint is None else 'user_supplied',
        'scale': 'estimated_metric', 'units': 'meters',
        'coordinate_system': 'opencv_world', 'camera_convention': 'world_to_camera',
        'pixel_convention': 'integer_pixel_centers', 'resolution_level': resolution_level,
        'num_tokens': num_tokens, 'confidence_kind': 'binary_model_mask',
        'preprocessing': 'exif_orientation_then_rgb',
    }
    output = {
        'points': points[None], 'images': rgb[None], 'intrinsics': intrinsics[None],
        'extrinsics': np.eye(4, dtype=np.float32)[None, :3], 'valid': valid[None],
        'confidence': valid[None].astype(np.float32), 'metadata': metadata,
    }
    if 'normal' in result:
        output['normals'] = _numpy(result['normal'])[None]
    return output


def _vggt(torch, paths, device, checkpoint):
    try:
        from vggt.models.vggt import VGGT
        from vggt.utils.load_fn import load_and_preprocess_images
        from vggt.utils.pose_enc import pose_encoding_to_extri_intri
        from vggt.utils.geometry import unproject_depth_map_to_point_map
    except ImportError as error:
        raise RuntimeError('VGGT ausente. Execute o instalador de modelos em ambiente isolado.') from error
    # The official helper intentionally returns its processed RGB raster. Camera
    # matrices are estimated for this raster; they must never be paired with the
    # original input image dimensions.
    content, boxes = pad_content_mask(paths)
    images = load_and_preprocess_images([str(path) for path in paths], mode='pad').to(device)
    weights = {'revision': VGGT_WEIGHTS_REVISION} if checkpoint is None else {}
    model = VGGT.from_pretrained(str(checkpoint or VGGT_CHECKPOINT), **weights).to(device).eval()
    precision = nullcontext()
    if device.type == 'cuda':
        dtype = torch.bfloat16 if torch.cuda.get_device_capability(device)[0] >= 8 else torch.float16
        precision = torch.autocast(device_type='cuda', dtype=dtype)
    with torch.inference_mode(), precision:
        predictions = model(images)
        extrinsics, intrinsics = pose_encoding_to_extri_intri(predictions['pose_enc'], images.shape[-2:])
    ext = _numpy(extrinsics[0])
    intr = _numpy(intrinsics[0])
    depth = _numpy(predictions['depth'][0])
    # Depth and solved cameras preserve the projection constraint. Upstream also
    # recommends these world points over the independent world-point head.
    points = unproject_depth_map_to_point_map(depth, ext, intr).astype(np.float32)
    confidence = _numpy(predictions['depth_conf'][0])
    valid = content & np.isfinite(points).all(axis=-1) & np.isfinite(confidence) & (depth[..., 0] > 0)
    points[~valid] = np.nan
    confidence[~valid] = 0
    rgb = np.rint(_numpy(images).transpose(0, 2, 3, 1).clip(0, 1)*255).astype(np.uint8)
    return {
        'points': points, 'images': rgb, 'intrinsics': intr, 'extrinsics': ext,
        'valid': valid, 'confidence': confidence,
        'metadata': {
            'provider': 'vggt', 'upstream_revision': VGGT_REVISION,
            'checkpoint': str(checkpoint or VGGT_CHECKPOINT), 'device': str(device),
            'weights_revision': VGGT_WEIGHTS_REVISION if checkpoint is None else 'user_supplied',
            'scale': 'relative', 'units': 'arbitrary', 'coordinate_system': 'opencv_world',
            'camera_convention': 'world_to_camera', 'pixel_convention': 'integer_pixel_centers',
            'preprocessing': 'official_load_and_preprocess_images_pad', 'content_boxes': boxes,
            'confidence_kind': 'raw_depth_head_score',
        },
    }


def infer(model, image_paths, *, device='auto', checkpoint=None, resolution_level=0, num_tokens=None):
    """Infer geometry for one MoGe image or multiple views of one VGGT scene.

    Returns points/images N×H×W×3, validity/confidence N×H×W, intrinsics
    N×3×3 and world-to-camera extrinsics N×3×4. Invalid points contain NaN.
    Confidence values are provider-specific, never cross-model probabilities.
    MoGe checkpoints accept a .pt file or Hub ID. VGGT accepts a Hub ID or
    a local directory in the Hugging Face from_pretrained format.
    """
    model = model.lower()
    paths = [Path(path) for path in image_paths]
    if model not in {'moge', 'vggt'}:
        raise ValueError('Modelo deve ser moge ou vggt.')
    if not paths or (model == 'moge' and len(paths) != 1):
        raise ValueError('MoGe requer uma imagem; VGGT requer uma ou mais vistas do mesmo plano.')
    if not isinstance(resolution_level, int) or not 0 <= resolution_level <= 9:
        raise ValueError('resolution_level deve ser inteiro entre 0 e 9.')
    if num_tokens is not None and (not isinstance(num_tokens, int) or num_tokens < 16):
        raise ValueError('num_tokens deve ser inteiro de pelo menos 16.')
    if model == 'vggt' and (resolution_level != 0 or num_tokens is not None):
        raise ValueError('resolution_level e num_tokens são controles exclusivos do MoGe.')
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    try:
        import torch
    except ImportError as error:
        raise RuntimeError('PyTorch ausente. Instale o ambiente opcional de modelos 3D.') from error
    selected = _device(torch, device)
    if model == 'moge':
        return _moge(torch, paths, selected, checkpoint, resolution_level, num_tokens)
    return _vggt(torch, paths, selected, checkpoint)
