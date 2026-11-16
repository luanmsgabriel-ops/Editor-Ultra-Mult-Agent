// Editor Ultra adapter. The imported animation modules are the pinned MIT revision.
import {sampleTrack} from '../../../vendor/motionlab/src/engine/animation.js';
import {sampleAnimationGroupTime} from '../../../vendor/motionlab/src/engine/animation-groups.js';
import {sampleProceduralMotion, planProceduralSound} from '../../../vendor/motionlab/src/engine/sound-procedural.js';
import {shutterSamples} from '../../../vendor/motionlab/src/engine/temporal.js';

export {shutterSamples};

export function evaluateScene(scene, time) {
  const nodes = structuredClone(scene.nodes);
  const targets = new Map();
  const visit = node => {targets.set(node.id, node); (node.children ?? []).forEach(visit);};
  nodes.forEach(visit);
  const camera = structuredClone(scene.camera ?? null);
  if (camera) targets.set('camera', camera);
  const groupTimes = {};
  for (const id of Object.keys(scene.groups ?? {})) {
    groupTimes[id] = sampleAnimationGroupTime({animation:{groups:scene.groups}}, id, time);
  }
  for (const track of scene.tracks ?? []) {
    const t = track.group ? groupTimes[track.group] : time;
    targets.get(track.target)[track.property] = sampleTrack(track.keys, t);
  }
  const activate = (node, parentVisible = true) => {
    const active = parentVisible && time >= (node.start_s ?? 0) && time < (node.end_s ?? scene.duration_s);
    node.active = active;
    if (scene.mode === '2d' && !active) node.opacity = 0;
    if (node.type === 'text') node.font = `${node.font_size}px "motionlab_${node.font_id}"`;
    (node.children ?? []).forEach(child => activate(child, active));
  };
  nodes.forEach(node => activate(node));
  return {time_s:time, group_times:groupTimes, nodes, camera};
}

// A proposal generator, not an audio selector. The kits are intentionally unbound.
// Each shot is sampled separately so a cut never creates a fictitious traversal.
export function sonicPlan(scene, {rate = 60, density = .5, telemetry3d = null} = {}) {
  const boundaries = [0, ...(scene.cuts ?? []).filter(t => t > 0 && t < scene.duration_s), scene.duration_s];
  const candidates = [], evidence = [];
  for (let shot = 0; shot < boundaries.length - 1; shot++) {
    const start = boundaries[shot], end = boundaries[shot + 1], duration = end - start;
    const absoluteTime = t => Math.min(end - 1e-9, start + t);
    let telemetry;
    if (scene.mode === '2d') {
      telemetry = sampleProceduralMotion(t => evaluateScene(scene, absoluteTime(t)).nodes,
        {duration, rate, width:scene.width, height:scene.height});
    } else {
      if (!telemetry3d) throw new Error('3D telemetry adapter missing');
      const frames = [];
      for (let i = 0; i <= Math.ceil(duration * rate); i++) {
        const time = Math.min(duration, i / rate);
        frames.push({time, ...telemetry3d(evaluateScene(scene, absoluteTime(time)))});
      }
      telemetry = {kind:'three_projected_geometry', duration, rate, frames, cuts:[]};
    }
    const planned = planProceduralSound(telemetry, {
      density, cameraKit:'unassigned', accentKit:'unassigned', objectKit:'unassigned'
    });
    for (const event of planned.events) {
      const at = start + event.time;
      const row = Math.min(telemetry.frames.length - 1, Math.round(event.time * rate));
      const previous = Math.max(0, row - 1);
      const id = `telemetry:${shot}:${event.source}:${row}`;
      evidence.push({id, source_node:event.source, shot_index:shot,
        time_s:at, sampled_interval_s:[start + telemetry.frames[previous].time, start + telemetry.frames[row].time],
        before:telemetry.frames[previous].objects[event.source] ?? null,
        after:telemetry.frames[row].objects[event.source] ?? null,
        speed:planned.curves[event.source]?.[row] ?? null});
      candidates.push({id:`sonic:${candidates.length}`, time_s:at,
        duration_s:Math.min(event.duration, end - at), source_node:event.source,
        event_kind:event.graphic ?? event.module,
        intensity:Math.min(1, Math.max(0, event.gain)), pan:event.pan,
        intensity_basis:'upstream_motion_gain_heuristic_not_loudness',
        evidence_ids:[id], sound_asset:null, semantic_selection:false,
        upstream_candidate:event});
    }
  }
  return {schema_version:'motionlab-sonic/1', status:'candidates_only',
    telemetry_kind:scene.mode === '2d' ? 'evaluated_canvas_graph_bounds' : 'projected_three_geometry_bounds',
    visibility_is_pixel_verified:false, rate, density, candidates, evidence,
    limitations:['Motion measurements do not establish editorial intent or acoustic suitability.',
      'Bounding-box visibility is approximate; these events require editorial selection and listening.']};
}
