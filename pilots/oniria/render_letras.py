"""Render the Oníria extruded title layer with Blender and a transparent background."""
import argparse
import sys

import bpy
from mathutils import Matrix, Vector


def make_surface(label, rgba, metal, rough, emission=0):
    material = bpy.data.materials.new(label)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = rgba
    shader.inputs["Metallic"].default_value = metal
    shader.inputs["Roughness"].default_value = rough
    shader.inputs["Emission Color"].default_value = rgba
    shader.inputs["Emission Strength"].default_value = emission
    return material


def aim(obj, point):
    obj.rotation_euler = (Vector(point) - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_type(value, font, width, height, spacing, y, extrusion, bevel, gold, bronze):
    shape = bpy.data.curves.new(value, "FONT")
    shape.body = value
    shape.font = font
    shape.align_x = "CENTER"
    shape.align_y = "CENTER"
    shape.space_character = spacing
    shape.size = height
    shape.extrude = extrusion
    shape.bevel_depth = bevel
    shape.bevel_resolution = 3
    shape.resolution_u = 12
    letter = bpy.data.objects.new(value, shape)
    bpy.context.collection.objects.link(letter)
    shape.materials.append(gold)
    shape.materials.append(bronze)
    shape.materials.append(gold)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = letter
    letter.select_set(True)
    bpy.context.view_layer.update()
    resize = min(1.0, width / letter.dimensions.x)
    letter.scale = (resize, resize, 1)
    letter.location.y = y
    return letter


def add_light(name, point, energy, rgb, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.color = rgb
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = point
    aim(obj, (0, 0, 0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--saida", required=True)
    parser.add_argument("--serif", default="/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf")
    parser.add_argument("--sans", default="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    options = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 56
    scene.cycles.use_denoising = False
    scene.render.film_transparent = True
    scene.render.resolution_x = 800
    scene.render.resolution_y = 340
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = options.saida
    scene.view_settings.view_transform = "AgX"
    scene.world = bpy.data.worlds.new("Ambiência")
    scene.world.color = (0.085, 0.032, 0.013)
    face = make_surface("Ouro quente escovado", (0.82, 0.47, 0.22, 1), 0.58, 0.32, 0.34)
    bronze = make_surface("Ouro escuro nas laterais", (0.31, 0.105, 0.027, 1), 0.55, 0.42, 0.035)
    caption = make_surface("Champanhe", (0.90, 0.62, 0.33, 1), 0.34, 0.41, 0.42)
    serif = bpy.data.fonts.load(options.serif)
    sans = bpy.data.fonts.load(options.sans)
    add_type("ONÍRIA", serif, 4.8, 1.43, 1.17, 0.53, 0.11, 0.018, face, bronze)
    add_type("F E S T I V A L", sans, 2.75, 0.34, 1, -0.26, 0.038, 0.006, caption, bronze)
    add_type("A  P R I M E I R A  N O I T E", sans, 3.72, 0.28, 1, -0.67, 0.021, 0.005, caption, bronze)
    add_light("Principal dourada", (-3.5, 3, 5), 610, (1, .68, .37), 4)
    add_light("Frontal suave", (0, 1, 6), 460, (1, .88, .66), 7)
    add_light("Recorte lateral", (3, -3, 1.7), 270, (1, .45, .19), 2)
    camera = bpy.data.objects.new("Perspectiva local estimada", bpy.data.cameras.new("Câmera"))
    bpy.context.collection.objects.link(camera)
    camera.location = (0.44, -0.39, 9.5)
    normal = camera.location.normalized()
    right = Vector((0, 1, 0)).cross(normal).normalized()
    up = normal.cross(right)
    camera.rotation_euler = Matrix((right, up, normal)).transposed().to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 5.65
    scene.camera = camera
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
