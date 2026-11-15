"""Render externally reconstructed product geometry as an RGBA plate."""
import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def point_at(obj, target):
    obj.rotation_euler = (target - obj.location).to_track_quat('-Z', 'Y').to_euler()


def render(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if args.asset.suffix.lower() in {'.glb', '.gltf'}:
        bpy.ops.import_scene.gltf(filepath=str(args.asset))
    else:
        bpy.ops.wm.ply_import(filepath=str(args.asset))
    scene = bpy.context.scene
    meshes = [obj for obj in scene.objects if obj.type == 'MESH']
    if not meshes or not any(obj.data.polygons for obj in meshes):
        raise ValueError('O ativo precisa conter uma malha com faces. Para COLMAP, use dense/mesh.ply.')
    bpy.context.view_layer.update()
    positions = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    lower = Vector([min(v[i] for v in positions) for i in range(3)])
    upper = Vector([max(v[i] for v in positions) for i in range(3)])
    center = (lower + upper) / 2
    span = max((upper - lower).length, .0001)
    yaw, pitch = map(math.radians, (args.yaw, args.pitch))
    direction = Vector((math.sin(yaw)*math.cos(pitch), -math.cos(yaw)*math.cos(pitch), math.sin(pitch)))
    bpy.ops.object.camera_add(location=center + direction*span*2.7)
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = span / args.fill
    camera.data.clip_end = max(100, span*8)
    point_at(camera, center)
    scene.camera = camera
    for offset, energy, color in [
        ((-1.5,-1.9,2.2),950,(1,.92,.83)),
        ((1.6,-.8,1),540,(.82,.91,1)),
        ((.5,1.8,1.3),1060,(1,.97,.93)),
    ]:
        bpy.ops.object.light_add(type='AREA', location=center + Vector(offset)*span)
        light = bpy.context.object
        light.data.energy = energy*span*span
        light.data.color = color
        light.data.shape = 'DISK'
        light.data.size = 1.7*span
        point_at(light, center)
    world = bpy.data.worlds.new('Stúdio')
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes.get('Background').inputs['Strength'].default_value = .22
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = False
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.filepath = str(args.output)
    bpy.ops.render.render(write_still=True)


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('Informe um inteiro positivo.')
    return number


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('asset', type=lambda value: Path(value).resolve())
    parser.add_argument('--output', type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument('--width', type=positive_int, default=720)
    parser.add_argument('--height', type=positive_int, default=1280)
    parser.add_argument('--samples', type=positive_int, default=32)
    parser.add_argument('--yaw', type=float, default=14)
    parser.add_argument('--pitch', type=float, default=12)
    parser.add_argument('--fill', type=float, default=.94)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if not args.asset.is_file() or args.asset.suffix.lower() not in {'.glb', '.gltf', '.ply'}:
        parser.error('Informe uma entrada .glb, .gltf ou .ply existente.')
    if args.output.suffix.lower() != '.png' or not 0 < args.fill <= 2:
        parser.error('Informe um destino PNG e --fill entre 0 e 2.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    render(args)
