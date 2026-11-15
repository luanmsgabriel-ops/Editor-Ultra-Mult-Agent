"""Build a calibrated, editable Cycles scene from measured CV-space geometry.

Run with Blender's Python. K uses OpenCV pixel coordinates, where (0, 0)
represents the first pixel center. Object positions share the NPZ world frame.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import zlib

import bpy
from mathutils import Euler, Matrix, Vector
import numpy as np


CV_TO_BLENDER = np.diag([1., -1., -1., 1.])


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('O valor precisa ser um inteiro positivo.')
    return number


def read_geometry(path, min_confidence):
    with np.load(path, allow_pickle=False) as archive:
        required = {'points', 'images', 'intrinsics', 'extrinsics', 'valid'}
        missing = required - set(archive.files)
        if missing:
            raise ValueError(f'Campos ausentes no NPZ: {sorted(missing)}')
        data = {name: archive[name] for name in required}
        confidence = archive['confidence'] if 'confidence' in archive.files else None
    points = data['points']
    if points.ndim != 4 or points.shape[-1] != 3 or not np.issubdtype(points.dtype, np.number):
        raise ValueError('points precisa ter forma N × H × W × 3 e valores numéricos.')
    n, height, width, _ = points.shape
    if min(n, height, width) < 1 or min(height, width) < 2:
        raise ValueError('A geometria precisa ter ao menos uma imagem com 2 × 2 pixels.')
    if data['images'].shape != points.shape or data['images'].dtype != np.uint8:
        raise ValueError('images precisa ter a mesma forma de points e dtype uint8.')
    if data['valid'].shape != points.shape[:-1] or data['valid'].dtype != np.bool_:
        raise ValueError('valid precisa ter forma N × H × W e dtype bool.')
    if data['intrinsics'].shape != (n, 3, 3) or data['extrinsics'].shape != (n, 3, 4):
        raise ValueError('intrinsics e extrinsics precisam ter forma N×3×3 e N×3×4.')
    if not all(np.isfinite(data[key]).all() for key in ('intrinsics', 'extrinsics')):
        raise ValueError('Os parâmetros de câmera precisam ser finitos.')
    for k, e in zip(data['intrinsics'], data['extrinsics']):
        if k[0, 0] <= 0 or k[1, 1] <= 0 or not np.allclose(k[2], [0, 0, 1], atol=1e-5):
            raise ValueError('Matriz intrínseca pinhole inválida.')
        if not np.allclose([k[0, 1], k[1, 0]], 0, atol=1e-5):
            raise ValueError('A câmera Blender requer intrínsecos sem skew.')
        rotation = e[:, :3]
        if not np.allclose(rotation @ rotation.T, np.eye(3), atol=2e-3) or not np.isclose(np.linalg.det(rotation), 1, atol=2e-3):
            raise ValueError('A extrínseca precisa conter uma rotação rígida válida.')
    data['valid'] = data['valid'] & np.isfinite(points).all(axis=-1)
    if confidence is not None:
        if confidence.shape != points.shape[:-1]:
            raise ValueError('confidence precisa ter forma N × H × W.')
        data['valid'] &= np.isfinite(confidence) & (confidence >= min_confidence)
    elif min_confidence > 0:
        raise ValueError('--min-confidence requer confidence no NPZ.')
    return data


def png_write(path, rgb):
    """Write an sRGB PNG without requiring external imaging packages in Blender."""
    height, width, _ = rgb.shape
    def chunk(kind, payload):
        return struct.pack('!I', len(payload)) + kind + payload + struct.pack('!I', zlib.crc32(kind + payload) & 0xffffffff)
    rows = b''.join(b'\x00' + row.tobytes() for row in rgb)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0))
                     + chunk(b'sRGB', b'\x00') + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def camera_matrix(extrinsic):
    world_to_camera = np.eye(4)
    world_to_camera[:3] = extrinsic
    return Matrix((CV_TO_BLENDER @ np.linalg.inv(world_to_camera) @ CV_TO_BLENDER).tolist())


def calibrated_camera(scene, intrinsic, extrinsic, width, height, depth):
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.name = 'Câmera calibrada'
    camera.matrix_world = camera_matrix(extrinsic)
    set_intrinsics(scene, camera, intrinsic, width, height)
    camera.data.clip_start = max(.00001, float(depth.min()) / 100)
    camera.data.clip_end = max(10, float(depth.max()) * 100)
    scene.camera = camera
    return camera


def set_intrinsics(scene, camera, intrinsic, width, height):
    fx, fy = intrinsic[0, 0], intrinsic[1, 1]
    cx, cy = intrinsic[0, 2] + .5, intrinsic[1, 2] + .5
    camera.data.type = 'PERSP'
    camera.data.sensor_fit = 'HORIZONTAL'
    camera.data.sensor_width = 36
    camera.data.lens = float(fx * 36 / width)
    ratio = float(fx / fy)
    scene.render.pixel_aspect_x = 1 if ratio >= 1 else 1 / ratio
    scene.render.pixel_aspect_y = ratio if ratio >= 1 else 1
    camera.data.shift_x = float((width / 2 - cx) / width)
    camera.data.shift_y = float((cy - height / 2) * ratio / width)


def animate_cameras(scene, camera, data, metadata, selected):
    manifest = metadata.get('source_manifest', {})
    frames = manifest.get('frames', [])
    fps = manifest.get('nominal_fps')
    if len(frames) != len(data['points']) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0:
        raise ValueError('Animação requer source_manifest com frames por vista e nominal_fps positivo.')
    numbers = [row.get('source_frame') for row in frames]
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in numbers):
        raise ValueError('source_frame precisa ser um inteiro não negativo por vista.')
    if any(b <= a for a, b in zip(numbers, numbers[1:])):
        raise ValueError('Os quadros de câmera precisam estar em ordem estritamente crescente.')
    ratios = data['intrinsics'][:, 0, 0] / data['intrinsics'][:, 1, 1]
    if not np.allclose(ratios, ratios[0], atol=1e-5, rtol=1e-5):
        raise ValueError('Animação requer razão fx/fy constante entre as vistas.')
    height, width = data['images'].shape[1:3]
    scene.render.fps = max(1, round(fps))
    scene.render.fps_base = scene.render.fps / fps
    camera.rotation_mode = 'QUATERNION'
    previous = None
    mapping = []
    for index, (number, k, e) in enumerate(zip(numbers, data['intrinsics'], data['extrinsics'])):
        frame = number - numbers[0] + 1
        camera.matrix_world = camera_matrix(e)
        if previous is not None and previous.dot(camera.rotation_quaternion) < 0:
            camera.rotation_quaternion.negate()
        previous = camera.rotation_quaternion.copy()
        set_intrinsics(scene, camera, k, width, height)
        for property_name in ('location', 'rotation_quaternion'):
            camera.keyframe_insert(data_path=property_name, frame=frame)
        for property_name in ('lens', 'shift_x', 'shift_y'):
            camera.data.keyframe_insert(data_path=property_name, frame=frame)
        mapping.append({'view': index, 'source_frame': number, 'blender_frame': frame})
    for owner in (camera, camera.data):
        if owner.animation_data and owner.animation_data.action:
            for curve in owner.animation_data.action.fcurves:
                for point in curve.keyframe_points:
                    point.interpolation = 'LINEAR'
    scene.frame_start, scene.frame_end = 1, mapping[-1]['blender_frame']
    scene.frame_set(mapping[selected]['blender_frame'])
    return {'fps': fps, 'mapping': mapping, 'interpolation': 'Linear between sampled cameras; intervening poses are approximate.'}


def triangulate(points, valid, extrinsic, stride, max_edge_ratio):
    """Preserve raster-grid topology while dropping invalid/depth-bridging faces."""
    height, width, _ = points.shape
    rows = np.unique(np.r_[np.arange(0, height, stride), height - 1])
    cols = np.unique(np.r_[np.arange(0, width, stride), width - 1])
    ys, xs = np.meshgrid(rows, cols, indexing='ij')
    sampled = points[ys, xs].reshape(-1, 3).astype(np.float64)
    camera = sampled @ extrinsic[:, :3].T + extrinsic[:, 3]
    good = valid[ys, xs].ravel() & (camera[:, 2] > 0) & np.isfinite(camera).all(axis=-1)
    grid = np.arange(len(sampled)).reshape(ys.shape)
    a, b, c, d = (grid[:-1, :-1].ravel(), grid[:-1, 1:].ravel(), grid[1:, :-1].ravel(), grid[1:, 1:].ravel())
    # Reverse raster winding so the normal faces the observing camera.
    triangles = np.concatenate([np.stack([a, c, b], -1), np.stack([b, c, d], -1)])
    triangles = triangles[good[triangles].all(axis=1)]
    original_count = len(triangles)
    if len(triangles):
        xyz = sampled[triangles]
        edge = np.maximum.reduce([np.linalg.norm(xyz[:, 0] - xyz[:, 1], axis=1),
                                  np.linalg.norm(xyz[:, 1] - xyz[:, 2], axis=1),
                                  np.linalg.norm(xyz[:, 2] - xyz[:, 0], axis=1)])
        reference_depth = camera[triangles, 2].min(axis=1)
        triangles = triangles[edge <= max_edge_ratio * reference_depth]
    if not len(triangles):
        raise ValueError('Nenhuma face válida. Revise máscara, stride e --max-edge-ratio.')
    used, inverse = np.unique(triangles, return_inverse=True)
    triangles = inverse.reshape(-1, 3)
    vertices = sampled[used] * [1, -1, -1]
    uv = np.column_stack(((xs.ravel()[used] + .5) / width, 1 - (ys.ravel()[used] + .5) / height))
    return vertices, triangles, uv, {'vertices': len(vertices), 'faces': len(triangles),
                                    'discarded_edge_faces': original_count - len(triangles),
                                    'sampled_valid_vertices': int(good.sum())}


def textured_mesh(data, index, args, temporary):
    vertices, triangles, uv, counts = triangulate(data['points'][index], data['valid'][index],
                                                data['extrinsics'][index], args.stride, args.max_edge_ratio)
    mesh = bpy.data.meshes.new(f'Geometria vista {index}')
    mesh.from_pydata(vertices.tolist(), [], triangles.tolist())
    mesh.update()
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.collection.objects.link(obj)
    layer = mesh.uv_layers.new(name='Projeção original')
    for polygon in mesh.polygons:
        for loop in polygon.loop_indices:
            layer.data[loop].uv = uv[mesh.loops[loop].vertex_index]
    path = temporary / f'view-{index:04d}.png'
    png_write(path, data['images'][index])
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = 'sRGB'
    image.pack()
    material = bpy.data.materials.new(f'{args.material} vista {index}')
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    texture = nodes.new('ShaderNodeTexImage')
    texture.image = image
    texture.interpolation = 'Linear'
    texture.extension = 'EXTEND'
    shader = nodes.new('ShaderNodeEmission' if args.material == 'projected' else 'ShaderNodeBsdfPrincipled')
    socket = 'Color' if args.material == 'projected' else 'Base Color'
    material.node_tree.links.new(texture.outputs['Color'], shader.inputs[socket])
    material.node_tree.links.new(shader.outputs[0], output.inputs['Surface'])
    if args.material == 'pbr':
        shader.inputs['Roughness'].default_value = .58
    obj.data.materials.append(material)
    return counts


def surface_material(name, color, roughness, metallic):
    if len(color) not in (3, 4) or not all(0 <= value <= 1 for value in color):
        raise ValueError('color deve ser RGB/RGBA entre zero e um.')
    if not 0 <= roughness <= 1 or not 0 <= metallic <= 1:
        raise ValueError('roughness e metallic precisam estar entre zero e um.')
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = tuple(color[:3]) + (color[3] if len(color) == 4 else 1,)
    shader.inputs['Roughness'].default_value = roughness
    shader.inputs['Metallic'].default_value = metallic
    return mat


def add_objects(path):
    if path is None:
        return 0
    config = json.loads(path.read_text(encoding='utf-8'))
    objects = config.get('objects', [])
    if not isinstance(objects, list):
        raise ValueError('objects deve ser uma lista.')
    for item in objects:
        kind = item.get('type')
        position = np.asarray(item.get('position', [0, 0, 1]), dtype=float)
        angles = np.asarray(item.get('rotation_deg', [0, 0, 0]), dtype=float)
        if position.shape != (3,) or angles.shape != (3,) or not np.isfinite([position, angles]).all():
            raise ValueError('Posição e rotação precisam ter três valores finitos.')
        if kind == 'box':
            dimensions = np.asarray(item.get('dimensions', [1, 1, 1]), dtype=float)
            if dimensions.shape != (3,) or not np.isfinite(dimensions).all() or (dimensions <= 0).any():
                raise ValueError('dimensions precisa ter três valores positivos.')
            bpy.ops.mesh.primitive_cube_add(size=1)
            obj = bpy.context.object
            obj.dimensions = dimensions.tolist()
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            bevel = float(item.get('bevel', .015))
            if bevel < 0 or not math.isfinite(bevel):
                raise ValueError('bevel precisa ser finito e não negativo.')
            mod = obj.modifiers.new('Bordas arredondadas', 'BEVEL')
            mod.width, mod.segments = bevel, 3
        elif kind == 'text':
            body = item.get('text', '')
            size, extrude, bevel = (float(item.get(key, default)) for key, default in
                                    [('size', .2), ('extrude', .01), ('bevel', .002)])
            if not isinstance(body, str) or not body.strip() or not all(math.isfinite(v) for v in (size, extrude, bevel)) or size <= 0 or min(extrude, bevel) < 0:
                raise ValueError('Texto ou dimensões tipográficas inválidos.')
            bpy.ops.object.text_add()
            obj = bpy.context.object
            obj.data.body, obj.data.size, obj.data.extrude, obj.data.bevel_depth = body, size, extrude, bevel
            obj.data.align_x = 'CENTER'
            obj.data.align_y = 'CENTER'
            font = item.get('font')
            if font:
                font_path = (path.parent / font).resolve()
                obj.data.font = bpy.data.fonts.load(str(font_path))
                obj.data.font.pack()
        else:
            raise ValueError(f'Tipo de objeto não suportado: {kind!r}')
        obj.name = item.get('name', kind)
        rotation = Euler(tuple(math.radians(v) for v in angles), 'XYZ').to_matrix().to_4x4()
        transform = Matrix(CV_TO_BLENDER.tolist()) @ rotation @ Matrix(CV_TO_BLENDER.tolist())
        transform.translation = Vector((position * [1, -1, -1]).tolist())
        obj.matrix_world = transform
        obj.data.materials.append(surface_material(obj.name, item.get('color', [.65, .04, .03]),
                                                  float(item.get('roughness', .32)), float(item.get('metallic', .0))))
    return len(objects)


def add_lights(scene, camera, distance):
    world = bpy.data.worlds.new('Luz ambiente estimada')
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes.get('Background').inputs['Strength'].default_value = .10
    for name, local, energy, color in [('Principal', (-.45, .55, -.25), 90, (1., .94, .88)),
                                       ('Preenchimento', (.5, .25, -.15), 45, (.84, .92, 1.))]:
        bpy.ops.object.light_add(type='AREA')
        light = bpy.context.object
        light.name = name
        light.location = camera.matrix_world @ (Vector(local) * distance)
        aim = camera.matrix_world @ Vector((0, 0, -distance))
        light.rotation_euler = (aim - light.location).to_track_quat('-Z', 'Y').to_euler()
        light.data.energy = energy * distance * distance
        light.data.color = color
        light.data.size = distance * .7


def run(args):
    data = read_geometry(args.geometry, args.min_confidence)
    n, height, width, _ = data['points'].shape
    if not 0 <= args.view < n:
        raise ValueError('--view está fora do intervalo de vistas.')
    e = data['extrinsics'][args.view]
    camera_points = data['points'][args.view] @ e[:, :3].T + e[:, 3]
    depth = camera_points[..., 2][data['valid'][args.view] & (camera_points[..., 2] > 0)]
    if not len(depth):
        raise ValueError('A vista selecionada não contém geometria visível válida.')
    metadata_path = args.geometry.with_suffix('.json')
    metadata = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() else {}
    if not isinstance(metadata, dict):
        raise ValueError('O arquivo JSON de metadados precisa conter um objeto.')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = False
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure, scene.view_settings.gamma = 0, 1
    camera = calibrated_camera(scene, data['intrinsics'][args.view], e, width, height, depth)
    trajectory = animate_cameras(scene, camera, data, metadata, args.view) if args.animate_cameras else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.render:
        args.render.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.scene-build-', dir=args.output.parent) as directory:
        temporary = Path(directory)
        indices = list(range(n)) if args.all_views else [args.view]
        meshes = [dict(view=i, **textured_mesh(data, i, args, temporary)) for i in indices]
        count = add_objects(args.objects)
        if args.material == 'pbr' or count:
            add_lights(scene, camera, float(np.median(depth)))
        report = {'schema': 1, 'source': str(args.geometry), 'metadata': metadata,
                  'frame': 'CV world transformed by diag(1,-1,-1)', 'pixel_coordinates': 'OpenCV integer pixel centers',
                  'view': args.view, 'size': [width, height], 'material': args.material, 'trajectory': trajectory,
                  'meshes': meshes, 'added_objects': count, 'engine': 'CYCLES', 'samples': args.samples,
                  'limitations': ['The surface covers visible measurements only; occluded geometry remains unknown.',
                                  'Projected colors include illumination already present in the input.',
                                  'PBR roughness and area lights are authored estimates, not recovered material or lighting.',
                                  'All-view meshes can overlap; no multi-view fusion is applied.']}
        if args.render:
            scene.render.filepath = str(temporary / 'preview.png')
            bpy.ops.render.render(write_still=True)
        # The saved render target should be usable after the staging directory disappears.
        scene.render.filepath = str(args.render.resolve()) if args.render else '//render.png'
        bpy.ops.wm.save_as_mainfile(filepath=str(temporary / 'scene.blend'))
        staged_report = temporary / 'report.json'
        staged_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if args.render:
            (temporary / 'preview.png').replace(args.render)
        (temporary / 'scene.blend').replace(args.output)
        staged_report.replace(args.output.with_suffix('.report.json'))
    print(json.dumps({'blend': str(args.output), 'render': str(args.render) if args.render else None,
                      'vertices': sum(row['vertices'] for row in meshes), 'faces': sum(row['faces'] for row in meshes)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('geometry', type=lambda value: Path(value).resolve())
    parser.add_argument('output', type=lambda value: Path(value).resolve())
    parser.add_argument('--render', type=lambda value: Path(value).resolve())
    parser.add_argument('--objects', type=lambda value: Path(value).resolve())
    parser.add_argument('--view', type=int, default=0)
    parser.add_argument('--stride', type=positive_int, default=4)
    parser.add_argument('--samples', type=positive_int, default=16)
    parser.add_argument('--max-edge-ratio', type=float, default=.08)
    parser.add_argument('--min-confidence', type=float, default=0)
    parser.add_argument('--material', choices=('projected', 'pbr'), default='projected')
    parser.add_argument('--all-views', action='store_true')
    parser.add_argument('--animate-cameras', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    if args.geometry.suffix.lower() != '.npz' or args.output.suffix.lower() != '.blend':
        parser.error('Informe uma geometria NPZ e um destino .blend.')
    if args.render and args.render.suffix.lower() != '.png':
        parser.error('--render precisa terminar em .png.')
    if not math.isfinite(args.max_edge_ratio) or args.max_edge_ratio <= 0 or not math.isfinite(args.min_confidence):
        parser.error('Os limiares precisam ser finitos e --max-edge-ratio positivo.')
    try:
        run(args)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f'Erro na reconstrução da cena: {error}\n')


if __name__ == '__main__':
    main()
