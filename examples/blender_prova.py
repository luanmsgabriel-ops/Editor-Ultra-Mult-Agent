"""Prova de âncora, perspectiva e oclusão. Execute via Blender 4.3+."""
import argparse
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view


def material(name, rgb, roughness):
    item = bpy.data.materials.new(name)
    item.use_nodes = True
    surface = item.node_tree.nodes.get("Principled BSDF")
    surface.inputs["Base Color"].default_value = (*rgb, 1)
    surface.inputs["Roughness"].default_value = roughness
    return item


def point_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_cube(name, location, dimensions, finish):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    obj.data.materials.append(finish)
    return obj


def create_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 22
    scene.cycles.use_denoising = False
    scene.world = bpy.data.worlds.new("Ambiente")
    scene.world.color = (0.16, 0.16, 0.16)
    scene.render.resolution_x = 432
    scene.render.resolution_y = 288
    scene.render.resolution_percentage = 100
    scene.render.fps = 24
    scene.frame_start, scene.frame_end = 1, 40
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "AgX"

    bpy.ops.mesh.primitive_plane_add(size=200)
    floor = bpy.context.object
    floor.name = "Chão"
    floor.data.materials.append(material("Piso", (0.085, 0.13, 0.15), 0.74))

    type_curve = bpy.data.curves.new("AUTORAL", "FONT")
    type_curve.body = "AUTORAL"
    type_curve.align_x = "CENTER"
    type_curve.size = 0.98
    type_curve.extrude = 0.105
    type_curve.bevel_depth = 0.022
    type_curve.bevel_resolution = 3
    letters = bpy.data.objects.new("Tipo no espaço", type_curve)
    scene.collection.objects.link(letters)
    # Text is in XY and its front faces +Z. Lift its back flush above the floor.
    letters.location = (0, 0.7, type_curve.extrude + type_curve.bevel_depth + 0.002)
    letters.data.materials.append(material("Tipografia metal", (0.72, 0.39, 0.14), 0.3))

    add_cube("Oclusor", (0.75, -0.20, 0.82), (0.40, 0.56, 1.64),
             material("Oclusor azul", (0.09, 0.24, 0.29), 0.54))

    bpy.ops.object.light_add(type="AREA", location=(-3, -4, 6))
    lamp = bpy.context.object
    lamp.data.energy = 1750
    lamp.data.shape = "DISK"
    lamp.data.size = 3
    point_at(lamp, (0, 0.2, 0))

    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.name = "Câmera animada"
    camera.data.lens = 40
    scene.camera = camera
    for at_frame, position in [(1, (4.2, -6.4, 5.2)), (40, (-2.6, -7.1, 3.65))]:
        camera.location = position
        point_at(camera, (0, 0.5, 0.14))
        camera.keyframe_insert("location", frame=at_frame)
        camera.keyframe_insert("rotation_euler", frame=at_frame)
    return scene, camera, letters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, default=Path("./prova-espacial"))
    parser.add_argument("--quadros", type=int, nargs="+", default=[1, 40])
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    destination = args.saida.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    scene, camera, letters = create_scene()
    world_anchor = letters.matrix_world.translation.copy()
    # Two checkpoints verify that the fixed world anchor projects differently.
    # Rendered frames are the independent evidence of appearance/occlusion.
    projections = []
    for number in args.quadros:
        if not scene.frame_start <= number <= scene.frame_end:
            parser.error(f"Quadro fora do intervalo [1, 40]: {number}")
        scene.frame_set(number)
        bpy.context.view_layer.update()
        assert (letters.matrix_world.translation - world_anchor).length < 1e-8
        screen = world_to_camera_view(scene, camera, world_anchor)
        assert 0 < screen.x < 1 and 0 < screen.y < 1 and screen.z > 0
        projections.append((screen.x, screen.y))
        scene.render.filepath = str(destination / f"quadro-{number:04d}.png")
        bpy.ops.render.render(write_still=True)
    if len(set(args.quadros)) > 1:
        assert len(set(projections)) > 1
    print(f"Âncora fixa {tuple(world_anchor)}. Projeções normalizadas: {projections}")


if __name__ == "__main__":
    main()
