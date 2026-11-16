"""Build a recurrent foreground alpha sequence on the original edit clock."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from .reference_cadence import digest, video_clock
from .video_anchor import frames_of, shot_starts


def prepare_alpha(source, model, directory):
    import onnxruntime

    rate, count = video_clock(source)
    directory.mkdir(parents=True, exist_ok=True)
    session_options = onnxruntime.SessionOptions()
    session_options.intra_op_num_threads = 3
    session_options.inter_op_num_threads = 1
    model_session = onnxruntime.InferenceSession(
        str(model), session_options, providers=['CPUExecutionProvider'],
    )
    frames = list(frames_of(source, analysis=True))
    if len(frames) != count or not count:
        raise ValueError('Alpha and source frame counts do not match.')
    cuts = set(shot_starts(frames))
    ratio = np.array([.50], np.float32)
    for index, bgr in enumerate(frames):
        if index in cuts:
            state = [np.zeros((1,1,1,1), np.float32) for _ in range(4)]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        picture = np.ascontiguousarray(rgb.transpose(2,0,1)[None], dtype=np.float32)/255
        _, alpha, *state = model_session.run(None, {
            'src': picture, 'downsample_ratio': ratio,
            **dict(zip(('r1i','r2i','r3i','r4i'), state)),
        })
        gray = np.uint8(np.clip(alpha[0,0],0,1)*255+.5)
        if not cv2.imwrite(str(directory/f'{index:06d}.png'),gray,[cv2.IMWRITE_PNG_COMPRESSION,2]):
            raise OSError('Could not write foreground alpha')
    report = {'source_sha256':digest(source), 'model_sha256':digest(model),
              'fps':str(rate), 'frames':count, 'resolution':list(frames[0].shape[1::-1])}
    (directory/'alpha.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('model',type=Path)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    print(prepare_alpha(args.source,args.model,args.directory))


if __name__=='__main__':
    main()
