// Polyfork stage.mjs. Its API is in API.md beside this file: you do not need to read this code.
// The commented source is https://polyfork.dev/cdn/stage.mjs
import * as THREE from 'three';

const TIMES = [
  { at: 0.00, name: 'day',    sky: 0x7fbdee, horizon: 0xdff0fa, hemiSky: 0xffffff, hemiGround: 0xa89f92, hemi: 0.92, key: 0xffedd2, keyI: 2.85, rim: 0xdfe8ff, rimI: 0.85, elev: 43, fog: 1.00 },
  { at: 0.55, name: 'golden', sky: 0x86b4e0, horizon: 0xffe0b0, hemiSky: 0xfff0dc, hemiGround: 0xb9a68c, hemi: 1.05, key: 0xffd9a0, keyI: 2.30, rim: 0xcfd8ff, rimI: 0.85, elev: 26, fog: 0.95 },
  { at: 0.82, name: 'dusk',   sky: 0x3d4f96, horizon: 0xff9d62, hemiSky: 0xb4bce8, hemiGround: 0x6d5f78, hemi: 0.85, key: 0xff9458, keyI: 1.70, rim: 0x8f9cff, rimI: 0.75, elev: 9,  fog: 0.85 },
  { at: 1.00, name: 'night',  sky: 0x070b1c, horizon: 0x1b2748, hemiSky: 0x53659e, hemiGround: 0x1b2032, hemi: 0.70, key: 0xaec6ff, keyI: 0.75, rim: 0x5a6cc0, rimI: 0.45, elev: 40, fog: 0.75 },
];
const NAMED = Object.fromEntries(TIMES.map((t) => [t.name, t.at]));
const LOOKS = {
  dawn:     { sky: 0x8fa9d8, horizon: 0xffc9b4, hemiSky: 0xdfe6ff, hemiGround: 0x8d879c, hemi: 0.82, key: 0xffcdb8, keyI: 1.95, rim: 0xa4b4ff, rimI: 0.80, elev: 11, fog: 0.80, night: 0.35 },
  noon:     { sky: 0x66aef2, horizon: 0xe4f3ff, hemiSky: 0xffffff, hemiGround: 0xb0a898, hemi: 0.95, key: 0xffffff, keyI: 3.05, rim: 0xe6eeff, rimI: 0.75, elev: 70, fog: 1.00, night: 0 },
  overcast: { sky: 0xb4bfca, horizon: 0xd8dde2, hemiSky: 0xffffff, hemiGround: 0xaeb0b2, hemi: 1.50, key: 0xeef2f6, keyI: 0.85, rim: 0xdde4ee, rimI: 0.45, elev: 58, fog: 0.72, night: 0 },
  moonlit:  { sky: 0x0b1230, horizon: 0x2a3a66, hemiSky: 0x6f86c8, hemiGround: 0x20263a, hemi: 0.95, key: 0xc4d6ff, keyI: 1.25, rim: 0x6a7ed0, rimI: 0.55, elev: 48, fog: 0.85, night: 1 },
  space:    { sky: 0x000000, horizon: 0x000000, hemiSky: 0x1a1a22, hemiGround: 0x8a7a6a, hemi: 0.55, key: 0xffffff, keyI: 3.4, rim: 0x9fb4ff, rimI: 0.35, elev: 34, fog: 0, night: 1, stars: true },
};
export const LIGHTING = ['noon', 'day', 'golden', 'dusk', 'night', 'dawn', 'overcast', 'moonlit', 'space'];

export function softenTerrain(root, { passes = 2, keep = 0.45, crease = 0.8, normals = true, vertexColors = true } = {}) {
  root.traverse((o) => {
    const g = o.isMesh && o.geometry;
    if (!g || g.index || !g.attributes.color || !g.attributes.position || o.material?.transparent) return;
    const P = g.attributes.position.array, C = g.attributes.color.array, F = P.length / 9;
    if (F < 8 || g.attributes.color.itemSize !== 3) return;
    const key = (i) => Math.round(P[i] * 500) + ',' + Math.round(P[i + 1] * 500) + ',' + Math.round(P[i + 2] * 500);
    const edges = new Map(), nb = Array.from({ length: F }, () => []), N = new Float32Array(F * 3);
    const at = new Map(), AREA = new Float32Array(F);     // position -> faces meeting there, for the vertex passes below
    for (let f = 0; f < F; f++) {
      const i = f * 9, k = [key(i), key(i + 3), key(i + 6)];
      const ux = P[i + 3] - P[i], uy = P[i + 4] - P[i + 1], uz = P[i + 5] - P[i + 2], vx = P[i + 6] - P[i], vy = P[i + 7] - P[i + 1], vz = P[i + 8] - P[i + 2];
      let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx; const l = Math.hypot(nx, ny, nz) || 1;
      N[f * 3] = nx / l; N[f * 3 + 1] = ny / l; N[f * 3 + 2] = nz / l; AREA[f] = l;
      for (const kk of k) { const list = at.get(kk); if (list) list.push(f); else at.set(kk, [f]); }
      for (let e = 0; e < 3; e++) {
        const a = k[e], b = k[(e + 1) % 3], id = a < b ? a + '|' + b : b + '|' + a, other = edges.get(id);
        if (other === undefined) edges.set(id, f); else { nb[f].push(other); nb[other].push(f); }
      }
    }
    let smoothNormals = normals;
    if (normals === 'auto') {
      let up = 0, green = 0;
      for (let f = 0; f < F; f++) if (N[f * 3 + 1] > 0.5) { up++; const r = C[f * 9], gg = C[f * 9 + 1], b = C[f * 9 + 2]; if (gg > r * 1.05 && gg > b * 1.2) green++; }
      smoothNormals = up > 0 && green / up >= 0.3;
      o.userData.groundLook = smoothNormals ? 'smooth' : 'faceted';
    }
    let cur = new Float32Array(F * 3);
    for (let f = 0; f < F; f++) { cur[f * 3] = C[f * 9]; cur[f * 3 + 1] = C[f * 9 + 1]; cur[f * 3 + 2] = C[f * 9 + 2]; }
    for (let pass = 0; pass < passes; pass++) {
      const next = new Float32Array(cur);
      for (let f = 0; f < F; f++) {
        let r = 0, gg = 0, b = 0, n = 0;
        for (const h of nb[f]) {
          if (N[f * 3] * N[h * 3] + N[f * 3 + 1] * N[h * 3 + 1] + N[f * 3 + 2] * N[h * 3 + 2] < crease) continue;
          r += cur[h * 3]; gg += cur[h * 3 + 1]; b += cur[h * 3 + 2]; n++;
        }
        if (!n) continue;
        next[f * 3] = keep * cur[f * 3] + (1 - keep) * r / n;
        next[f * 3 + 1] = keep * cur[f * 3 + 1] + (1 - keep) * gg / n;
        next[f * 3 + 2] = keep * cur[f * 3 + 2] + (1 - keep) * b / n;
      }
      cur = next;
    }
    for (let f = 0; f < F; f++) for (let v = 0; v < 3; v++) { C[f * 9 + v * 3] = cur[f * 3]; C[f * 9 + v * 3 + 1] = cur[f * 3 + 1]; C[f * 9 + v * 3 + 2] = cur[f * 3 + 2]; }
    if (smoothNormals || vertexColors) {
      const Nn = smoothNormals ? new Float32Array(P.length) : null;
      for (let f = 0; f < F; f++) for (let v = 0; v < 3; v++) {
        const i = f * 9 + v * 3, faces = at.get(key(i));
        let nx = 0, ny = 0, nz = 0, r = 0, gg = 0, b = 0, w = 0;
        for (const h of faces) {
          if (N[f * 3] * N[h * 3] + N[f * 3 + 1] * N[h * 3 + 1] + N[f * 3 + 2] * N[h * 3 + 2] < crease) continue;
          const a = AREA[h]; nx += N[h * 3] * a; ny += N[h * 3 + 1] * a; nz += N[h * 3 + 2] * a;
          r += cur[h * 3] * a; gg += cur[h * 3 + 1] * a; b += cur[h * 3 + 2] * a; w += a;
        }
        if (Nn) { const l = Math.hypot(nx, ny, nz) || 1; Nn[i] = nx / l; Nn[i + 1] = ny / l; Nn[i + 2] = nz / l; }
        if (vertexColors && w) { C[i] = r / w; C[i + 1] = gg / w; C[i + 2] = b / w; }
      }
      if (Nn) {
        g.setAttribute('normal', new THREE.BufferAttribute(Nn, 3));
        const mats = (Array.isArray(o.material) ? o.material : [o.material]).map((m) => { const c = m.clone(); c.flatShading = false; c.needsUpdate = true; return c; });
        o.material = Array.isArray(o.material) ? mats : mats[0];
      }
    }
    g.attributes.color.needsUpdate = true;
  });
  return root;
}

export function stage(renderer, scene, {
  time = 'day', toneMapping = 'none', shadows = true, shadowMap = 2048, shadowSpan = 70,
  sky = true, fog = true, far = 320, azimuth = 38,
} = {}) {
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const aces = toneMapping === 'aces';
  renderer.toneMapping = aces ? THREE.ACESFilmicToneMapping : THREE.NoToneMapping;
  renderer.toneMappingExposure = aces ? 1.5 : 1;
  const lift = aces ? 1.1 : 1;
  renderer.shadowMap.enabled = !!shadows;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const hemi = new THREE.HemisphereLight(0xffffff, 0xb8b0a4, 1.15);
  const key = new THREE.DirectionalLight(0xfff2e0, 2.4);
  const rim = new THREE.DirectionalLight(0xdfe8ff, 0.9);
  key.castShadow = !!shadows;
  key.shadow.mapSize.set(shadowMap, shadowMap);
  key.shadow.bias = 0;
  const cam = key.shadow.camera;
  cam.left = cam.bottom = -shadowSpan / 2; cam.right = cam.top = shadowSpan / 2;
  cam.near = 1; cam.far = 400; cam.updateProjectionMatrix();
  const texel = shadowSpan / shadowMap;
  key.shadow.normalBias = texel * 2;
  scene.add(hemi, key, key.target, rim, rim.target);

  let dome = null;
  if (sky) {
    const g = new THREE.SphereGeometry(60, 32, 16);
    g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(g.attributes.position.count * 3), 3));
    dome = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide, fog: false, depthWrite: false, depthTest: false }));
    dome.name = 'sky'; dome.renderOrder = -1000; dome.frustumCulled = false;
    const n = 1400, sp = new Float32Array(n * 3), sc = new Float32Array(n * 3); let seed = 3;
    const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
    for (let i = 0; i < n; i++) {
      const u = rnd(), v = rnd(), th = u * Math.PI * 2, el = Math.asin(0.03 + v * 0.97), r = 58;
      sp[i * 3] = r * Math.cos(el) * Math.cos(th); sp[i * 3 + 1] = r * Math.sin(el); sp[i * 3 + 2] = r * Math.cos(el) * Math.sin(th);
      const b = 0.35 + Math.pow(rnd(), 3) * 0.65, tint = rnd(); sc[i * 3] = b * (tint < 0.15 ? 0.85 : 1); sc[i * 3 + 1] = b * (tint > 0.85 ? 0.9 : 1); sc[i * 3 + 2] = b * (tint < 0.15 ? 1 : tint > 0.85 ? 0.75 : 1);
    }
    const sg = new THREE.BufferGeometry(); sg.setAttribute('position', new THREE.BufferAttribute(sp, 3)); sg.setAttribute('color', new THREE.BufferAttribute(sc, 3));
    const stars = new THREE.Points(sg, new THREE.PointsMaterial({ size: 1.6, sizeAttenuation: false, vertexColors: true, fog: false, depthWrite: false, depthTest: false, transparent: true }));
    stars.name = 'stars'; stars.renderOrder = -999; stars.frustumCulled = false; stars.visible = false; dome.add(stars);
    dome.onBeforeRender = (r, sc, camera) => {
      dome.position.copy(camera.position); dome.updateMatrixWorld();
      if (scene.fog && fogBase) { const d = camera.position.distanceTo(focus); scene.fog.near = d + fogBase.near; scene.fog.far = d + fogBase.far; }
    };
    scene.add(dome);
  }
  if (fog) scene.fog = new THREE.Fog(0xdff0fa, far * 0.35, far);

  const focus = new THREE.Vector3(); let fogBase = null;
  let followed = null, t = 0;
  const A = new THREE.Color(), B = new THREE.Color();
  const mixHex = (a, b, k) => A.setHex(a).lerp(B.setHex(b), k).clone();

  function setTime(v) {
    const preset = typeof v === 'string' ? LOOKS[v] : null;
    if (typeof v === 'string' && !preset && !(v in NAMED)) console.warn(`stage.mjs: no lighting called "${v}". The names are: ${LIGHTING.join(', ')}, or a number 0..1 from day to night.`);
    t = typeof v === 'string' ? (NAMED[v] ?? 0) : Math.min(1, Math.max(0, v));
    let i = 0; while (i < TIMES.length - 2 && t > TIMES[i + 1].at) i++;
    const a = preset || TIMES[i], b = preset || TIMES[i + 1], k = preset ? 0 : (t - a.at) / (b.at - a.at || 1), s = Math.min(1, Math.max(0, k));
    const num = (p) => a[p] + (b[p] - a[p]) * s;
    hemi.color.copy(mixHex(a.hemiSky, b.hemiSky, s)); hemi.groundColor.copy(mixHex(a.hemiGround, b.hemiGround, s));
    hemi.intensity = num('hemi') * lift;
    key.color.copy(mixHex(a.key, b.key, s)); key.intensity = num('keyI') * lift;
    rim.color.copy(mixHex(a.rim, b.rim, s)); rim.intensity = num('rimI') * lift;
    look.elevation = num('elev');
    const top = mixHex(a.sky, b.sky, s), hor = mixHex(a.horizon, b.horizon, s);
    if (dome) {
      const pos = dome.geometry.attributes.position, col = dome.geometry.attributes.color, R = 60, c = new THREE.Color();
      for (let n = 0; n < pos.count; n++) {
        const h = Math.max(0, pos.getY(n) / R);                 // 0 at the horizon, 1 overhead
        c.copy(hor).lerp(top, Math.pow(h, 0.55));
        col.setXYZ(n, c.r, c.g, c.b);
      }
      col.needsUpdate = true;
    } else scene.background = hor;
    if (scene.fog) { scene.fog.color.copy(hor); fogBase = { near: far * 0.4 * num('fog'), far: far * 1.1 * num('fog') }; scene.fog.near = fogBase.near; scene.fog.far = fogBase.far; }
    const n = Math.min(1, Math.max(0, (t - 0.6) / 0.2));
    look.night = preset ? preset.night : n * n * (3 - 2 * n);
    if (dome) { const st = dome.getObjectByName('stars'); if (st) st.visible = !!preset?.stars; }
    if (scene.fog && preset && preset.fog === 0) { scene.fog.near = 1e6; scene.fog.far = 1e7; fogBase = null; }   // no air, no haze
    look.lighting = typeof v === 'string' ? v : null;
    place();
    return look;
  }
  const lamps = () => {
    for (const o of scene.children) {
      const f = o.userData?.night;
      if (typeof f === 'function' && o.userData.nightSet !== look.night) { f(look.night); o.userData.nightSet = look.night; }
    }
  };

  function place() {
    const el = THREE.MathUtils.degToRad(look.elevation ?? 52), az = THREE.MathUtils.degToRad(azimuth);
    const fx = Math.round(focus.x / texel) * texel, fz = Math.round(focus.z / texel) * texel;
    key.target.position.set(fx, focus.y, fz);
    key.position.set(fx + Math.cos(el) * Math.sin(az) * 160, focus.y + Math.sin(el) * 160, fz + Math.cos(el) * Math.cos(az) * 160);
    rim.target.position.copy(key.target.position);
    rim.position.set(fx - Math.sin(az) * 120, focus.y + 70, fz - Math.cos(az) * 120);
  }

  const look = {
    hemi, key, rim, sky: dome, elevation: 52, night: 0,
    get time() { return t; },
    setTime,
    follow(object) { followed = object; return look; },
    update() { if (followed) { followed.getWorldPosition(focus); } place(); lamps(); },
    shadows(root) {
      root.traverse((o) => {
        if (!o.isMesh) return;
        o.castShadow = !o.material?.userData?.glow; o.receiveShadow = true;     // kit.mjs's lit faces (windows, lenses) cast nothing
        if (o.geometry && !o.geometry.attributes.normal) o.geometry.computeVertexNormals();
        for (const m of (Array.isArray(o.material) ? o.material : [o.material])) if (m && m.shadowSide == null) m.shadowSide = m.side;
      });
      return root;
    },
    soften(root, opts = {}) { return softenTerrain(root, opts); },
    ground(placeOrBounds, { color = null, y = null, size = null, hills = true } = {}) {
      const b = placeOrBounds?.bounds ?? placeOrBounds;
      const hex = color ?? placeOrBounds?.groundColor ?? '#a9a59c';
      const c = b.getCenter(new THREE.Vector3()), s = b.getSize(new THREE.Vector3());
      const S = size ?? Math.max(far * 2.2, Math.max(s.x, s.z) * 4), N = 160;          // 160: patches a few metres across near the place, not nine
      const g = new THREE.PlaneGeometry(S, S, N, N).rotateX(-Math.PI / 2);
      const pos = g.attributes.position, col = new Float32Array(pos.count * 3), base = new THREE.Color(hex), k = new THREE.Color();
      const n2 = (x, z) => Math.sin(x * 0.071 + 1.3) * Math.cos(z * 0.053 - 0.7) + 0.5 * Math.sin(x * 0.19 - z * 0.23);
      const flat = Math.max(s.x, s.z) / 2 + 80;
      for (let i = 0; i < pos.count; i++) {
        const x = pos.getX(i), z = pos.getZ(i), d = Math.hypot(x, z);
        const ramp = Math.min(1, Math.max(0, (d - flat) / 140)), rise = ramp * ramp * (3 - 2 * ramp);
        const hill = hills ? rise * (9 + 8 * n2(x * 0.55 + 40, z * 0.55 - 25)) : 0;
        pos.setY(i, hill);
        const m = 0.6 * n2(x, z) + 0.4 * n2(x * 2.7 + 13, z * 2.3 - 7), v = (1 + 0.14 * m) * (1 - 0.16 * rise);
        k.copy(base).multiplyScalar(v); k.r *= 1 + 0.06 * m; k.b *= 1 - 0.10 * m;
        col[i * 3] = k.r; col[i * 3 + 1] = k.g; col[i * 3 + 2] = k.b;
      }
      g.computeVertexNormals();
      g.setAttribute('color', new THREE.BufferAttribute(col, 3));
      const cv = document.createElement('canvas'); cv.width = cv.height = 256;
      const c2 = cv.getContext('2d'); c2.fillStyle = '#ececec'; c2.fillRect(0, 0, 256, 256);
      let seed = 7; const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
      for (let n = 0; n < 260; n++) {
        const x = rnd() * 256, y = rnd() * 256, r = 7 + rnd() * 26, light = rnd() < 0.5, a = 0.05 + rnd() * 0.09;
        for (const ox of [-256, 0, 256]) for (const oy of [-256, 0, 256]) {
          const gr = c2.createRadialGradient(x + ox, y + oy, 0, x + ox, y + oy, r);
          gr.addColorStop(0, light ? `rgba(255,255,255,${a})` : `rgba(90,96,70,${a})`); gr.addColorStop(1, 'rgba(0,0,0,0)');
          c2.fillStyle = gr; c2.fillRect(x + ox - r, y + oy - r, r * 2, r * 2);
        }
      }
      const blotch = new THREE.CanvasTexture(cv); blotch.wrapS = blotch.wrapT = THREE.RepeatWrapping; blotch.repeat.set(S / 26, S / 26);
      blotch.colorSpace = THREE.SRGBColorSpace; blotch.anisotropy = 4;
      const mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, map: blotch, flatShading: false, roughness: 1, metalness: 0 }));   // ground is smooth: see softenTerrain
      mesh.position.set(c.x, y ?? placeOrBounds?.groundY ?? -0.05, c.z);
      mesh.receiveShadow = true; mesh.name = 'ground';
      scene.add(mesh);
      return mesh;
    },
  };
  setTime(time);
  return look;
}

export default stage;
