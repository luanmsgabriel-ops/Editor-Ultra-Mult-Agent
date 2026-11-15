"""Export four ordered world points through the solved Blender camera."""
import argparse
import json
from pathlib import Path
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scene',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--objects',nargs=4,required=True,
                        help='Marcadores na ordem superior E/D, inferior D/E.')
    parser.add_argument('--start',type=int,default=1)
    parser.add_argument('--end',type=int,required=True,help='Quadro final inclusivo no Blender.')
    parser.add_argument('--video-start',type=int,default=0,help='Índice correspondente no vídeo.')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.end<args.start or args.video_start<0:
        parser.error('Intervalo de exportação inválido.')
    bpy.ops.wm.open_mainfile(filepath=str(args.scene.resolve()))
    scene=bpy.context.scene
    if scene.camera is None:
        parser.error('A cena precisa ter câmera ativa.')
    markers=[scene.objects.get(name) for name in args.objects]
    if any(obj is None for obj in markers):
        parser.error('Marcadores ausentes na cena.')
    quads={}
    for frame in range(args.start,args.end+1):
        scene.frame_set(frame)
        coords=[world_to_camera_view(scene,scene.camera,obj.matrix_world.translation) for obj in markers]
        label=str(args.video_start+frame-args.start)
        quads[label]=[[float(v.x),float(1-v.y)] for v in coords] if min(v.z for v in coords)>0 else None
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'quads':quads},indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
