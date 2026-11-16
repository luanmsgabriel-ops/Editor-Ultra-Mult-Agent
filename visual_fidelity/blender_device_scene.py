"""Blender 4.3 runner for volumetric, UV-mapped smartphone product scenes.

Run through ``python -m visual_fidelity.device_scene render recipe.json``.
Only the display surface is planar. Chassis, glass slab, rear panel, camera
island, lens barrels, rings and buttons are independent solid geometry.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from visual_fidelity.device_scene import (DEFAULT_GEOMETRY, frame_state,
    load_config, merge, rounded_prism, rounded_rect_outline, screen_geometry, screen_uv)


def build(config):
    import bpy
    from mathutils import Vector

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = config.get("engine", "CYCLES")
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = int(config.get("samples", 12))
        scene.cycles.use_denoising = bool(config.get("denoise", False))
        scene.cycles.max_bounces = int(config.get("max_bounces", 4))
        scene.cycles.diffuse_bounces = 2
        scene.cycles.glossy_bounces = 2
        scene.cycles.transparent_max_bounces = 4
        scene.render.use_persistent_data = True
    else:
        scene.eevee.taa_render_samples = int(config.get("samples", 12))
        scene.eevee.use_raytracing = bool(config.get("raytracing", False))
        scene.eevee.use_shadows = bool(config.get("shadows", True))
        scene.eevee.shadow_resolution_scale = float(config.get("shadow_resolution_scale", 0.5))
    scene.render.resolution_x, scene.render.resolution_y = config.get("resolution", [720, 1280])
    scene.render.resolution_percentage = 100
    scene.render.fps = int(config.get("fps", 30))
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = int(config.get("png_compression", 15))
    scene.render.film_transparent = bool(config.get("transparent", True))
    scene.render.use_file_extension = True
    scene.render.use_motion_blur = bool(config.get("motion_blur", False))
    scene.render.motion_blur_shutter = float(config.get("shutter", 0.35))
    scene.view_settings.view_transform = config.get("view_transform", "Standard")
    scene.view_settings.look = "None"
    scene.view_settings.exposure = float(config.get("exposure", 0))
    scene.view_settings.gamma = 1.0
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (*config.get("world_color", [0.08, 0.08, 0.08]), 1)
    bg.inputs["Strength"].default_value = float(config.get("world_strength", 0.3))
    scene.frame_start = min(row["frame"] for row in config["frames"])
    scene.frame_end = max(row["frame"] for row in config["frames"])
    scene["device_scene_recipe"] = json.dumps(config, ensure_ascii=False)
    scene["camera_provenance"] = "Authored product camera, not a recovered original camera solve"

    def material(name, color, metallic=0.0, roughness=0.3, coat=0.0):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        shader = mat.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = (*color, 1)
        shader.inputs["Metallic"].default_value = metallic
        shader.inputs["Roughness"].default_value = roughness
        shader.inputs["Coat Weight"].default_value = coat
        shader.inputs["Coat Roughness"].default_value = 0.15
        return mat

    def finish(obj, mat, parent, bevel=0.0):
        obj.parent = parent
        obj.data.materials.append(mat)
        if bevel:
            mod = obj.modifiers.new("Machined edge radius", "BEVEL")
            mod.width = bevel
            mod.segments = 3
            mod.limit_method = "ANGLE"
            mod.angle_limit = math.radians(30)
            mod.harden_normals = True
            normals = obj.modifiers.new("Weighted face normals", "WEIGHTED_NORMAL")
            normals.keep_sharp = True
        return obj

    def prism(name, width, height, depth, radius, location, mat, parent, bevel=0.0, segments=12):
        verts, faces = rounded_prism(width, height, depth, radius, segments)
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        obj.location = location
        for poly in mesh.polygons:
            poly.use_smooth = poly.index >= 2
        return finish(obj, mat, parent, bevel)

    def cylinder(name, radius, depth, location, mat, parent):
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=radius, depth=depth, location=location)
        obj = bpy.context.object
        obj.name = name
        for poly in obj.data.polygons:
            poly.use_smooth = len(poly.vertices) == 4
        return finish(obj, mat, parent, min(depth/4, 0.002))

    def torus(name, radius, minor, location, mat, parent):
        bpy.ops.mesh.primitive_torus_add(major_segments=48, minor_segments=12, location=location,
                                        major_radius=radius, minor_radius=minor)
        obj = bpy.context.object
        obj.name = name
        for poly in obj.data.polygons:
            poly.use_smooth = True
        return finish(obj, mat, parent)

    def display(name, spec, mat, parent):
        pts = rounded_rect_outline(spec["width"], spec["height"], spec["radius"], 16)
        mesh = bpy.data.meshes.new(name)
        # A triangle fan avoids unstable N-gon tessellation on curved UV corners.
        verts = [(0, 0, spec["z"])] + [(x, y, spec["z"]) for x, y in pts]
        faces = [(0, i+1, (i+1) % len(pts)+1) for i in range(len(pts))]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        uv = mesh.uv_layers.new(name="DisplayUV")
        for loop in mesh.loops:
            x, y, _ = verts[loop.vertex_index]
            uv.data[loop.index].uv = screen_uv(x, y, spec["width"], spec["height"])
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        return finish(obj, mat, parent)

    roots, screens, screen_nodes, device_specs = {}, {}, {}, {}
    cards, material_defaults = {}, {}
    for device in config["devices"]:
        name = device["id"]
        g = merge(DEFAULT_GEOMETRY, device.get("geometry", {}))
        w, h, depth = g["width"], g["height"], g["depth"]
        # Detail proportions follow the body dimensions, not a source-specific mesh.
        unit = w/0.78
        root = bpy.data.objects.new(name+".Rig", None)
        scene.collection.objects.link(root)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = w/2
        root["coordinate_convention"] = "+X right; +Y top; +Z display/front"
        roots[name] = root
        colors = device.get("materials", {})
        chassis = material(name+".Chassis", colors.get("chassis", [0.3, 0.32, 0.35]), 0.95, 0.22)
        back = material(name+".Rear satin glass", colors.get("back", [0.68, 0.69, 0.71]), 0.1, 0.3, 0.25)
        black = material(name+".Black bezel", [0.003, 0.003, 0.004], 0.15, 0.22, 0.1)
        island_color = [0.62, 0.63, 0.65] if device.get("camera_layout") == "bar" else [0.33, 0.35, 0.38]
        island = material(name+".Camera island", colors.get("camera_island", island_color), 0.65, 0.26, 0.1)
        lens_edge = material(name+".Lens anodized barrels", [0.035, 0.04, 0.05], 0.85, 0.19)
        lens_ring = material(name+".Lens polished rings", [0.42, 0.46, 0.49], 1.0, 0.13)
        lens_glass = material(name+".Lens optical glass", [0.007, 0.014, 0.022], 0.5, 0.075, 0.8)
        iris = material(name+".Lens internal optics", [0.008, 0.02, 0.025], 0.55, 0.16)
        flash = material(name+".Flash diffuser", [0.8, 0.76, 0.61], 0.05, 0.32)
        prism(name+".Chassis", w, h, depth, g["corner_radius"], (0, 0, 0), chassis, root, g["edge_bevel"], g["corner_segments"])
        prism(name+".Rear panel", w-0.012*unit, h-0.012*unit, 0.004*unit,
              g["corner_radius"]-0.006*unit, (0, 0, -depth/2-0.001*unit), back, root, 0.001*unit)
        prism(name+".Front glass slab", w-0.012*unit, h-0.012*unit, 0.004*unit,
              g["corner_radius"]-0.006*unit, (0, 0, depth/2+0.001*unit), black, root, 0.001*unit)
        screen_mat = material(name+".Display glass", [0.0, 0.0, 0.0], 0.0,
                              float(device.get("screen_roughness", 0.2)), 0.04)
        shader = screen_mat.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Specular IOR Level"].default_value = float(device.get("screen_reflection", 0.12))
        shader.inputs["Emission Strength"].default_value = float(device.get("screen_emission", 1.0))
        shader.inputs["Emission Color"].default_value = (*device.get("screen_color", [0, 0, 0]), 1)
        tex = screen_mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.name = "Authored screen content"
        tex.interpolation = "Linear"
        tex.extension = "EXTEND"
        # Link is added only when an image is assigned, preserving black screens.
        spec = screen_geometry(g)
        screens[name] = display(name+".UV display", spec, screen_mat, root)
        screen_nodes[name] = (tex, shader, screen_mat)
        device_specs[name] = spec
        if device.get("front_sensor", True):
            prism(name+".Front sensor island", 0.135*unit, 0.031*unit, 0.002*unit, 0.015*unit,
                  (0, h/2-0.057*unit, spec["z"]+0.0015*unit), black, root, 0.0, 8)
        # Rear side is -Z. Positive local X appears on the viewer's left from behind.
        if device.get("rear_cameras", True):
            bar = device.get("camera_layout", "island") == "bar"
            cx, cy = w/2-0.212*unit, h/2-0.225*unit
            back_z = -depth/2
            if bar:
                panel_h = min(0.50*unit, h*0.4)
                cy = h/2-panel_h/2-0.01*unit
                prism(name+".Full width camera bar", w-0.018*unit, panel_h, 0.018*unit, 0.06*unit,
                      (0, cy, back_z-0.012*unit), island, root, 0.004*unit)
            else:
                prism(name+".Triple camera island", 0.37*unit, 0.405*unit, 0.018*unit, 0.06*unit,
                      (cx, cy, back_z-0.012*unit), island, root, 0.004*unit)
            for j, (dx, dy) in enumerate(((0.09, 0.097), (-0.092, 0), (0.09, -0.098))):
                x, y = cx+dx*unit, cy+dy*unit
                cylinder(name+f".Lens {j+1} barrel", 0.079*unit, 0.026*unit,
                         (x, y, back_z-0.032*unit), lens_edge, root)
                torus(name+f".Lens {j+1} silver rim", 0.072*unit, 0.006*unit,
                      (x, y, back_z-0.045*unit), lens_ring, root)
                cylinder(name+f".Lens {j+1} glass", 0.065*unit, 0.003*unit,
                         (x, y, back_z-0.045*unit), lens_glass, root)
                torus(name+f".Lens {j+1} inner optic", 0.033*unit, 0.003*unit,
                      (x, y, back_z-0.047*unit), iris, root)
            sensor_x = -w/2+0.10*unit if bar else cx-0.096*unit
            cylinder(name+".Camera flash", (0.028 if bar else 0.022)*unit, 0.004*unit,
                     (sensor_x, cy+0.14*unit, back_z-0.024*unit), flash, root)
            cylinder(name+".Depth sensor", (0.027 if bar else 0.02)*unit, 0.004*unit,
                     (sensor_x, cy-0.045*unit if bar else cy-0.14*unit, back_z-0.024*unit), black, root)
        button_positions = ((w/2, h*0.15, 0.16*unit), (-w/2, h*0.18, 0.1*unit), (-w/2, h*0.09, 0.1*unit)) if device.get("side_buttons", True) else []
        for j, (x, y, bh) in enumerate(button_positions):
            prism(name+f".Side button {j+1}", 0.012*unit, bh, depth*0.3,
                  0.005*unit, (x, y, 0), chassis, root, 0.001*unit, 4)
        # Optional rear graphic, carried in local coordinates like the display.
        if device.get("back_texture"):
            back_spec = {"width": w-0.025*unit, "height": h-0.025*unit,
                         "radius": g["corner_radius"]-0.013*unit, "z": 0.0}
            back_mat = material(name+".Rear graphic", [0.7, 0.7, 0.7], 0.05, 0.3)
            node = back_mat.node_tree.nodes.new("ShaderNodeTexImage")
            node.image = bpy.data.images.load(device["back_texture"], check_existing=True)
            back_mat.node_tree.links.new(node.outputs["Color"], back_mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"])
            obj = display(name+".Rear graphic surface", back_spec, back_mat, root)
            obj.rotation_euler.y = math.pi
            obj.location.z = -depth/2-0.0035*unit
        material_defaults[name] = []
        for mat in bpy.data.materials:
            if mat.name.startswith(name+".") and mat != screen_mat and mat.use_nodes:
                shader = mat.node_tree.nodes.get("Principled BSDF")
                if shader:
                    material_defaults[name].append((shader, {key: tuple(shader.inputs[key].default_value) if key == "Base Color" else shader.inputs[key].default_value
                        for key in ("Base Color", "Metallic", "Roughness", "Coat Weight")}))
        cards[name] = {}
        for index, card in enumerate(device.get("cards", [])):
            card_id = card.get("id", f"card{index+1}")
            u, v, cw, ch = card["rect_uv"]
            parent = bpy.data.objects.new(name+".CardRig."+card_id, None)
            scene.collection.objects.link(parent)
            parent.parent = root
            card_mat = material(name+".Card material."+card_id, [0, 0, 0], 0, 0.45)
            card_shader = card_mat.node_tree.nodes.get("Principled BSDF")
            card_shader.inputs["Specular IOR Level"].default_value = 0.05
            card_shader.inputs["Emission Strength"].default_value = float(card.get("emission", 1))
            node = card_mat.node_tree.nodes.new("ShaderNodeTexImage")
            node.interpolation = "Linear"
            node.extension = "EXTEND"
            if card.get("texture"):
                node.image = bpy.data.images.load(card["texture"], check_existing=True)
                card_mat.node_tree.links.new(node.outputs["Color"], card_shader.inputs["Emission Color"])
                card_mat.node_tree.links.new(node.outputs["Alpha"], card_shader.inputs["Alpha"])
            card_spec = {"width": cw*spec["width"], "height": ch*spec["height"], "z": 0,
                         "radius": min(float(card.get("radius", 0.003*unit)), cw*spec["width"]/2, ch*spec["height"]/2)}
            obj = display(name+".Card."+card_id, card_spec, card_mat, parent)
            solid = obj.modifiers.new("Card physical thickness", "SOLIDIFY")
            solid.thickness = float(card.get("thickness", 0.001*unit))
            solid.offset = -1
            cards[name][card_id] = {"root": parent, "object": obj, "node": node, "base": card, "size": [cw, ch]}

    for index, light in enumerate(config.get("lights", [
            {"location": [-2.0, 2.4, 3.4], "energy": 150, "size": 2.0, "size_y": 3.8},
            {"location": [2.1, -0.5, 2.0], "energy": 70, "size": 1.0, "size_y": 3.3},
            {"location": [-1.6, 1.4, -2.2], "energy": 120, "size": 1.2, "size_y": 3.0},
            {"location": [1.4, -0.8, -2.8], "energy": 70, "size": 2.2, "size_y": 1.2},
    ])):
        data = bpy.data.lights.new(f"Studio softbox {index+1}", "AREA")
        data.energy = light.get("energy", 100)
        data.use_shadow = bool(light.get("shadow", config.get("shadows", True)))
        data.shape = "RECTANGLE"
        data.size = light.get("size", 2)
        data.size_y = light.get("size_y", data.size)
        data.color = light.get("color", [1, 1, 1])
        obj = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(obj)
        obj.location = light["location"]
        obj.rotation_euler = (Vector(light.get("target", [0, 0, 0]))-obj.location).to_track_quat("-Z", "Y").to_euler()
    camera_data = bpy.data.cameras.new("Product camera")
    camera = bpy.data.objects.new("Product camera", camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = "PERSP"
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.clip_start = 0.005
    camera_data.clip_end = 1000
    scene.camera = camera
    focus = bpy.data.objects.new("DOF focus", None)
    scene.collection.objects.link(focus)
    camera_data.dof.focus_object = focus
    layer = scene.view_layers[0]
    if config.get("passes"):
        layer.use_pass_z = "depth" in config["passes"]
        layer.use_pass_normal = "normal" in config["passes"]
        layer.use_pass_object_index = "object_index" in config["passes"]
        for number, root in enumerate(roots.values(), 1):
            for obj in root.children_recursive:
                obj.pass_index = number
    return {"scene": scene, "camera": camera, "focus": focus, "roots": roots,
            "screens": screens, "screen_nodes": screen_nodes, "screen_specs": device_specs,
            "cards": cards, "material_defaults": material_defaults}


def _orient(obj, state):
    from mathutils import Matrix, Quaternion
    if "rotation_quaternion_wxyz" in state:
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = Quaternion(state["rotation_quaternion_wxyz"]).normalized()
    elif "rotation_matrix" in state:
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = Matrix(state["rotation_matrix"]).to_quaternion()
    else:
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = [math.radians(v) for v in state.get("rotation_deg", [0, 0, 0])]


def apply_state(rig, state, keyframe=False, textures=True):
    import bpy
    from mathutils import Matrix, Quaternion, Vector

    frame = state["frame"]
    for device in state["devices"]:
        name = device["id"]
        root = rig["roots"][name]
        root.location = device.get("location", [0, 0, 0])
        root.scale = device.get("scale", [1, 1, 1])
        _orient(root, device)
        for child in root.children_recursive:
            child.hide_render = not device.get("visible", True)
            if keyframe:
                child.keyframe_insert("hide_render", frame=frame)
        if keyframe:
            for prop in ("location", "scale", "rotation_quaternion" if root.rotation_mode == "QUATERNION" else "rotation_euler"):
                root.keyframe_insert(prop, frame=frame)
        style = device.get("style", "studio")
        for shader, defaults in rig["material_defaults"][name]:
            for key, value in defaults.items():
                shader.inputs[key].default_value = value
            if style == "clay":
                shader.inputs["Base Color"].default_value = (*device.get("clay_color", [0.55, 0.57, 0.59]), 1)
            if style in {"clay", "matte"}:
                shader.inputs["Metallic"].default_value = 0
                shader.inputs["Roughness"].default_value = 0.8
                shader.inputs["Coat Weight"].default_value = 0
        card_states = {card.get("id", f"card{index+1}"): card for index, card in enumerate(device.get("cards", []))}
        for card_id, entry in rig["cards"][name].items():
            card = merge(entry["base"], card_states.get(card_id, {}))
            u, v, cw, ch = card["rect_uv"]
            spec = rig["screen_specs"][name]
            parent = entry["root"]
            parent.location = ((u+cw/2-0.5)*spec["width"], (v+ch/2-0.5)*spec["height"], spec["z"]+float(card.get("lift", 0.02)))
            parent.scale = (cw/entry["size"][0], ch/entry["size"][1], 1)
            _orient(parent, card)
            entry["object"].hide_render = not (device.get("visible", True) and card.get("visible", True))
            if keyframe:
                for prop in ("location", "scale", "rotation_quaternion" if parent.rotation_mode == "QUATERNION" else "rotation_euler"):
                    parent.keyframe_insert(prop, frame=frame)
                entry["object"].keyframe_insert("hide_render", frame=frame)
            if textures and card.get("texture") and (not entry["node"].image or entry["node"].image.filepath != card["texture"]):
                entry["node"].image = bpy.data.images.load(card["texture"], check_existing=True)
        if textures:
            node, shader, mat = rig["screen_nodes"][name]
            texture = device.get("screen_texture") if device.get("screen_mode", "texture") == "texture" else None
            if texture:
                texture = str(Path(texture).resolve(strict=True))
                if not node.image or node.image.filepath != texture:
                    previous = node.image
                    node.image = bpy.data.images.load(texture, check_existing=True)
                    node.image.colorspace_settings.name = "sRGB"
                    if previous and not previous.users:
                        bpy.data.images.remove(previous)
                if not shader.inputs["Emission Color"].is_linked:
                    mat.node_tree.links.new(node.outputs["Color"], shader.inputs["Emission Color"])
            else:
                for link in list(shader.inputs["Emission Color"].links):
                    mat.node_tree.links.remove(link)
                shader.inputs["Emission Color"].default_value = (*([0, 0, 0] if device.get("screen_mode") == "black" else device.get("screen_color", [0, 0, 0])), 1)
            shader.inputs["Emission Strength"].default_value = float(device.get("screen_emission", 1.0))
    cam = rig["camera"]
    camera = state["camera"]
    cam.location = camera["location"]
    cam.rotation_mode = "QUATERNION"
    if "rotation_quaternion_wxyz" in camera or "rotation_matrix" in camera:
        _orient(cam, camera)
    else:
        forward = (Vector(camera["target"])-cam.location).normalized()
        # Explicit world +Y up: Blender's generic track helper assumes world Z
        # and would unexpectedly roll a portrait phone when orbiting off-axis.
        preferred_up = Vector(camera.get("up", [0, 1, 0]))
        if abs(forward.dot(preferred_up.normalized())) > 0.999:
            preferred_up = Vector((1, 0, 0))
        right = forward.cross(preferred_up).normalized()
        up = right.cross(forward).normalized()
        orientation = Matrix((right, up, -forward)).transposed().to_quaternion()
        # Camera local +Z points backwards; positive roll rotates the camera body.
        cam.rotation_quaternion = orientation @ Quaternion((0, 0, 1), math.radians(camera.get("roll_deg", 0)))
    cam.data.lens = camera["lens_mm"]
    cam.data.sensor_width = camera["sensor_width_mm"]
    cam.data.shift_x = float(camera.get("shift_x", 0))
    cam.data.shift_y = float(camera.get("shift_y", 0))
    cam.data.dof.use_dof = bool(camera["dof"].get("enabled", False))
    cam.data.dof.aperture_fstop = float(camera["dof"].get("fstop", 4))
    rig["focus"].location = camera["dof"].get("focus_target", camera["target"])
    if keyframe:
        for prop in ("location", "rotation_quaternion"):
            cam.keyframe_insert(prop, frame=frame)
        for prop in ("lens", "shift_x", "shift_y", "dof.use_dof", "dof.aperture_fstop"):
            cam.data.keyframe_insert(prop, frame=frame)
        rig["focus"].keyframe_insert("location", frame=frame)
    bpy.context.view_layer.update()


def project_metadata(rig, state):
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    scene, camera = rig["scene"], rig["camera"]
    width, height = scene.render.resolution_x, scene.render.resolution_y
    result = {"frame": state["frame"], "camera_matrix_world": [list(row) for row in camera.matrix_world],
              "lens_mm": camera.data.lens, "devices": {}}
    for device in state["devices"]:
        name = device["id"]
        spec, obj = rig["screen_specs"][name], rig["roots"][name]
        # The bounding rectangle includes the rounded-corner cutouts.
        corners = [(-spec["width"]/2, spec["height"]/2, spec["z"]),
                   (spec["width"]/2, spec["height"]/2, spec["z"]),
                   (spec["width"]/2, -spec["height"]/2, spec["z"]),
                   (-spec["width"]/2, -spec["height"]/2, spec["z"])]
        world = [obj.matrix_world @ Vector(p) for p in corners]
        ndc = [world_to_camera_view(scene, camera, p) for p in world]
        normal = (obj.matrix_world.to_3x3().inverted().transposed() @ Vector((0, 0, 1))).normalized()
        center = obj.matrix_world @ Vector((0, 0, spec["z"]))
        result["devices"][name] = {"screen_corner_order": ["top_left", "top_right", "bottom_right", "bottom_left"],
            "screen_world": [list(p) for p in world],
            "screen_pixels": [[p.x*width, (1-p.y)*height] for p in ndc],
            "camera_depth": [p.z for p in ndc], "front_facing": normal.dot(camera.location-center) > 0,
            "visible": device.get("visible", True), "matrix_world": [list(row) for row in obj.matrix_world]}
    return result


def set_render_border(rig, config):
    """Optional conservative geometry bounds, retaining the full output raster."""
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    scene, camera = rig["scene"], rig["camera"]
    scene.render.use_border = False
    scene.render.use_crop_to_border = False
    if not config.get("auto_border", False):
        return
    points = []
    for root in rig["roots"].values():
        for obj in root.children_recursive:
            if obj.type == "MESH" and not obj.hide_render:
                points.extend(world_to_camera_view(scene, camera, obj.matrix_world @ Vector(p)) for p in obj.bound_box)
    if not points or min(p.z for p in points) <= camera.data.clip_start:
        return
    pad_x = float(config.get("border_padding", 48))/scene.render.resolution_x
    pad_y = float(config.get("border_padding", 48))/scene.render.resolution_y
    xmin, xmax = max(0, min(p.x for p in points)-pad_x), min(1, max(p.x for p in points)+pad_x)
    ymin, ymax = max(0, min(p.y for p in points)-pad_y), min(1, max(p.y for p in points)+pad_y)
    if xmin >= xmax or ymin >= ymax:
        return
    scene.render.border_min_x, scene.render.border_max_x = xmin, xmax
    scene.render.border_min_y, scene.render.border_max_y = ymin, ymax
    scene.render.use_border = True


def main():
    import bpy
    args = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--frames")
    options = parser.parse_args(args)
    config = load_config(options.config)
    output = Path(config["output"])
    output.mkdir(parents=True, exist_ok=True)
    rig = build(config)
    scene = rig["scene"]
    # Store editable camera and device trajectories in the .blend before rendering.
    for row in config["frames"]:
        apply_state(rig, frame_state(config, row), keyframe=True, textures=False)
    for datablock in list(bpy.data.objects)+list(bpy.data.cameras):
        if datablock.animation_data and datablock.animation_data.action:
            for curve in datablock.animation_data.action.fcurves:
                for key in curve.keyframe_points:
                    key.interpolation = "LINEAR"
    first = frame_state(config, config["frames"][0])
    scene.frame_set(first["frame"])
    apply_state(rig, first)
    bpy.ops.wm.save_as_mainfile(filepath=str(output/"scene.blend"))
    (output/"recipe.resolved.json").write_text(json.dumps(config, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    selected = set(int(f) for f in options.frames.split(",")) if options.frames else None
    if selected and selected-set(row["frame"] for row in config["frames"]):
        raise ValueError("Requested frames are not authored in the recipe")
    metadata = []
    for row in config["frames"]:
        if selected is not None and row["frame"] not in selected:
            continue
        state = frame_state(config, row)
        scene.frame_set(state["frame"])
        apply_state(rig, state)
        set_render_border(rig, config)
        stem = f"{state['frame']:06d}"
        scene.render.filepath = str(output/(stem+".png"))
        started = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        info = project_metadata(rig, state)
        info["render_seconds"] = round(time.perf_counter()-started, 4)
        if config.get("passes"):
            # A multilayer EXR retains actual render passes, in scene-linear space.
            scene.render.image_settings.file_format = "OPEN_EXR_MULTILAYER"
            scene.render.image_settings.color_depth = "32"
            bpy.data.images["Render Result"].save_render(str(output/(stem+".exr")), scene=scene)
            scene.render.image_settings.file_format = "PNG"
            scene.render.image_settings.color_depth = "8"
        (output/(stem+".json")).write_text(json.dumps(info, indent=2)+"\n", encoding="utf-8")
        metadata.append(info)
        print("DEVICE_RENDER", json.dumps({"frame": state["frame"], "seconds": info["render_seconds"], "output": scene.render.filepath}), flush=True)
    (output/"render-manifest.json").write_text(json.dumps({"engine": scene.render.engine, "blender_version": bpy.app.version_string,
        "samples": config.get("samples", 12), "resolution": config.get("resolution", [720, 1280]),
        "camera_provenance": "Authored product camera; no original camera solve claimed", "frames": metadata}, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
