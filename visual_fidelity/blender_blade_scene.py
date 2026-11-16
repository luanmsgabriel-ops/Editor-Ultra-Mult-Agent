"""Blender runner for curved solid metallic blades over transparent typography."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from visual_fidelity.blade_scene import swept_blade_mesh, validate_config
from visual_fidelity.device_scene import merge
from visual_fidelity.blender_device_scene import set_render_border


def build(config):
    import bpy
    import bmesh
    from mathutils import Vector
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = config.get("engine", "BLENDER_EEVEE_NEXT")
    if scene.render.engine == "BLENDER_EEVEE_NEXT":
        scene.eevee.taa_render_samples = config.get("samples", 4)
        scene.eevee.use_raytracing = False
        scene.eevee.use_shadows = False
    else:
        scene.cycles.samples = config.get("samples", 4)
        scene.cycles.use_denoising = False
        scene.render.use_persistent_data = True
    scene.render.resolution_x, scene.render.resolution_y = config.get("resolution", [720, 1280])
    scene.render.resolution_percentage = 100
    scene.render.fps = config.get("fps", 30)
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 15
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = config.get("exposure", 0)
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (*config.get("world_color", [.008, .012, .02]), 1)
    background.inputs["Strength"].default_value = config.get("world_strength", .15)
    scene.frame_start, scene.frame_end = config["frames"][0]["frame"], config["frames"][-1]["frame"]
    roots, shaders, tip_controls = {}, {}, {}
    for blade in config["blades"]:
        identifier = blade["id"]
        vertices, faces = swept_blade_mesh(**merge(config.get("geometry", {}), blade.get("geometry", {})))
        mesh = bpy.data.meshes.new(identifier+".Curved solid")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(mesh)
        bm.free()
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        root = bpy.data.objects.new(identifier+".Rig", None)
        scene.collection.objects.link(root)
        obj = bpy.data.objects.new(identifier+".Blade", mesh)
        scene.collection.objects.link(obj)
        obj.parent = root
        material = bpy.data.materials.new(identifier+".Blue metal")
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        look = merge(config.get("material", {}), blade.get("material", {}))
        shader.inputs["Base Color"].default_value = (*look.get("color", [.13, .18, .25]), 1)
        shader.inputs["Metallic"].default_value = look.get("metallic", .85)
        shader.inputs["Roughness"].default_value = look.get("roughness", .35)
        shader.inputs["Anisotropic"].default_value = look.get("anisotropic", .2)
        shader.inputs["Coat Weight"].default_value = look.get("coat", .05)
        # Optional local material falloff on the lower tip during a fast entry.
        # This shades the real solid; it does not alter its camera projection.
        nodes, links = material.node_tree.nodes, material.node_tree.links
        coords = nodes.new("ShaderNodeTexCoord")
        separate = nodes.new("ShaderNodeSeparateXYZ")
        links.new(coords.outputs["Generated"], separate.inputs[0])
        remap = nodes.new("ShaderNodeMapRange")
        remap.inputs["From Min"].default_value = 0
        remap.inputs["From Max"].default_value = .35
        remap.inputs["To Min"].default_value = 0
        remap.inputs["To Max"].default_value = 1
        remap.clamp = True
        links.new(separate.outputs["Y"], remap.inputs["Value"])
        power = nodes.new("ShaderNodeMath")
        power.operation = "POWER"
        power.inputs[1].default_value = 2
        links.new(remap.outputs["Result"], power.inputs[0])
        multiply = nodes.new("ShaderNodeMixRGB")
        multiply.blend_type = "MULTIPLY"
        multiply.inputs[0].default_value = 1
        multiply.inputs[1].default_value = (*look.get("color", [.13, .18, .25]), 1)
        links.new(power.outputs[0], multiply.inputs[2])
        mix = nodes.new("ShaderNodeMixRGB")
        mix.inputs[0].default_value = 0
        mix.inputs[1].default_value = (*look.get("color", [.13, .18, .25]), 1)
        links.new(multiply.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], shader.inputs["Base Color"])
        tip_controls[identifier] = mix.inputs[0]
        obj.data.materials.append(material)
        roots[identifier], shaders[identifier] = root, shader
    for index, light in enumerate(config.get("lights", [
            {"location": [-1.5, 2.5, 2.3], "energy": 35, "size": 1.5, "size_y": 1.8, "color": [.63, .78, 1]},
            {"location": [-2.5, -.1, 2.0], "energy": 8, "size": .3, "size_y": 4.2, "color": [.45, .62, .9]},
            {"location": [2.5, 2.0, 3], "energy": 15, "size": 3.5, "color": [.7, .8, 1]},
    ])):
        data = bpy.data.lights.new(f"Cool softbox {index}", "AREA")
        data.energy = light["energy"]
        data.shape = "RECTANGLE"
        data.size = light.get("size", 1)
        data.size_y = light.get("size_y", data.size)
        data.color = light.get("color", [1, 1, 1])
        data.use_shadow = False
        obj = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(obj)
        obj.location = light["location"]
        obj.rotation_euler = (Vector(light.get("target", [0, 0, 0]))-obj.location).to_track_quat("-Z", "Y").to_euler()
    camera_data = bpy.data.cameras.new("Blade local viewport")
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0, 0, config.get("camera_distance", 6))
    camera.rotation_euler = (0, 0, 0)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = config.get("viewport_height", 3.2)
    camera_data.clip_start = .01
    camera_data.clip_end = 100
    scene.camera = camera
    scene["blade_scene_recipe"] = json.dumps(config)
    return {"scene": scene, "camera": camera, "roots": roots, "shaders": shaders, "tip_controls": tip_controls}


def apply_state(rig, config, row, keyframe=False):
    import bpy
    for base in config["blades"]:
        identifier = base["id"]
        state = merge(base, row.get("blades", {}).get(identifier, {}))
        root = rig["roots"][identifier]
        root.location = state.get("location", [0, 0, 0])
        root.rotation_euler = [math.radians(v) for v in state.get("rotation_deg", [0, 0, 0])]
        root.scale = state.get("scale", [1, 1, 1])
        for child in root.children:
            child.hide_render = not state.get("visible", True)
            if keyframe:
                child.keyframe_insert("hide_render", frame=row["frame"])
        rig["shaders"][identifier].inputs["Alpha"].default_value = state.get("opacity", row.get("opacity", 1))
        rig["tip_controls"][identifier].default_value = state.get("tip_darkening", 0)
        if keyframe:
            for prop in ("location", "rotation_euler", "scale"):
                root.keyframe_insert(prop, frame=row["frame"])
    bpy.context.view_layer.update()


def main():
    import bpy
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--frames")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    config = validate_config(json.loads(args.config.read_text()))
    output = (args.config.parent/config["output"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    rig = build(config)
    for row in config["frames"]:
        apply_state(rig, config, row, keyframe=True)
    for root in rig["roots"].values():
        for curve in root.animation_data.action.fcurves:
            for key in curve.keyframe_points:
                key.interpolation = "LINEAR"
    first = config["frames"][0]
    rig["scene"].frame_set(first["frame"])
    apply_state(rig, config, first)
    bpy.ops.wm.save_as_mainfile(filepath=str(output/"blades.blend"))
    (output/"recipe.json").write_text(json.dumps(config, indent=2)+"\n")
    selected = set(int(f) for f in args.frames.split(",")) if args.frames else None
    results = []
    for row in config["frames"]:
        if selected is not None and row["frame"] not in selected:
            continue
        scene = rig["scene"]
        scene.frame_set(row["frame"])
        apply_state(rig, config, row)
        set_render_border(rig, {"auto_border": config.get("auto_border", True), "border_padding": config.get("border_padding", 12)})
        scene.render.filepath = str(output/f"{row['frame']:06d}.png")
        started = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        result = {"frame": row["frame"], "seconds": round(time.perf_counter()-started, 4), "output": scene.render.filepath}
        results.append(result)
        print("BLADE_RENDER", json.dumps(result), flush=True)
    (output/"render-manifest.json").write_text(json.dumps({"schema": "editor-ultra.blade-render.v1", "geometry": "Closed swept elliptical solids", "resolution": config.get("resolution", [720, 1280]), "frames": results}, indent=2)+"\n")


if __name__ == "__main__":
    main()
