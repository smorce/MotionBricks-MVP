// Polyfork merge.mjs. Its API is in API.md beside this file: you do not need to read this code.
// The commented source is https://polyfork.dev/cdn/merge.mjs
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const matKey = (m) => !m ? 'none' : [
  m.type, m.vertexColors, m.flatShading, m.transparent, m.opacity, m.side, m.depthWrite,
  m.metalness, m.roughness, m.emissiveIntensity,
  m.color?.getHexString?.() ?? '', m.emissive?.getHexString?.() ?? '',
].join('|');

const MAPS = ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'alphaMap', 'emissiveMap', 'bumpMap', 'clearcoatMap', 'clearcoatNormalMap', 'sheenColorMap', 'sheenRoughnessMap', 'transmissionMap', 'thicknessMap', 'specularIntensityMap', 'specularColorMap', 'anisotropyMap'];
const textured = (m) => !!m && (m.isMeshPhysicalMaterial || MAPS.some((k) => m[k]));
const hex = (c) => c?.getHexString?.() ?? '';
const q4 = (x) => (x == null ? '' : Math.round(x * 4) / 4);
const q2 = (x) => (x == null ? '' : Math.round(x * 2) / 2);
const glanceOnly = (m) => m.userData?.glance != null && !m.userData?.fire   // the key is the default (the function's source) plus the glance, nothing else
  && m.customProgramCacheKey?.() === `${m.onBeforeCompile}|pf-glance-${Number(m.userData.glance).toFixed(3)}`;
const texKey = (m) => (m.onBeforeCompile !== THREE.Material.prototype.onBeforeCompile && !glanceOnly(m)) || m.userData?.fire
  ? 'own|' + m.uuid
  : ['tex', glanceOnly(m) ? m.customProgramCacheKey() : '', m.type, m.transparent, m.opacity, m.side, m.shadowSide, m.depthWrite, m.alphaTest, m.alphaToCoverage, m.flatShading,
     q2(m.metalness), q4(m.roughness), hex(m.emissive), q4(m.emissiveIntensity), q4(m.envMapIntensity), Math.sign(m.normalScale?.y ?? 0),
     q4(m.sheen), q4(m.sheenRoughness), q4(m.clearcoat), q4(m.clearcoatRoughness), q4(m.anisotropy), m.anisotropyRotation,
     m.transmission, m.thickness, m.ior, hex(m.attenuationColor), m.attenuationDistance, m.specularIntensity, hex(m.specularColor),
     m.polygonOffset, m.polygonOffsetFactor, m.polygonOffsetUnits, !!m.userData?.glow, !!m.userData?.emits,
     ...MAPS.map((k) => m[k]?.uuid ?? '')].join('|');

export function mergeAssets(list, { keepDynamic = true } = {}) {
  const buckets = {};        // material signature -> { material, geoms }
  const dynamic = [];

  const lift = node => {
    const out = node.clone(true);
    node.updateWorldMatrix(true, false);
    node.matrixWorld.decompose(out.position, out.quaternion, out.scale);
    dynamic.push(out);
  };

  const mergeTextured = (node) => {
    const m = node.material, key = texKey(m), own = key.startsWith('own|');
    let g = node.geometry.index ? node.geometry.toNonIndexed() : node.geometry.clone();
    g.applyMatrix4(node.matrixWorld);
    for (const name of Object.keys(g.attributes)) if (!['position', 'normal', 'uv', 'color'].includes(name)) g.deleteAttribute(name);
    const n = g.attributes.position.count;
    if (!g.attributes.normal) g.computeVertexNormals();
    if (!g.attributes.uv) g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(n * 2), 2));
    const col = m.vertexColors ? g.attributes.color : null, tint = own ? new THREE.Color(1, 1, 1) : (m.color ?? new THREE.Color(1, 1, 1));
    const arr = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const r = col ? col.getX(i) : 1, gg = col ? col.getY(i) : 1, b = col ? col.getZ(i) : 1;
      arr[i * 3] = r * tint.r; arr[i * 3 + 1] = gg * tint.g; arr[i * 3 + 2] = b * tint.b;
    }
    g.setAttribute('color', new THREE.BufferAttribute(arr, 3));
    for (const name of ['position', 'normal', 'uv', 'color']) g.attributes[name].gpuType = THREE.FloatType;
    const bucket = (buckets[key] ??= { material: own ? m : null, geoms: [], best: null, bestN: -1, sheen: [] });
    if (!own && n > bucket.bestN) { bucket.best = m; bucket.bestN = n; }
    if (!own && m.sheenColor && m.sheen) bucket.sheen.push(m.sheenColor);
    bucket.geoms.push(g);
  };
  const finishTextured = () => {
    for (const b of Object.values(buckets)) {
      if (b.material || !b.best) continue;
      const material = b.best.clone();
      material.color.set(1, 1, 1); material.vertexColors = true; material.name = 'merged:' + (b.best.name || 'zone');
      if (glanceOnly(b.best)) { material.onBeforeCompile = b.best.onBeforeCompile; material.customProgramCacheKey = b.best.customProgramCacheKey; }   // clone() drops both
      if (b.sheen.length) { const c = new THREE.Color(0, 0, 0); for (const x of b.sheen) c.add(x); material.sheenColor = c.multiplyScalar(1 / b.sheen.length); }
      b.material = material;
    }
  };

  for (const entry of list) {
    const object = entry?.isObject3D ? entry : entry?.object;
    if (!object) continue;
    const exclude = new Set(keepDynamic ? Object.keys(entry?.rig ?? {}) : []);
    object.updateWorldMatrix(true, true);
    (function walk(node) {
      if (exclude.has(node.name)) { lift(node); return; }
      if (node.isSkinnedMesh) { if (keepDynamic) lift(node); return; }
      if (node.isMesh && !Array.isArray(node.material) && textured(node.material) && node.geometry?.attributes?.position) {
        mergeTextured(node);
      } else if (node.isMesh && node.geometry?.attributes?.position) {
        let g = node.geometry.index ? node.geometry.toNonIndexed() : node.geometry.clone();
        g.applyMatrix4(node.matrixWorld);
        for (const name of Object.keys(g.attributes)) {
          if (name === 'position' || name === 'normal' || name === 'color') continue;
          if (/^(uv\d*|tangent|skinIndex|skinWeight)$/.test(name)) g.deleteAttribute(name);
        }
        if (!g.attributes.normal) g.computeVertexNormals(); // normal-less GLBs (previews) merge too
        const col = g.attributes.color;
        if (!col) {
          const n = g.attributes.position.count;
          const c = new THREE.Color(node.material?.color ?? 0xffffff);
          const arr = new Float32Array(n * 3);
          for (let i = 0; i < n; i++) { arr[i * 3] = c.r; arr[i * 3 + 1] = c.g; arr[i * 3 + 2] = c.b; }
          g.setAttribute('color', new THREE.BufferAttribute(arr, 3));
        } else if (col.itemSize === 4) {
          const n = col.count, arr = new Float32Array(n * 3);
          for (let i = 0; i < n; i++) { arr[i * 3] = col.getX(i); arr[i * 3 + 1] = col.getY(i); arr[i * 3 + 2] = col.getZ(i); }
          g.setAttribute('color', new THREE.BufferAttribute(arr, 3));
        }
        for (const name of ['position', 'normal', 'color']) {
          const a = g.attributes[name];
          if (a && a.gpuType !== THREE.FloatType) a.gpuType = THREE.FloatType;
        }
        const key = matKey(node.material);
        (buckets[key] ??= { material: node.material, geoms: [] }).geoms.push(g);
      }
      for (const c of node.children) walk(c);
    })(object);
  }

  finishTextured();
  const parts = [];
  for (const { material, geoms } of Object.values(buckets)) {
    if (geoms.length && !material?.map) {
      const core = new Set(['position', 'normal', 'color', 'uv']);
      const extra = Object.keys(geoms[0].attributes).filter((k) => !core.has(k)
        && geoms.every((g) => g.attributes[k] && g.attributes[k].itemSize === geoms[0].attributes[k].itemSize));
      for (const g of geoms) {
        for (const k of Object.keys(g.attributes)) {
          if (core.has(k)) continue;
          if (!extra.includes(k)) { g.deleteAttribute(k); continue; }
          const a = g.attributes[k];
          if (a.array instanceof Float32Array && a.gpuType !== THREE.FloatType) a.gpuType = THREE.FloatType;
        }
      }
    }
    const mg = geoms.length ? mergeGeometries(geoms, false) : null;
    if (!mg && geoms.length) {
      const sig = g => Object.keys(g.attributes).sort().map(k => {
        const a = g.attributes[k];
        return `${k}[${a.itemSize}] ${a.array.constructor.name} gpu=${a.gpuType ?? 'default'}`
          + (a.normalized ? ' normalized' : '');
      }).join(', ');
      const rows = geoms.map((g, i) => `  #${i} ${g.attributes.position.count} verts: ${sig(g)}`);
      console.warn('mergeAssets: a material bucket would not merge, so it stays separate.\n'
        + rows.join('\n'));
    }
    if (mg) {
      const mesh = new THREE.Mesh(mg, material);
      mesh.castShadow = !material?.userData?.glow; mesh.receiveShadow = true;
      parts.push(mesh);
    }
    geoms.forEach(g => g.dispose?.());
  }
  let merged = null;
  if (parts.length === 1) merged = parts[0];
  else if (parts.length > 1) {
    merged = new THREE.Group();
    merged.name = 'merged';
    parts.forEach(p => merged.add(p));
  }
  return { merged, dynamic };
}
