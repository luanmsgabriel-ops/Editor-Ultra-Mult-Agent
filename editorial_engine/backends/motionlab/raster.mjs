// Original CPU renderer for declarative Three.js geometry. No WebGL emulation.
// Opaque meshes, perspective-correct Lambert lighting, six-plane clipping and z-buffer.
import * as THREE from 'three';
import {FontLoader} from 'three/addons/loaders/FontLoader.js';
import {TextGeometry} from 'three/addons/geometries/TextGeometry.js';
import {readFileSync} from 'node:fs';

const srgbToLinear = v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
const linearToSrgb = v => v <= .0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - .055;
const rgb = hex => [1, 3, 5].map(i => srgbToLinear(parseInt(hex.slice(i, i + 2), 16) / 255));
const byte = v => Math.round(Math.max(0, Math.min(1, linearToSrgb(v))) * 255);
const edge = (a, b, x, y) => (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]);

function clipPolygon(vertices) {
  const planes = [v => v[3]+v[0], v => v[3]-v[0], v => v[3]+v[1],
    v => v[3]-v[1], v => v[3]+v[2], v => v[3]-v[2]];
  let polygon = vertices;
  for (const distance of planes) {
    const result = [];
    for (let i = 0; i < polygon.length; i++) {
      const a = polygon[i], b = polygon[(i + 1) % polygon.length];
      const da = distance(a), db = distance(b), ain = da >= 0, bin = db >= 0;
      if (ain) result.push(a);
      if (ain !== bin) {
        const u = da / (da - db);
        result.push(a.map((v, k) => v + (b[k] - v) * u));
      }
    }
    polygon = result;
    if (!polygon.length) break;
  }
  return polygon;
}

export function createThreeRenderer(scene) {
  const geometry = new Map(), fonts = new Map();
  for (const font of scene.fonts ?? []) if (font.format === 'three-typeface') {
    fonts.set(font.id, new FontLoader().parse(JSON.parse(readFileSync(font.path, 'utf8'))));
  }
  function visit(node) {
    let g;
    switch (node.type) {
      case 'box': g = new THREE.BoxGeometry(...node.size); break;
      case 'sphere': g = new THREE.SphereGeometry(node.radius, node.segments ?? 24, node.rings ?? 16); break;
      case 'plane': g = new THREE.PlaneGeometry(...node.size); break;
      case 'torus': g = new THREE.TorusGeometry(node.radius, node.tube, node.rings ?? 12, node.segments ?? 32); break;
      case 'text3d': g = new TextGeometry(node.text, {font:fonts.get(node.font_id),
        size:node.font_size, depth:node.depth, curveSegments:node.curve_segments ?? 6,
        bevelEnabled:false}); break;
      case 'group': break;
      default: throw new Error(`Unsupported 3D type: ${node.type}`);
    }
    if (g) {
      g.computeBoundingBox();
      geometry.set(node.id, g);
    }
    (node.children ?? []).forEach(visit);
  }
  scene.nodes.forEach(visit);

  function build(state) {
    const world = new THREE.Scene(), meshes = [];
    const add = (node, parent, silent = false) => {
      const object = new THREE.Object3D();
      object.name = node.id;
      object.position.fromArray(node.position ?? [0, 0, 0]);
      object.rotation.set(...(node.rotation ?? [0, 0, 0]));
      object.scale.fromArray(node.scale ?? [1, 1, 1]);
      parent.add(object);
      silent ||= node.sound === false;
      if (geometry.has(node.id)) meshes.push({object, node, geometry:geometry.get(node.id), silent});
      (node.children ?? []).forEach(child => add(child, object, silent));
    };
    state.nodes.forEach(node => add(node, world));
    world.updateMatrixWorld(true);
    for (const {object} of meshes) if (!object.matrixWorld.elements.every(Number.isFinite)) {
      throw new Error(`Non-finite hierarchical transform on ${object.name}`);
    }
    const spec = state.camera;
    if (new THREE.Vector3(...spec.position).distanceTo(new THREE.Vector3(...spec.target)) < 1e-9) {
      throw new Error('Animated camera position coincides with its look target');
    }
    const camera = new THREE.PerspectiveCamera(spec.fov, scene.width / scene.height, spec.near, spec.far);
    camera.position.fromArray(spec.position);
    camera.lookAt(new THREE.Vector3(...spec.target));
    camera.updateMatrixWorld(true);
    camera.updateProjectionMatrix();
    const vp = new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    return {meshes, camera, vp};
  }

  function render(state) {
    const {meshes, camera, vp} = build(state);
    const width = scene.width, height = scene.height;
    const data = new Uint8ClampedArray(width * height * 4);
    const depth = new Float64Array(width * height); depth.fill(Infinity);
    if (scene.background !== null) {
      const b = [1, 3, 5].map(i => parseInt(scene.background.slice(i, i + 2), 16));
      for (let i = 0; i < width * height; i++) data.set([...b, 255], i * 4);
    }
    const lightSpecs = (scene.lights ?? []).map(light => ({...light, color:rgb(light.color),
      vector:light.type === 'directional' ? new THREE.Vector3(...light.direction).normalize() : null}));
    const coverage = {};
    let triangles = 0;
    for (const {object, node, geometry:g} of meshes) {
      coverage[node.id] = 0;
      if (!node.active) continue;
      const positions = g.attributes.position, normals = g.attributes.normal, index = g.index;
      const normalMatrix = new THREE.Matrix3().getNormalMatrix(object.matrixWorld);
      const base = rgb(node.material.color), material = node.material;
      const vertexCount = index ? index.count : positions.count;
      const vertices = [];
      for (let i = 0; i < positions.count; i++) {
        const p = new THREE.Vector3().fromBufferAttribute(positions, i).applyMatrix4(object.matrixWorld);
        const n = new THREE.Vector3().fromBufferAttribute(normals, i).applyMatrix3(normalMatrix).normalize();
        const c = new THREE.Vector4(p.x, p.y, p.z, 1).applyMatrix4(vp);
        vertices.push([c.x, c.y, c.z, c.w, p.x, p.y, p.z, n.x, n.y, n.z]);
      }
      for (let start = 0; start < vertexCount; start += 3) {
        const v = [0, 1, 2].map(k => vertices[index ? index.getX(start + k) : start + k]);
        const clipped = clipPolygon(v);
        for (let k = 1; k < clipped.length - 1; k++) {
          const tri = [clipped[0], clipped[k], clipped[k + 1]];
          if (tri.some(p => p[3] <= 1e-12)) continue;
          const screen = tri.map(p => [(p[0] / p[3] + 1) * width / 2,
            (1 - p[1] / p[3]) * height / 2, p[2] / p[3], 1 / p[3]]);
          const area = edge(screen[0], screen[1], ...screen[2]);
          if (Math.abs(area) < 1e-10 || (area > 0 && material.side !== 'double')) continue;
          triangles++;
          const left = Math.max(0, Math.floor(Math.min(...screen.map(p => p[0]))));
          const right = Math.min(width - 1, Math.ceil(Math.max(...screen.map(p => p[0]))));
          const top = Math.max(0, Math.floor(Math.min(...screen.map(p => p[1]))));
          const bottom = Math.min(height - 1, Math.ceil(Math.max(...screen.map(p => p[1]))));
          for (let y = top; y <= bottom; y++) for (let x = left; x <= right; x++) {
            const b = [edge(screen[1], screen[2], x + .5, y + .5) / area,
              edge(screen[2], screen[0], x + .5, y + .5) / area,
              edge(screen[0], screen[1], x + .5, y + .5) / area];
            if (b.some(w => w < -1e-9)) continue;
            const z = b.reduce((sum, w, j) => sum + w * screen[j][2], 0);
            const offset = y * width + x;
            if (z >= depth[offset] || z < -1 || z > 1) continue;
            const invW = b.reduce((sum, w, j) => sum + w * screen[j][3], 0);
            const attr = component => b.reduce((sum, w, j) => sum + w * tri[j][component] * screen[j][3], 0) / invW;
            const normal = new THREE.Vector3(attr(7), attr(8), attr(9)).normalize();
            if (area > 0) normal.negate();
            const point = new THREE.Vector3(attr(4), attr(5), attr(6));
            const illumination = material.unlit ? [1, 1, 1] : [0, 0, 0];
            if (!material.unlit) for (const light of lightSpecs) {
              let amount = light.intensity;
              if (light.type !== 'ambient') {
                const direction = light.type === 'directional' ? light.vector : new THREE.Vector3(...light.position).sub(point).normalize();
                amount *= Math.max(0, normal.dot(direction));
              }
              for (let channel = 0; channel < 3; channel++) illumination[channel] += light.color[channel] * amount;
            }
            for (let channel = 0; channel < 3; channel++) data[offset * 4 + channel] = byte(base[channel] * illumination[channel]);
            data[offset * 4 + 3] = 255;
            depth[offset] = z;
            coverage[node.id]++;
          }
        }
      }
    }
    return {data, triangles, backend:'three-cpu-lambert-zbuffer/1'};
  }

  function telemetry(state) {
    const {meshes, camera, vp} = build(state), objects = {};
    for (const {object, node, geometry:g, silent} of meshes) {
      const box = g.boundingBox;
      const points = [];
      for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
        const world = new THREE.Vector3(x, y, z).applyMatrix4(object.matrixWorld);
        const projected = new THREE.Vector4(world.x, world.y, world.z, 1).applyMatrix4(vp);
        if (projected.w > 0) points.push([projected.x / projected.w, projected.y / projected.w]);
      }
      const minX = points.length ? Math.min(...points.map(p => p[0])) : 0;
      const maxX = points.length ? Math.max(...points.map(p => p[0])) : 0;
      const minY = points.length ? Math.min(...points.map(p => p[1])) : 0;
      const maxY = points.length ? Math.max(...points.map(p => p[1])) : 0;
      const centerX = (minX + maxX) / 2, centerY = (minY + maxY) / 2;
      const rotation = new THREE.Quaternion(); object.getWorldQuaternion(rotation);
      const visible = !silent && node.active && points.length && maxX > -1 && minX < 1 && maxY > -1 && minY < 1;
      const area = Math.max(0, Math.min(1, maxX) - Math.max(-1, minX)) * Math.max(0, Math.min(1, maxY) - Math.max(-1, minY)) / 4;
      objects[node.id] = {position:[centerX * 4, centerY * 2, 0], quaternion:rotation.toArray(),
        visibility:visible ? 1 : 0, opacity:node.active ? 1 : 0, pan:Math.max(-.85, Math.min(.85, centerX)),
        size:[Math.max(0, maxX - minX) / 2, Math.max(0, maxY - minY) / 2], renderKind:node.type,
        transition:false, importance:Math.max(.05, Math.min(1, Math.sqrt(area) * 3))};
    }
    return {camera:{position:camera.position.toArray(), quaternion:camera.quaternion.toArray()}, objects};
  }
  return {render, telemetry, dispose:() => {for (const g of geometry.values()) g.dispose();}};
}
