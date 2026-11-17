import pytest
from visual_fidelity.blender_temporal import validate_samples, key_object_motion

class FakeScene:
    def __init__(self): self.frames = []
    def frame_set(self, f): self.frames.append(f)

class FakeObject:
    def __init__(self): self.keys = []
    def keyframe_insert(self, **kwargs):
        self.keys.append((kwargs['data_path'], kwargs['frame'], getattr(self, kwargs['data_path'])))

def test_keys_every_transform_on_real_frame_clock():
    scene, obj = FakeScene(), FakeObject()
    receipt = key_object_motion(scene, obj, [
      {'frame': 1, 'location': [0,0,0], 'rotation_euler': [0,0,0]},
      {'frame': 4, 'location': [1,0,0], 'rotation_euler': [0,0,0.5]},
      {'frame': 9, 'location': [2,0,0], 'rotation_euler': [0,0,1]},
    ])
    assert len(obj.keys) == 6 and scene.frames == [1]
    assert [v[1] for v in obj.keys] == [1,1,4,4,9,9]
    assert receipt['rendered'] is False and receipt['motion_blur_verified'] is False

def test_temporal_guards():
    cases = [
        [{'frame':1,'location':[0,0,0]},{'frame':1,'location':[1,0,0]}],
        [{'frame':1,'location':[0,0,0]},{'frame':2,'scale':[1,1,1]}],
        [{'frame':1,'location':[0,0,0]},{'frame':2,'location':[float('nan'),0,0]}],
    ]
    for samples in cases:
        with pytest.raises(ValueError): validate_samples(samples)
