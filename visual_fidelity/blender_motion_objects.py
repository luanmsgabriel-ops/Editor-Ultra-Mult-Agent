"""Config-driven, editable Blender target/arrow and metallic aperture rigs.

Execute with Blender: blender -b --python blender_motion_objects.py -- config.json.
All geometry and animations are local to a root Empty. World motion can be keyed
on that root without baking the independent arrow or lighting animation.
Pure geometry helpers are importable without bpy for contract tests.
"""
import argparse
import json
import math
from pathlib import Path
import sys


def keyhole_outline(radius=0.9, center_y=0.52, bottom=-1.50,
                    bottom_half_width=0.90, opening_angle=50, segments=96):
    if radius <= 0 or segments < 12 or bottom >= center_y-radius:
        raise ValueError('Invalid keyhole dimensions')
    angles=[math.radians(-opening_angle+(180+2*opening_angle)*i/segments)
            for i in range(segments+1)]
    return [(radius*math.cos(a),center_y+radius*math.sin(a)) for a in angles]+[
        (-bottom_half_width,bottom),(bottom_half_width,bottom)]


def ring_mesh(points, inset=.91, depth=.10):
    if not 0 < inset < 1 or depth <= 0:
        raise ValueError('inset must be in (0, 1), depth positive')
    n=len(points)
    vertices=[(x*s,y*s,z) for z in (-depth/2,depth/2)
              for s in (1,inset) for x,y in points]
    faces=[]
    for i in range(n):
        j=(i+1)%n
        faces.extend([(i,j,2*n+j,2*n+i), (n+j,n+i,3*n+i,3*n+j),
                      (i,n+i,n+j,j), (2*n+j,3*n+j,3*n+i,2*n+i)])
    return vertices,faces


def validate_config(c):
    if c.get('kind') not in ('target','keyhole'):
        raise ValueError('kind must be target or keyhole')
    if int(c.get('frames',1)) < 1 or int(c.get('fps',24)) < 1:
        raise ValueError('frames/fps must be positive')
    if len(c.get('resolution',[320,320])) != 2 or min(c.get('resolution',[320,320])) < 16:
        raise ValueError('resolution must have two positive dimensions')
    return c


def build(c):
    import bpy
    from mathutils import Vector
    validate_config(c)
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    sc=bpy.context.scene;sc.render.engine='CYCLES';sc.cycles.samples=int(c.get('samples',12))
    sc.cycles.use_denoising=False;sc.cycles.max_bounces=5
    sc.render.resolution_x,sc.render.resolution_y=c.get('resolution',[320,320]);sc.render.resolution_percentage=100
    sc.render.image_settings.file_format='PNG';sc.render.image_settings.color_mode='RGBA';sc.render.film_transparent=True
    sc.render.fps=int(c.get('fps',24));sc.frame_start=1;sc.frame_end=int(c.get('frames',1))
    sc.view_settings.view_transform='AgX';sc.world.color=(.14,.14,.14)
    root=bpy.data.objects.new('MotionRoot',None);sc.collection.objects.link(root)
    def material(name,color,metallic=0,roughness=.25,coat=.4):
        m=bpy.data.materials.new(name);m.use_nodes=True;p=m.node_tree.nodes.get('Principled BSDF')
        p.inputs['Base Color'].default_value=(*color,1);p.inputs['Metallic'].default_value=metallic
        p.inputs['Roughness'].default_value=roughness;p.inputs['Coat Weight'].default_value=coat
        p.inputs['Coat Roughness'].default_value=.16;return m
    def finish(obj,mat,parent=root):
        obj.parent=parent;obj.data.materials.append(mat)
        for p in obj.data.polygons:p.use_smooth=True
        bevel=obj.modifiers.new('Rounded machined edge','BEVEL');bevel.width=.025;bevel.segments=3
        obj.modifiers.new('Weighted normals','WEIGHTED_NORMAL');return obj
    def cylinder(name,radius,depth,z,mat):
        bpy.ops.mesh.primitive_cylinder_add(vertices=96,radius=radius,depth=depth,location=(0,0,z));obj=bpy.context.object;obj.name=name;return finish(obj,mat)
    def light(name,loc,energy,size,color=(1,1,1)):
        data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.shape='DISK';data.size=size;data.color=color
        obj=bpy.data.objects.new(name,data);sc.collection.objects.link(obj);obj.location=loc
        obj.rotation_euler=(Vector((0,0,0))-obj.location).to_track_quat('-Z','Y').to_euler();return obj
    if c['kind']=='target':
        red=material('Target enamel',c.get('red',[.65,.004,.008]),.18,.23)
        white=material('Ivory ring',c.get('white',[.95,.91,.81]),.1,.28)
        metal=material('Target rim',[.32,.025,.025],.65,.23)
        blue=material('Arrow blue',c.get('arrow_color',[.025,.29,.57]),.2,.24)
        cylinder('Target thickness',.81,.16,0,metal)
        for i,(r,m) in enumerate(zip([.79,.62,.46,.30,.15],[red,white,red,white,red])):cylinder('Target face ring '+str(i),r,.016,.092+i*.009,m)
        arrow=bpy.data.objects.new('ArrowRig',None);sc.collection.objects.link(arrow);arrow.parent=root
        # Shaft points out of the target toward camera-right, with separate fletching geometry.
        tip=Vector((.02,0,.18));tail=Vector((1.48,.12,.62));vec=tail-tip
        bpy.ops.mesh.primitive_cylinder_add(vertices=24,radius=.055,depth=vec.length,location=(tip+tail)/2)
        obj=bpy.context.object;obj.name='Arrow shaft';obj.rotation_euler=vec.to_track_quat('Z','Y').to_euler();finish(obj,blue,arrow)
        for i,ang in enumerate([0,math.pi/2]):
            axis=Vector((0,math.cos(ang)*.22,math.sin(ang)*.22));p=tail-vec.normalized()*.36
            verts=[tuple(p-axis*.28),tuple(tail-axis),tuple(tail-vec.normalized()*.10),tuple(tail+axis),tuple(p+axis*.28)]
            mesh=bpy.data.meshes.new('Fletching');mesh.from_pydata(verts,[],[tuple(range(len(verts)))]);mesh.update()
            obj=bpy.data.objects.new('Arrow fin '+str(i),mesh);sc.collection.objects.link(obj);finish(obj,blue,arrow)
            solid=obj.modifiers.new('Fin thickness','SOLIDIFY');solid.thickness=.035
        for f in range(1,sc.frame_end+1):
            t=(f-1)/max(1,sc.frame_end-1);root.rotation_euler=(math.radians(6+4*math.sin(t*5)),math.radians(-24+11*math.sin(t*4)),math.radians(-5))
            root.keyframe_insert('rotation_euler',frame=f)
            # An independently damped landing/wobble, not rotation of one flattened icon.
            settle=math.exp(-t*8);arrow.location=(.55*settle,.12*settle,.22*settle)
            arrow.rotation_euler=(0,math.radians(7*math.sin(t*30)*settle),math.radians(5*math.sin(t*25)*settle))
            arrow.keyframe_insert('location',frame=f);arrow.keyframe_insert('rotation_euler',frame=f)
        light('Soft key',(-3,4,5),400,4);light('Rim strip',(3,1,2),250,2)
    else:
        pts=keyhole_outline(**c.get('shape',{}));verts,faces=ring_mesh(pts,float(c.get('inset',.92)),float(c.get('depth',.13)))
        mesh=bpy.data.meshes.new('Keyhole aperture ring');mesh.from_pydata(verts,[],faces);mesh.update()
        obj=bpy.data.objects.new('Keyhole gold frame',mesh);sc.collection.objects.link(obj)
        gold=material('Brushed polished gold',c.get('gold',[.83,.43,.075]),.95,float(c.get('roughness',.24)),.15);finish(obj,gold)
        soft=light('Gold softbox',(-2,2,4),260,3,(1,.86,.65));sweep=light('Moving reflection',(-3,0,3),500,1.4,(1,.96,.86))
        light('Bottom rim',(0,-3,2),130,1.8,(1,.72,.32))
        for f in range(1,sc.frame_end+1):
            t=(f-1)/max(1,sc.frame_end-1);sweep.location=(-3+6*t,2*math.sin(t*math.pi),3)
            sweep.rotation_euler=(Vector((0,0,0))-sweep.location).to_track_quat('-Z','Y').to_euler()
            sweep.keyframe_insert('location',frame=f);sweep.keyframe_insert('rotation_euler',frame=f)
        c['_aperture']=[[x*c.get('inset',.92),y*c.get('inset',.92)] for x,y in pts]
    bpy.ops.object.camera_add(location=tuple(c.get('camera_location',[0,0,8])))
    cam=bpy.context.object;cam.name='Camera';cam.rotation_euler=(Vector((0,0,0))-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.type='ORTHO';cam.data.ortho_scale=float(c.get('ortho_scale',3.6));sc.camera=cam
    for f,row in c.get('root_keyframes',{}).items():
        if 'location' in row:root.location=row['location'];root.keyframe_insert('location',frame=int(f))
        if 'scale' in row:root.scale=row['scale'];root.keyframe_insert('scale',frame=int(f))
    return sc,c


def main():
    import bpy
    args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    p=argparse.ArgumentParser();p.add_argument('config',type=Path);a=p.parse_args(args)
    c=json.loads(a.config.read_text());sc,c=build(c);out=Path(c['output']).resolve();out.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
    (out/'recipe.json').write_text(json.dumps(c,indent=2))
    for f in range(1,sc.frame_end+1):
        sc.frame_set(f);sc.render.filepath=str(out/f'{f:04d}.png');bpy.ops.render.render(write_still=True)

if __name__=='__main__':main()
