"""Render an editable, six-panel baseball cap with Blender (4.3+)."""
import argparse
from math import cos, pi, sin
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def options():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene", type=Path, help="Optionally save the editable .blend project.")
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--denoise", action="store_true", help="Requires a build with OpenImageDenoise.")
    parser.add_argument("--base-color", type=Path, help="Optional cloth base-color texture.")
    parser.add_argument("--roughness", type=Path, help="Optional cloth roughness map.")
    parser.add_argument("--normal", type=Path, help="Optional tangent-space cloth normal map.")
    parser.add_argument("--logo", type=Path, help="Optional PNG with alpha to replace the test mark.")
    parser.add_argument("--no-mark", action="store_true")
    parser.add_argument("--logo-center-u", type=float, default=0.49714)
    parser.add_argument("--logo-center-v", type=float, default=0.337)
    parser.add_argument("--logo-width", type=float, default=0.0505, help="Width in crown UV coordinates.")
    parser.add_argument("--logo-height", type=float, default=0.22, help="Height in crown UV coordinates.")
    parser.add_argument("--camera-elevation", type=float, default=50)
    parser.add_argument("--camera-azimuth", type=float, default=0)
    parser.add_argument("--ortho-scale", type=float, default=4.16)
    parser.add_argument("--aim-y", type=float, default=-0.67)
    parser.add_argument("--aim-z", type=float, default=0.11)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if min(args.width, args.height, args.samples, args.ortho_scale, args.logo_width, args.logo_height) <= 0:
        parser.error("Dimensions, samples and scale must be positive.")
    for field in ("base_color", "roughness", "normal", "logo"):
        path = getattr(args, field)
        if path is not None and not path.is_file():
            parser.error(f"Missing {field} texture: {path}")
    return args


def simple_material(name, color, roughness, sheen=0.0):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Sheen Weight"].default_value = sheen
    return material


def texture_node(material, filename, uv, color_space):
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(filename.resolve()), check_existing=False)
    texture.image.colorspace_settings.name = color_space
    links.new(uv, texture.inputs["Vector"])
    return texture


def cloth_material(name, args, custom_logo=False, tint=1):
    material = simple_material(name, (0.15 * tint,) * 3, 0.82, 0.25)
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    coords = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeVectorMath")
    mapping.operation = "MULTIPLY"
    mapping.inputs[1].default_value = (17, 13, 1)
    links.new(coords.outputs["UV"], mapping.inputs[0])
    uv = mapping.outputs[0]

    fibers = nodes.new("ShaderNodeTexNoise")
    fibers.inputs["Scale"].default_value = 31
    fibers.inputs["Detail"].default_value = 2.5
    links.new(uv, fibers.inputs["Vector"])

    weave = []
    for direction in ("X", "Y"):
        wave = nodes.new("ShaderNodeTexWave")
        wave.bands_direction = direction
        wave.inputs["Scale"].default_value = 38
        wave.inputs["Distortion"].default_value = 2.4
        wave.inputs["Detail Scale"].default_value = 3
        links.new(uv, wave.inputs["Vector"])
        weave.append(wave.outputs["Fac"])
    crossing = nodes.new("ShaderNodeMath")
    crossing.operation = "MULTIPLY"
    links.new(weave[0], crossing.inputs[0])
    links.new(weave[1], crossing.inputs[1])

    shades = nodes.new("ShaderNodeValToRGB")
    shades.color_ramp.elements[0].color = (0.074 * tint,) * 3 + (1,)
    shades.color_ramp.elements[1].color = (0.158 * tint,) * 3 + (1,)
    links.new(fibers.outputs["Fac"], shades.inputs["Fac"])
    surface_color = shades.outputs["Color"]
    if args.base_color:
        surface_color = texture_node(material, args.base_color, uv, "sRGB").outputs["Color"]
    if args.roughness:
        rough = texture_node(material, args.roughness, uv, "Non-Color")
        links.new(rough.outputs["Color"], shader.inputs["Roughness"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.34
    bump.inputs["Distance"].default_value = 0.009
    links.new(crossing.outputs[0], bump.inputs["Height"])
    if args.normal:
        normal = nodes.new("ShaderNodeNormalMap")
        links.new(texture_node(material, args.normal, uv, "Non-Color").outputs["Color"],
                  normal.inputs["Color"])
        links.new(normal.outputs[0], bump.inputs["Normal"])
    links.new(bump.outputs[0], shader.inputs["Normal"])
    if custom_logo:
        logo_coords = nodes.new("ShaderNodeVectorMath")
        logo_coords.operation = "MULTIPLY"
        logo_coords.inputs[1].default_value = (1 / args.logo_width, 1 / args.logo_height, 1)
        links.new(coords.outputs["UV"], logo_coords.inputs[0])
        offset = nodes.new("ShaderNodeVectorMath")
        offset.operation = "ADD"
        offset.inputs[1].default_value = (
            0.5 - args.logo_center_u / args.logo_width,
            0.5 - args.logo_center_v / args.logo_height,
            0,
        )
        links.new(logo_coords.outputs[0], offset.inputs[0])
        logo = texture_node(material, args.logo, offset.outputs[0], "sRGB")
        logo.extension = "CLIP"
        overlay = nodes.new("ShaderNodeMixRGB")
        links.new(logo.outputs["Alpha"], overlay.inputs[0])
        links.new(surface_color, overlay.inputs[1])
        links.new(logo.outputs["Color"], overlay.inputs[2])
        surface_color = overlay.outputs[0]
    links.new(surface_color, shader.inputs["Base Color"])
    return material


def crown_point(theta, t, lift=0.0):
    angle = t * pi / 2
    radius = max(0.0008, cos(angle)) ** 0.78
    sewn = 1 + 0.012 * sin(6 * theta - pi / 2)
    creases = (0.024 * sin(11 * theta + 2 * t) +
               0.016 * sin(19 * theta - 5.4 * t)) * (sin(pi * t) ** 2)
    radius = radius * (sewn + creases) + lift
    x = 1.005 * radius * sin(theta)
    y = -1.21 * radius * cos(theta) + 0.37 * t * t
    z = 1.005 * sin(angle) + lift * 0.5
    z += 0.025 * sin(theta * 3) * sin(pi * t)
    return x, y, z


def visor_point(theta, distance, lift=0):
    edge_x = 0.96 * sin(theta)
    edge_y = -0.95 - 1.33 * max(0, cos(theta)) ** 0.43
    seam_x = 1.005 * 0.982 * sin(theta)
    seam_y = -1.21 * 0.982 * cos(theta)
    x = seam_x + distance * (edge_x - seam_x)
    y = seam_y + distance * (edge_y - seam_y)
    z = -0.018 - 0.113 * distance - (0.084 + 0.125 * distance) * sin(theta) ** 2
    return x, y, z + lift


def surface(name, rows, columns, point, material, reverse=False):
    vertices = [point(j / columns, i / rows)
                for i in range(rows + 1) for j in range(columns + 1)]
    stride = columns + 1
    faces = []
    for i in range(rows):
        for j in range(columns):
            a = i * stride + j
            face = (a, a + 1, a + stride + 1, a + stride)
            faces.append(face[::-1] if reverse else face)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="Cloth UV")
    for polygon in mesh.polygons:
        polygon.use_smooth = True
        for index in polygon.loop_indices:
            row, col = divmod(mesh.loops[index].vertex_index, stride)
            uv.data[index].uv = (col / columns, row / rows)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def tube(name, material, lines, radius):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 2
    curve.bevel_depth = radius
    curve.bevel_resolution = 2
    for points in lines:
        line = curve.splines.new("POLY")
        line.points.add(len(points) - 1)
        for point, coordinate in zip(line.points, points):
            point.co = (*coordinate, 1)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def path(start, stop, step_count, point):
    return [point(start + (stop - start) * index / step_count)
            for index in range(step_count + 1)]


def stitches(start, stop, total, point, duty=0.62):
    step = (stop - start) / total
    return [[point(start + index * step), point(start + (index + duty) * step)]
            for index in range(total)]


def create_cap(args):
    fabric = cloth_material("Six-panel woven cotton", args, custom_logo=args.logo and not args.no_mark)
    bill_material = cloth_material("Visor woven cotton", args, tint=0.92)
    seam = simple_material("Gray structural thread", (0.111,) * 3, 0.9, 0.28)
    sewing = simple_material("Fine dark cotton stitching", (0.082,) * 3, 0.9)
    upper_thread = simple_material("Light cotton highlights", (0.154,) * 3, 0.88, 0.26)
    eye = simple_material("Eyelet recess", (0.020,) * 3, 0.93)
    crown = surface("Crown", 48, 144, lambda u, v: crown_point((u - 0.5) * 2 * pi, v), fabric)
    solidify = crown.modifiers.new("Cotton thickness", "SOLIDIFY")
    solidify.thickness = 0.012
    visor = surface("Curved visor", 26, 96, lambda u, v: visor_point((u - 0.5) * 2.75, v),
                    bill_material, reverse=True)
    solidify = visor.modifiers.new("Visor edge thickness", "SOLIDIFY")
    solidify.thickness = 0.022
    bevel = visor.modifiers.new("Visor rounded edge", "BEVEL")
    bevel.width = 0.018
    bevel.segments = 3

    crown_seams, crown_stitches = [], []
    for segment in range(6):
        angle = segment * pi / 3
        crown_seams.append(path(0.009, 0.965, 64, lambda t: crown_point(angle, t, 0.006)))
        for offset in (-0.023, 0.023):
            crown_stitches.extend(stitches(0.015, 0.94, 58,
                                          lambda t: crown_point(angle + offset, t, 0.007)))
    tube("Six reinforced crown seams", seam, crown_seams, 0.005)
    tube("Paired stitched seams", sewing, crown_stitches, 0.0023)
    tube("Bound crown hem", seam,
         [path(-pi, pi, 144, lambda angle: crown_point(angle, 0.002, 0.009))], 0.012)
    tube("Crown hem stitches", upper_thread,
         stitches(-pi, pi, 254, lambda angle: crown_point(angle, 0.017, 0.011)), 0.0031)
    brim_stitches = []
    for offset in (0.42, 0.51, 0.60, 0.69, 0.78, 0.87, 0.95):
        brim_stitches.extend(stitches(-1.313, 1.313, 92, lambda theta: visor_point(theta, offset, 0.004)))
    tube("Concentric rows in visor", sewing, brim_stitches, 0.0025)
    tube("Visor bound edge", seam,
         [path(-1.375, 1.375, 110, lambda angle: visor_point(angle, 0.997, 0.001))], 0.010)

    eyelets = ((-0.75, 0.64), (0.70, 0.64), (-1.34, 0.62),
               (1.34, 0.62), (-2.65, 0.50), (2.65, 0.50))
    for index, (theta, eye_height) in enumerate(eyelets):
        ring = path(0, 2 * pi, 26,
                    lambda angle: crown_point(theta + 0.036 * cos(angle), eye_height + 0.022 * sin(angle), 0.010))
        tube(f"Eyelet {index + 1}", upper_thread, [ring], 0.010)
        center = crown_point(theta, eye_height, 0.007)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=0.022, location=center)
        grommet = bpy.context.object
        grommet.name = f"Eyelet recess {index + 1}"
        grommet.data.materials.append(eye)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=28, ring_count=16, radius=1, location=(0, 0.37, 1.018))
    button = bpy.context.object
    button.name = "Fabric-covered top button"
    button.scale = (0.091, 0.075, 0.038)
    button.data.materials.append(seam)
    for face in button.data.polygons:
        face.use_smooth = True

    if not args.no_mark and not args.logo:
        embroidery = simple_material("Off-white embroidery thread", (0.86, 0.85, 0.82), 0.72, 0.45)
        outline = []
        for delta in (-0.012, 0.0, 0.012):
            outline.append(path(0, 2 * pi, 110, lambda angle: crown_point(
                -0.018 + (0.142 + delta) * cos(angle), 0.337 + (0.105 + 0.65 * delta) * sin(angle), 0.013
            )))
        tube("Embroidered sample O", embroidery, outline, 0.009)


def aim_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def area_lamp(name, position, target, power, size):
    lamp = bpy.data.lights.new(name, "AREA")
    lamp.energy = power
    lamp.shape = "DISK"
    lamp.size = size
    obj = bpy.data.objects.new(name, lamp)
    bpy.context.collection.objects.link(obj)
    obj.location = position
    aim_at(obj, target)


def setup_render(args):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = args.denoise
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get("Background").inputs[0].default_value = (0.28, 0.28, 0.28, 1)
    scene.world.node_tree.nodes.get("Background").inputs[1].default_value = 0.31
    scene.view_settings.view_transform = "AgX"
    target = (0, args.aim_y, args.aim_z)
    elevation = args.camera_elevation * pi / 180
    azimuth = args.camera_azimuth * pi / 180
    camera_data = bpy.data.cameras.new("Calibrated front overhead camera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = args.ortho_scale
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = Vector(target) + 8 * Vector((sin(azimuth) * cos(elevation),
                                                    -cos(azimuth) * cos(elevation), sin(elevation)))
    aim_at(camera, target)
    scene.camera = camera
    area_lamp("Broad raised key", (-3.8, -4.1, 4.5), (0, -0.1, 0.3), 515, 4.0)
    area_lamp("Muted opposing fill", (2.8, -1.7, 4.2), (0, -0.1, 0.3), 146, 3.4)
    area_lamp("Upper background reflection", (-0.8, 2.8, 3.4), (0, 0, 0), 43, 2.6)


def main():
    args = options()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    create_cap(args)
    setup_render(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(args.output.resolve())
    if args.scene:
        args.scene.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=str(args.scene.resolve()))
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
