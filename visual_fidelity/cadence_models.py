"""Optional inference backends for reference cadence analysis."""

from importlib.metadata import version
from importlib.util import module_from_spec, spec_from_file_location

import cv2
import numpy as np

from .music_sync import SAMPLE_RATE, decode_pcm


def beat_this(path, duration, start, speed, checkpoint, device):
    from beat_this.inference import Audio2Beats

    pcm = decode_pcm(path, duration, start, speed)
    samples = np.frombuffer(pcm, dtype='<f4').reshape(-1, 2)
    predictor = Audio2Beats(checkpoint_path=str(checkpoint), device=device, dbn=False)
    beats, downbeats = predictor(samples, SAMPLE_RATE)
    return {
        'backend': 'beat_this',
        'version': version('beat-this'),
        'beats': sorted(set(float(t) for t in beats if 0 <= t < duration)),
        'downbeats': sorted(set(float(t) for t in downbeats if 0 <= t < duration)),
    }


def transnet_v2(frames, implementation, checkpoint, device):
    import torch

    spec = spec_from_file_location('transnetv2_pytorch', implementation)
    if spec is None or spec.loader is None:
        raise ValueError('Provide the official TransNetV2 PyTorch module as a .py file')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.TransNetV2()
    model.load_state_dict(torch.load(checkpoint, map_location='cpu', weights_only=True))
    model = model.eval().to(device)
    estimates = []
    # Take only the central 50 predictions of each 100-frame context window.
    with torch.inference_mode():
        for start in range(0, len(frames), 50):
            context = np.arange(start - 25, start + 75).clip(0, len(frames) - 1)
            window = torch.from_numpy(frames[context][None]).to(device)
            single, multi = model(window)
            estimates.append(np.stack([
                single[0, 25:75, 0].sigmoid().cpu().numpy(),
                multi['many_hot'][0, 25:75, 0].sigmoid().cpu().numpy(),
            ], axis=1))
    return np.concatenate(estimates)[:len(frames)]


def flow_estimator(backend, device, checkpoint=None):
    if backend == 'farneback':
        def estimate(previous, current):
            return cv2.calcOpticalFlowFarneback(
                cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY),
                cv2.cvtColor(current, cv2.COLOR_BGR2GRAY),
                None, .5, 3, 15, 3, 5, 1.2, 0,
            )
        return estimate

    import torch
    from torchvision.models.optical_flow import Raft_Small_Weights, raft_small

    if checkpoint:
        model = raft_small(weights=None)
        model.load_state_dict(torch.load(checkpoint, map_location='cpu', weights_only=True))
    else:
        model = raft_small(weights=Raft_Small_Weights.C_T_V2)
    model = model.eval().to(device)

    def estimate(previous, current):
        height, width = previous.shape[:2]
        pad = (0, (-width) % 8, 0, (-height) % 8)
        inputs = []
        for frame in (previous, current):
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            tensor = torch.from_numpy(rgb).permute(2, 0, 1)[None].to(device)
            inputs.append(torch.nn.functional.pad(tensor.float() / 127.5 - 1, pad, mode='replicate'))
        with torch.inference_mode():
            flow = model(*inputs)[-1][0, :, :height, :width].cpu().numpy()
        return flow.transpose(1, 2, 0)

    return estimate
