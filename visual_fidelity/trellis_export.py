"""Generate a textured GLB using an externally installed TRELLIS.2 environment."""
import sys


def main(image_path, output_path):
    import torch
    if not torch.cuda.is_available():
        raise SystemExit('TRELLIS.2 requer um ambiente CUDA configurado.')
    import o_voxel
    from PIL import Image
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    pipeline = Trellis2ImageTo3DPipeline.from_pretrained('microsoft/TRELLIS.2-4B')
    pipeline.cuda()
    with Image.open(image_path) as image:
        mesh = pipeline.run(image.copy())[0]
    mesh.simplify(16777216)
    model = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs,
        coords=mesh.coords, attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5]*3, [0.5]*3], decimation_target=250000, texture_size=2048,
        remesh=True, remesh_band=1, remesh_project=0, verbose=True,
    )
    model.export(output_path)


if __name__ == '__main__':
    main(*sys.argv[1:])
