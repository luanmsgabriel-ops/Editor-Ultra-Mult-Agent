// JSON stdin/stdout boundary. No scene JavaScript, shell strings, network or timers.
import {readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {createCanvas, ImageData, GlobalFonts} from '@napi-rs/canvas';
import * as THREE from 'three';
import {renderProcedural} from '../../../vendor/motionlab/src/engine/procedural.js';
import {evaluateScene, shutterSamples, sonicPlan} from './scene.mjs';
import {createThreeRenderer} from './raster.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const linear = v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
const encoded = v => v <= .0031308 ? v * 12.92 : 1.055 * v ** (1 / 2.4) - .055;
const lookup = Float32Array.from({length:256}, (_, i) => linear(i / 255));

function renderer(scene) {
  for (const font of scene.fonts ?? []) {
    if (hash(readFileSync(font.path)) !== font.sha256) throw new Error(`Font hash changed: ${font.id}`);
    if (font.format === 'font' && !GlobalFonts.registerFromPath(font.path, `motionlab_${font.id}`)) {
      throw new Error(`Font could not be loaded: ${font.id}`);
    }
  }
  const canvas = createCanvas(scene.width, scene.height), ctx = canvas.getContext('2d');
  const three = scene.mode === '3d' ? createThreeRenderer(scene) : null;
  function sample(time) {
    const state = evaluateScene(scene, time);
    if (three) return three.render(state).data;
    ctx.clearRect(0, 0, scene.width, scene.height);
    if (scene.background !== null) {
      ctx.fillStyle = scene.background; ctx.fillRect(0, 0, scene.width, scene.height);
    }
    renderProcedural(ctx, time, {width:scene.width, height:scene.height, nodes:state.nodes, clear:false});
    return ctx.getImageData(0, 0, scene.width, scene.height).data;
  }
  function frame(time, options) {
    const schedule = shutterSamples(time, {fps:scene.fps_value, duration:scene.duration_s,
      samples:options.samples, shutterAngle:options.shutter_angle, cuts:scene.cuts, profile:options.shutter_profile});
    let pixels;
    if (schedule.length === 1) pixels = sample(schedule[0].time);
    else {
      const accumulation = new Float64Array(scene.width * scene.height * 4);
      for (const exposure of schedule) {
        const rgba = sample(exposure.time);
        for (let i = 0; i < rgba.length; i += 4) {
          const alpha = rgba[i + 3] / 255, weight = alpha * exposure.weight;
          for (let c = 0; c < 3; c++) accumulation[i + c] += lookup[rgba[i + c]] * weight;
          accumulation[i + 3] += weight;
        }
      }
      pixels = new Uint8ClampedArray(accumulation.length);
      for (let i = 0; i < pixels.length; i += 4) {
        const alpha = accumulation[i + 3];
        if (alpha > 1e-10) for (let c = 0; c < 3; c++) pixels[i + c] = Math.round(Math.max(0, Math.min(1, encoded(accumulation[i + c] / alpha))) * 255);
        pixels[i + 3] = Math.round(alpha * 255);
      }
    }
    ctx.putImageData(new ImageData(pixels, scene.width, scene.height), 0, 0);
    return {png:canvas.toBuffer('image/png'), schedule, rgba:pixels};
  }
  return {frame, three, backend:three ? 'three-cpu-lambert-zbuffer/1' : 'motionlab-canvas2d-napi/1'};
}

function probe() {
  const base = {width:24, height:24, fps_value:24, duration_s:1, background:null, tracks:[], groups:{}, cuts:[], fonts:[]};
  const two = renderer({...base, mode:'2d', nodes:[{id:'proof', type:'rect', width:12, height:12, x:4, y:4, fill:'#ff0000'}]});
  const twoResult = two.frame(0, {samples:1, shutter_angle:0, shutter_profile:'box'});
  const three = renderer({...base, mode:'3d', nodes:[{id:'proof', type:'box', size:[1, 1, 1], material:{color:'#00ff00', unlit:true}}],
    camera:{position:[2, 2, 4], target:[0, 0, 0], fov:50, near:.1, far:100}, lights:[]});
  const threeResult = three.frame(0, {samples:1, shutter_angle:0, shutter_profile:'box'});
  const check = (result, channel) => {
    let visible = 0, transparent = 0;
    for (let i = 0; i < result.rgba.length; i += 4) {
      if (result.rgba[i + 3] && result.rgba[i + channel] > 0) visible++;
      if (!result.rgba[i + 3]) transparent++;
    }
    if (!visible || !transparent) throw new Error('Pixel proof failed');
    return {png_sha256:hash(result.png), visible_pixels:visible, transparent_pixels:transparent};
  };
  return {node:process.version, three_revision:THREE.REVISION, webgl:{available:false, used:false},
    backends:{canvas2d:{available:true, backend:two.backend, proof:check(twoResult, 0)},
      three_cpu:{available:true, backend:three.backend, proof:check(threeResult, 1)}}};
}

try {
  const request = JSON.parse(readFileSync(0, 'utf8'));
  let result;
  if (request.command === 'probe') result = probe();
  else if (request.command === 'evaluate') result = evaluateScene(request.scene, request.time_s);
  else if (request.command === 'schedule') result = shutterSamples(request.time_s, request.options);
  else if (request.command === 'sonic') {
    const three = request.scene.mode === '3d' ? createThreeRenderer(request.scene) : null;
    result = sonicPlan(request.scene, {...request.options, telemetry3d:three?.telemetry});
    three?.dispose();
  } else if (request.command === 'render') {
    const scene = request.scene, engine = renderer(scene), frames = [];
    for (let index = 0; index < scene.frame_count; index++) {
      const time_s = index / scene.fps_value, frame = engine.frame(time_s, request.options);
      const path = join(request.frames_dir, `${String(index).padStart(8, '0')}.png`);
      writeFileSync(path, frame.png, {flag:'wx'});
      frames.push({index, path, sha256:hash(frame.png), time_s, exposure:frame.schedule});
    }
    engine.three?.dispose();
    result = {backend:engine.backend, frames, alpha:'straight', color_space:'sRGB',
      temporal_integration:'linear-light-premultiplied-accumulation', three_revision:THREE.REVISION};
  } else throw new Error(`Unknown command: ${request.command}`);
  process.stdout.write(JSON.stringify(result));
} catch (error) {
  process.stderr.write(String(error.stack ?? error));
  process.exitCode = 1;
}
