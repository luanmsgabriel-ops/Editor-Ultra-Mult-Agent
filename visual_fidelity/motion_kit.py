"""Discover reusable motion components and validate their project contracts."""
import argparse
import json
from pathlib import Path
from PIL import Image
from .light_sweep import Sweep, light_sweep

VERSION='0.9.0'
STAGE_VERSION='0.8.0'
LEGACY_VERSION='0.7.0'
CAPABILITIES={
    'orbit-occlusion': {'module':'visual_fidelity.orbit_type','requires':['occluder','depth_order'],'kind':'projected-spatial'},
    'light-sweep': {'module':'visual_fidelity.light_sweep','requires':['surface_alpha'],'kind':'linear-light-composite'},
    'complete-word-layers': {'module':'visual_fidelity.type_layout','requires':['complete_glyphs','layer_order'],'kind':'typography'},
    'metric-curve-type': {'module':'visual_fidelity.type_layout','requires':['font_metrics','path'],'kind':'typography'},
    'target-arrow-rig': {'module':'visual_fidelity.blender_motion_objects','requires':['separate_arrow','parent_transform'],'kind':'mesh-3d'},
    'metallic-keyhole': {'module':'visual_fidelity.blender_motion_objects','requires':['aperture_mask','bevel','moving_reflection'],'kind':'mesh-3d'},
}
LEGACY_CAPABILITIES=frozenset(CAPABILITIES)
CAPABILITIES.update({
    'device-screen-stage': {'module':'visual_fidelity.device_scene','requires':['independent_camera','screen_uv','frame_poses','asset_provenance'],'kind':'mesh-3d'},
    'measured-device-projection': {'module':'visual_fidelity.device_camera','requires':['measured_corners','assumed_intrinsics','camera_provenance'],'kind':'planar-pose-calibration'},
    'curved-metal-blades': {'module':'visual_fidelity.blade_scene','requires':['true_geometry','foreground_depth','frame_schedule'],'kind':'mesh-3d'},
})
STAGE_CAPABILITIES=frozenset(CAPABILITIES)
CAPABILITIES.update({
    'measured-element-motion': {
        'module':'visual_fidelity.motion_binding',
        'requires':['presentation_clock','element_identity','curve_profile','render_binding','coverage_report'],
        'kind':'measured-similarity-2d',
    },
})


def validate_manifest(manifest):
    """Fail early on missing implementations/evidence; never certify likeness.

    'reviewed' means a human/model inspection was recorded, not user approval.
    Store media in project assets, not the public repository or this registry.
    """
    pinned=manifest.get('engine_version')
    if pinned not in (VERSION,STAGE_VERSION,LEGACY_VERSION):raise ValueError('Pin the actual motion-kit version.')
    required=manifest.get('required_features',[])
    if not required or len(required)!=len(set(required)):raise ValueError('Provide unique required_features.')
    used=manifest.get('features',{})
    for name in required:
        if name not in CAPABILITIES:raise ValueError(f'Unknown capability: {name}')
        if pinned==LEGACY_VERSION and name not in LEGACY_CAPABILITIES:
            raise ValueError(f'{name}: requires motion-kit {VERSION}; legacy manifests remain limited to their original capabilities.')
        if pinned==STAGE_VERSION and name not in STAGE_CAPABILITIES:
            raise ValueError(f'{name}: requires motion-kit {VERSION}; 0.8 manifests retain their original capabilities.')
        item=used.get(name,{})
        if item.get('module')!=CAPABILITIES[name]['module']:
            raise ValueError(f'{name}: project is not wired to the registered engine module.')
        controls=item.get('controls',{})
        missing=[x for x in CAPABILITIES[name]['requires'] if not controls.get(x)]
        if missing:raise ValueError(f'{name}: missing controls {missing}')
        if item.get('status') not in ('implemented','tested','reviewed'):
            raise ValueError(f'{name}: unsupported implementation status')
        if item['status'] in ('tested','reviewed') and not item.get('evidence'):
            raise ValueError(f'{name}: evidence required')
    for asset in manifest.get('lettering_assets',[]):
        if asset.get('used_as_complete') and asset.get('coverage') not in ('complete-font','reconstructed-complete'):
            raise ValueError(f"{asset.get('id')}: visible fragments cannot be reused as complete letters.")
        if asset.get('coverage')=='reconstructed-complete' and not asset.get('inferred_regions'):
            raise ValueError('Reconstructed lettering must disclose inferred regions.')
    return {'engine_version':pinned,'validator_version':VERSION,'features':required,'contract_valid':True,
            'visual_similarity_certified':False,'user_approved':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('list')
    check=sub.add_parser('check');check.add_argument('manifest',type=Path)
    sweep=sub.add_parser('sweep');sweep.add_argument('input',type=Path);sweep.add_argument('output',type=Path)
    sweep.add_argument('--phase',type=float,required=True);sweep.add_argument('--angle',type=float,default=-12)
    sweep.add_argument('--width',type=float,default=.12);sweep.add_argument('--intensity',type=float,default=.78)
    args=parser.parse_args()
    if args.action=='list':result={'version':VERSION,'capabilities':CAPABILITIES}
    elif args.action=='check':result=validate_manifest(json.loads(args.manifest.read_text()))
    else:
        with Image.open(args.input)as im:
            image=light_sweep(im,args.phase,Sweep(angle=args.angle,width=args.width,intensity=args.intensity))
        args.output.parent.mkdir(parents=True,exist_ok=True);image.save(args.output)
        result={'output':str(args.output),'kind':'composite','alpha_preserved':True}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
