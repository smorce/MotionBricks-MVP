// Polyfork city.mjs. Its API is in API.md beside this file: you do not need to read this code.
// The commented source is https://polyfork.dev/cdn/city.mjs
import * as THREE from 'three';

const DEG = Math.PI / 180;
const ROAD = /road|asphalt|tarmac|(^|-)lane|street-tile|street$/, RAIL = /tram|train|rail|track/;
const TREE = /(^|-)(tree|blossom|pine|palm|birch|oak|maple|cypress|willow|evergreen)s?(-|$)/;     // whole words: "tree" is inside "street"
const VEHICLE = /(^|-)(car|van|truck|bus|taxi|cab|suv|pickup|scooter|moped|motorbike|motorcycle|sedan|hatchback|minivan|wagon|jeep|ambulance|lorry|coupe|limo)(-|$)|^veh-/;

const rng = (seed) => { let a = (seed >>> 0) || 1; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; };
const rot = (x, z, a) => [x * Math.cos(a) + z * Math.sin(a), -x * Math.sin(a) + z * Math.cos(a)];
const mode = (list) => { const n = new Map(); let best = null, top = 0; for (const v of list) { const c = (n.get(v) || 0) + 1; n.set(v, c); if (c > top) { top = c; best = v; } } return best; };

export function cityLayout({ rows, make, isHuman = () => false, hasWheels = () => false, colourways = () => ({ name: 'colorway', list: [] }), city = {} }) {
  const { seed = 1, blocks = [3, 3], parks = 0.15 } = city;
  const rnd = rng(seed), pick = (a) => a[Math.floor(rnd() * a.length)];
  const pickLot = (a) => { const w = a.map((l) => (l.members.length ? 3 : 1)), sum = w.reduce((x, y) => x + y, 0); let t = rnd() * sum; for (let i = 0; i < a.length; i++) { t -= w[i]; if (t <= 0) return a[i]; } return a[a.length - 1]; };

  const first = new Map(), count = new Map();
  rows.forEach((r, i) => { r.__i = i; if (!first.has(r.part)) first.set(r.part, r); count.set(r.part, (count.get(r.part) || 0) + 1); });
  const nth = {}; for (const r of rows) r.__ord = nth[r.part] = (nth[r.part] ?? -1) + 1;
  const dim = new Map();
  for (const [k, r] of first) {
    const o = make(k, r, r.__ord), b = new THREE.Box3().setFromObject(o), s = b.getSize(new THREE.Vector3()), c = b.getCenter(new THREE.Vector3());
    dim.set(k, { x: s.x, y: s.y, z: s.z, cx: c.x, cz: c.z, human: isHuman(o) });
  }
  const kind = (k) => {
    const d = dim.get(k);
    if (d.human) return 'person';
    if (d.y < 0.4 && Math.max(d.x, d.z) >= 1.5) return RAIL.test(k) ? 'skip' : (ROAD.test(k) ? 'road' : 'walk');
    if (RAIL.test(k)) return 'skip';
    if (hasWheels(k) || (VEHICLE.test(k) && !/shelter|stop|station|stand|rack|sign|lane|wash|park|depot|garage/.test(k))) return 'vehicle';
    if (TREE.test(k)) return 'tree';
    if (d.y >= 3 && Math.min(d.x, d.z) >= 2.5) return 'building';
    return 'thing';
  };
  const kinds = new Map([...first.keys()].map((k) => [k, kind(k)]));
  const of = (what) => rows.filter((r) => kinds.get(r.part) === what);
  const roads = of('road');
  if (!roads.length) throw new Error('kit.mjs city: this kit has no road tiles to lay streets with (looked for flat parts named road, asphalt, lane or street). city is for street kits.');
  const roadKey = mode(roads.map((r) => r.part)), T = Math.round(Math.max(dim.get(roadKey).x, dim.get(roadKey).z) * 2) / 2;
  const thin = (r) => Math.min(dim.get(r.part).x, dim.get(r.part).z) < 1;
  const walks = of('walk').filter((r) => !thin(r)), walkKey = mode(walks.map((r) => r.part)) || roadKey;
  const squareish = (k) => { const d = dim.get(k); return Math.min(d.x, d.z) >= 0.45 * T && Math.min(d.x, d.z) / Math.max(d.x, d.z) > 0.7 && !/path|walk-|deck|plank|board|bridge|track|drive|(^|-)run(-|$)/.test(k); };
  const yardKey = mode(walks.filter((r) => r.part !== walkKey && squareish(r.part)).map((r) => r.part)) || null;
  const kerbKey = mode(of('walk').filter(thin).map((r) => r.part));
  const S = city.street ?? (T < 6 ? 2 : 1);

  const at = new Set(roads.map((r) => `${Math.round(r.x / T)},${Math.round(r.z / T)}`));
  const has = (r, dx, dz) => at.has(`${Math.round(r.x / T) + dx},${Math.round(r.z / T) + dz}`);
  const alongX = roads.filter((r) => (has(r, 1, 0) || has(r, -1, 0)) && !has(r, 0, 1) && !has(r, 0, -1)).map((r) => (((r.ry || 0) % 180) + 180) % 180);
  const alongZ = roads.filter((r) => (has(r, 0, 1) || has(r, 0, -1)) && !has(r, 1, 0) && !has(r, -1, 0)).map((r) => (((r.ry || 0) % 180) + 180) % 180);
  const ryZ = mode(alongZ) ?? ((mode(alongX) ?? 90) + 90) % 180, ryX = mode(alongX) ?? (ryZ + 90) % 180;

  const UP = 1.5, aloft = (r) => (r.y || 0) >= UP;
  const buildings = of('building').filter((r) => !aloft(r)), things = rows.filter((r) => kinds.get(r.part) === 'thing');
  const frontOfRow = new Map();
  for (const b of buildings) {
    const d = dim.get(b.part); let best = 0, top = -1;
    for (const phi of [0, 90, 180, -90]) {
      const half = (Math.abs(phi) === 90 ? d.x : d.z) / 2, wide = (Math.abs(phi) === 90 ? d.z : d.x) / 2, turn = -((b.ry || 0) + phi) * DEG;
      let score = 0;
      for (const r of roads) { const [l, f] = rot(r.x - b.x, r.z - b.z, turn); if (f > 0 && f < half + 2.6 * T && Math.abs(l) <= T / 2 + 0.1) { score = Math.max(score, 2 + 1 / f); } }
      for (const r of things) { const [l, f] = rot(r.x - b.x, r.z - b.z, turn); if (f > half - 0.9 && f < half + 1.7 && Math.abs(l) <= wide + 0.3) score += 1; }
      if (score > top) { top = score; best = phi; }
    }
    frontOfRow.set(b, best); b.__sure = top >= 3;
  }
  for (const b of buildings) if (!b.__sure) { const usual = mode(buildings.filter((o) => o.part === b.part && o.__sure).map((o) => frontOfRow.get(o))); if (usual !== null) frontOfRow.set(b, usual); }

  const wsz = Math.max(dim.get(walkKey).x, dim.get(walkKey).z);
  const gaps = [];
  for (const b of buildings) {
    const d = dim.get(b.part), phi = frontOfRow.get(b), half = (Math.abs(phi) === 90 ? d.x : d.z) / 2, turn = -((b.ry || 0) + phi) * DEG;
    let near = Infinity;
    for (const r of roads) { const [l, f] = rot(r.x - b.x, r.z - b.z, turn); if (f > 0 && Math.abs(l) <= T / 2 + 0.1) near = Math.min(near, f - T / 2 - half); }
    if (near > 0.5 && near < 3 * T) gaps.push(near);
  }
  gaps.sort((a, b) => a - b);
  const PAVE = Math.max(1, Math.round((gaps[Math.floor(gaps.length / 2)] ?? wsz) / wsz)) * wsz;

  const ground = new Set([roadKey, walkKey, yardKey, kerbKey]);
  const loose = rows.filter((r) => ['thing', 'tree'].includes(kinds.get(r.part)) || (aloft(r) && ['building', 'vehicle'].includes(kinds.get(r.part)))
    || (['walk', 'road'].includes(kinds.get(r.part)) && !ground.has(r.part)));          // a front walk, a driveway slab: part of a lot
  const taken = new Set();
  const lotOf = (b, reach) => {
    const d = dim.get(b.part), front = frontOfRow.get(b), turn = -((b.ry || 0) + front) * DEG, sideways = Math.abs(front) === 90;
    const W = sideways ? d.z : d.x, D = sideways ? d.x : d.z;
    return { b, W, D, turn, front, members: [], reach };
  };
  const heights = buildings.map((b) => dim.get(b.part).y).sort((a, b) => a - b), median = heights[Math.floor(heights.length / 2)] || 0;
  const lots = buildings.map((b) => lotOf(b, count.get(b.part) === 1 && buildings.length > 3 && dim.get(b.part).y < 0.6 * median ? 9 : 0));
  for (const r of loose) {
    let best = null, bd = Infinity, where = null;
    for (const lot of lots) {
      const [cx, cz] = rot(r.x - lot.b.x, r.z - lot.b.z, lot.turn);
      const inside = aloft(r) && kinds.get(r.part) !== 'thing' ? Math.abs(cx) <= lot.W / 2 && Math.abs(cz) <= lot.D / 2
        : lot.reach ? Math.hypot(cx, cz) <= lot.reach
        : Math.abs(cx) <= lot.W / 2 + 0.6 && cz >= -lot.D / 2 - 0.6 && cz <= lot.D / 2 + PAVE + 0.4;
      const dist = Math.hypot(cx, cz);
      if (inside && dist < bd) { bd = dist; best = lot; where = [cx, cz]; }
    }
    if (best) { best.members.push({ r, cx: where[0], cz: where[1] }); taken.add(r); }
  }
  const landmarks = lots.filter((l) => l.reach), street = lots.filter((l) => !l.reach);
  const corner = street.filter((l) => /corner/.test(l.b.part)), mid = street.filter((l) => !/corner/.test(l.b.part));
  const free = loose.filter((r) => !taken.has(r));
  const trees = rows.filter((r) => kinds.get(r.part) === 'tree'), smalls = free.filter((r) => kinds.get(r.part) === 'thing' && dim.get(r.part).y < 2);
  const vehicles = of('vehicle').filter((r) => !aloft(r)), people = of('person');

  const depths = street.map((l) => l.D).sort((a, b) => a - b), fronts = street.map((l) => l.W).sort((a, b) => a - b);
  const deepest = depths[Math.floor(depths.length * 0.9)] ?? 2 * T, front = fronts[Math.floor(fronts.length / 2)] ?? 2 * T;
  const [bw, bd] = city.block ?? [Math.ceil(Math.max(6 * T, 4 * front) / T), Math.ceil((2 * deepest + 4) / T)];
  const [nx, nz] = blocks, W = S * T, BX = bw * T, BZ = bd * T;
  const cellX = BX + 2 * PAVE, cellZ = BZ + 2 * PAVE, SX = nx * cellX + (nx + 1) * W, SZ = nz * cellZ + (nz + 1) * W;
  const X0 = -SX / 2, Z0 = -SZ / 2, out = [];
  const copy = (r, x, z, ry) => { const n = { ...r, x, y: r.y || 0, z, ry, ord: r.__ord }; delete n.__i; delete n.__ord; delete n.__sure; out.push(n); return n; };
  const pave = (part, x0, z0, x1, z1, ry = 0) => {
    const d = dim.get(part), q = Math.abs(Math.round(ry / 90)) % 2 === 1, sx = q ? d.z : d.x, sz = q ? d.x : d.z, f = first.get(part);
    for (let x = x0; x < x1 - 0.01; x += sx) for (let z = z0; z < z1 - 0.01; z += sz) {
      out.push({ part, x: Math.min(x, Math.max(x0, x1 - sx)) + sx / 2, y: 0, z: Math.min(z, Math.max(z0, z1 - sz)) + sz / 2, ry, params: f.params, ord: f.__ord });
    }
  };
  const colX = (i) => X0 + W + i * (cellX + W), rowZ = (j) => Z0 + W + j * (cellZ + W);        // a block cell's near corner, pavement included
  const roadRects = [], lotsOut = [];
  for (let j = 0; j <= nz; j++) roadRects.push({ x0: X0, z0: Z0 + j * (cellZ + W), x1: X0 + SX, z1: Z0 + j * (cellZ + W) + W, alongX: true });
  for (let i = 0; i <= nx; i++) for (let j = 0; j < nz; j++) roadRects.push({ x0: X0 + i * (cellX + W), z0: rowZ(j), x1: X0 + i * (cellX + W) + W, z1: rowZ(j) + cellZ, alongX: false });
  let road = null;
  if (city.roads === 'tiles') for (const r of roadRects) pave(roadKey, r.x0, r.z0, r.x1, r.z1, r.alongX ? ryX : ryZ);
  else {
    const tally = new Map(), va = new THREE.Vector3(), vb = new THREE.Vector3(), vc = new THREE.Vector3();
    const tileObj = make(roadKey, first.get(roadKey), first.get(roadKey).__ord); tileObj.updateMatrixWorld(true);
    tileObj.traverse((n) => {
      const pos = n.isMesh && n.geometry?.attributes?.position; if (!pos) return;
      const col = n.geometry.attributes.color || null, mc = (Array.isArray(n.material) ? n.material[0] : n.material)?.color || { r: 1, g: 1, b: 1 };
      const idx = n.geometry.index, tris = (idx ? idx.count : pos.count) / 3;
      for (let t = 0; t < tris; t++) {
        const a = idx ? idx.getX(t * 3) : t * 3, b = idx ? idx.getX(t * 3 + 1) : t * 3 + 1, c = idx ? idx.getX(t * 3 + 2) : t * 3 + 2;
        va.fromBufferAttribute(pos, a); vb.fromBufferAttribute(pos, b); vc.fromBufferAttribute(pos, c);
        const nrm = vb.sub(va).cross(vc.sub(va)), area = nrm.length() / 2; if (nrm.y <= 0.5 * nrm.length()) continue;
        const key = [(col ? col.getX(a) : 1) * mc.r, (col ? col.getY(a) : 1) * mc.g, (col ? col.getZ(a) : 1) * mc.b].map((v) => Math.round(v * 64) / 64).join(',');
        tally.set(key, (tally.get(key) || 0) + area);
      }
    });
    const byArea = [...tally.entries()].sort((p, q) => q[1] - p[1]).map(([k, area]) => ({ rgb: k.split(',').map(Number), area }));
    const lum = (c) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2], total = byArea.reduce((n, c) => n + c.area, 0) || 1;
    const asphalt = byArea[0]?.rgb ?? [0.05, 0.055, 0.065];
    const paint = (byArea.filter((c) => lum(c.rgb) > lum(asphalt) + 0.18 && c.area / total > 0.002).sort((p, q) => lum(q.rgb) - lum(p.rgb))[0]?.rgb) ?? [0.72, 0.7, 0.62];
    const y = dim.get(roadKey).y, P = [], C = [];
    const quad = (x0, z0, x1, z1, yy, rgb) => { for (const [x, z] of [[x0, z0], [x0, z1], [x1, z1], [x0, z0], [x1, z1], [x1, z0]]) { P.push(x, yy, z); C.push(rgb[0], rgb[1], rgb[2]); } };
    for (const r of roadRects) quad(r.x0, r.z0, r.x1, r.z1, y, asphalt);
    const yp = y + 0.012, stripe = (r, u0, u1, v0, v1) => (r.alongX ? quad(u0, r.z0 + v0, u1, r.z0 + v1, yp, paint) : quad(r.x0 + v0, u0, r.x0 + v1, u1, yp, paint));
    const stretches = [];
    for (let j = 0; j <= nz; j++) for (let i = 0; i < nx; i++) stretches.push({ alongX: true, x0: colX(i), x1: colX(i) + cellX, z0: Z0 + j * (cellZ + W), z1: Z0 + j * (cellZ + W) + W });
    for (let i = 0; i <= nx; i++) for (let j = 0; j < nz; j++) stretches.push({ alongX: false, x0: X0 + i * (cellX + W), x1: X0 + i * (cellX + W) + W, z0: rowZ(j), z1: rowZ(j) + cellZ });
    for (const r of stretches) {
      const a = r.alongX ? r.x0 : r.z0, b = r.alongX ? r.x1 : r.z1, mid = W / 2;
      for (const [from, dir] of [[a, 1], [b, -1]]) {                         // each end: a zebra crossing, then a stop line on the lane that arrives
        for (let v = 0.55; v + 0.5 <= W - 0.5; v += 1.05) stripe(r, Math.min(from + dir * 0.7, from + dir * 3.3), Math.max(from + dir * 0.7, from + dir * 3.3), v, v + 0.5);
        const arriving = (dir === 1) === r.alongX ? [0.3, mid - 0.12] : [mid + 0.12, W - 0.3];
        if (b - a >= 30) stripe(r, Math.min(from + dir * 4.0, from + dir * 4.4), Math.max(from + dir * 4.0, from + dir * 4.4), arriving[0], arriving[1]);
      }
      for (let u = a + 5.4; u + 2.4 <= b - 5.4; u += 6) stripe(r, u, u + 2.4, mid - 0.075, mid + 0.075);   // ONE centre line
      stripe(r, a + 4.4, b - 4.4, 0.32, 0.42); stripe(r, a + 4.4, b - 4.4, W - 0.42, W - 0.32);               // an edge line at each kerb
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(P), 3)); g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(C), 3));
    g.computeVertexNormals();
    road = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95, metalness: 0, flatShading: true }));
    road.name = 'city-road'; road.receiveShadow = true;
  }
  const kerbLong = kerbKey ? Math.max(dim.get(kerbKey).x, dim.get(kerbKey).z) : 0, kerbWide = kerbKey ? Math.min(dim.get(kerbKey).x, dim.get(kerbKey).z) : 0;
  const kerbAlongX = kerbKey ? (dim.get(kerbKey).x >= dim.get(kerbKey).z ? 0 : 90) : 0;
  const isPark = new Map();
  for (let i = 0; i < nx; i++) for (let j = 0; j < nz; j++) {
    const cx0 = colX(i), cz0 = rowZ(j), cx1 = cx0 + cellX, cz1 = cz0 + cellZ;
    const park = rnd() < parks && (trees.length > 0 || landmarks.length > 0);
    isPark.set(`${i},${j}`, park);
    pave(walkKey, cx0, cz0, cx1, cz0 + PAVE); pave(walkKey, cx0, cz1 - PAVE, cx1, cz1);
    pave(walkKey, cx0, cz0 + PAVE, cx0 + PAVE, cz1 - PAVE); pave(walkKey, cx1 - PAVE, cz0 + PAVE, cx1, cz1 - PAVE);
    if (yardKey && (!park || !city.turf)) pave(yardKey, cx0 + PAVE, cz0 + PAVE, cx1 - PAVE, cz1 - PAVE);
    if (kerbKey) {
      pave(kerbKey, cx0, cz0, cx1, cz0 + kerbWide, kerbAlongX); pave(kerbKey, cx0, cz1 - kerbWide, cx1, cz1, kerbAlongX);
      pave(kerbKey, cx0, cz0, cx0 + kerbWide, cz1, kerbAlongX + 90); pave(kerbKey, cx1 - kerbWide, cz0, cx1, cz1, kerbAlongX + 90);
    }
  }

  const stamp = (lot, x, z, face) => {
    const d = dim.get(lot.b.part), ry = face - lot.front * DEG;
    const [ox, oz] = rot(d.cx, d.cz, ry);                        // the box is not always centred on the origin
    const bx = x - ox, bz = z - oz;
    const placedB = copy(lot.b, bx, bz, ry / DEG);
    const [fx, fz] = rot(0, lot.D / 2 + Math.min(PAVE, 2.2), face);
    lotsOut.push({ key: lot.b.part, x: +x.toFixed(2), z: +z.toFixed(2), facing: +face.toFixed(4), width: +lot.W.toFixed(2), depth: +lot.D.toFixed(2), door: [+(x + fx).toFixed(2), +(z + fz).toFixed(2)], park: lot.reach > 0 });
    const ways = colourways(lot.b.part);
    if (ways.list.length > 1 && (lot.uses = (lot.uses || 0) + 1) > 1) { placedB.params = { ...(lot.b.params || {}), [ways.name]: pick(ways.list) }; placedB.ownNight = true; }
    for (const m of lot.members) {
      const md = dim.get(m.r.part), reach = lot.D / 2 + PAVE - 0.15 - Math.min(md.x, md.z) / 2;
      const cz = (m.r.y || 0) < 0.5 && m.cz > reach ? Math.max(lot.D / 2 + 0.2, reach) : m.cz;
      const [wx, wz] = rot(m.cx, cz, face);
      copy(m.r, bx + wx, bz + wz, (m.r.ry || 0) + ry / DEG - (lot.b.ry || 0));    // members were measured from the building's ORIGIN
    }
  };

  const fillEdge = (e, used, deep) => {
    const clear = (e, s, w, d) => { const [cx, cz, rw, rd] = e.at(s, w, d); return !used.some((u) => cx - rw / 2 < u[2] - 0.05 && cx + rw / 2 > u[0] + 0.05 && cz - rd / 2 < u[3] - 0.05 && cz + rd / 2 > u[1] + 0.05); };
      let a = 0, b = e.len;
      while (a < b - 1 && !clear(e, a, 1, 3)) a += 0.5;
      while (b > a + 1 && !clear(e, b - 1, 1, 3)) b -= 0.5;
      const pool = street.filter((l) => l.D <= deep);
      if (!pool.length || b - a < Math.min(...pool.map((l) => l.W))) return;
      let best = null;
      for (let t = 0; t < 12; t++) {
        const seq = []; let left = b - a, last = null;
        for (let guard = 0; guard < 40; guard++) {
          const atEnd = !seq.length || left <= Math.max(...pool.map((l) => l.W)) + 0.01;
          let can = pool.filter((l) => l.W <= left + 0.01 && l.b.part !== last);
          if (!can.length) can = pool.filter((l) => l.W <= left + 0.01);
          if (!can.length) break;
          const cornerish = can.filter((l) => /corner/.test(l.b.part)), plain = can.filter((l) => !/corner/.test(l.b.part));
          const from = atEnd && cornerish.length ? cornerish : (plain.length ? plain : can);
          const w = from.map((l) => (l.members.length ? 3 : 1) / (1 + (l.uses || 0) + seq.filter((q) => q === l).length * 2));
          let r = rnd() * w.reduce((x, y) => x + y, 0), lot = from[from.length - 1];
          for (let i = 0; i < from.length; i++) { r -= w[i]; if (r <= 0) { lot = from[i]; break; } }
          seq.push(lot); left -= lot.W; last = lot.b.part;
        }
        if (seq.length && (!best || left < best.left - 0.01)) best = { seq, left };
      }
      if (!best) return;
      const alley = best.seq.length > 1 ? Math.min(3, best.left / (best.seq.length - 1)) : 0;
      let s = a + (best.left - alley * (best.seq.length - 1)) / 2;
      for (const lot of best.seq) {
        const [cx, cz, w, d] = e.at(s, lot.W, lot.D);
        if (clear(e, s, lot.W, lot.D)) { used.push([cx - w / 2, cz - d / 2, cx + w / 2, cz + d / 2]); stamp(lot, cx, cz, e.face); }
        s += lot.W + alley;
      }
  };

  for (let bi = 0; bi < nx; bi++) for (let bj = 0; bj < nz; bj++) {
    const x0 = colX(bi) + PAVE, z0 = rowZ(bj) + PAVE, x1 = x0 + BX, z1 = z0 + BZ;
    if (isPark.get(`${bi},${bj}`)) {
      const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
      if (landmarks.length) stamp(pick(landmarks), cx, cz, pick([0, 90, 180, -90]) * DEG);
      const n = Math.round(BX * BZ / 70), spots = [];
      for (let t = 0; t < n * 6 && spots.length < n && trees.length; t++) {
        const x = x0 + 2 + rnd() * (x1 - x0 - 4), z = z0 + 2 + rnd() * (z1 - z0 - 4);
        if (Math.hypot(x - cx, z - cz) < (landmarks.length ? 8 : 0) || spots.some((q) => Math.hypot(q[0] - x, q[1] - z) < 4.5)) continue;
        spots.push([x, z]); copy(pick(trees), x, z, rnd() * 360);
      }
      for (let t = 0; t < Math.min(6, smalls.length); t++) copy(pick(smalls), x0 + 1 + rnd() * (x1 - x0 - 2), z0 + 1 + rnd() * (z1 - z0 - 2), pick([0, 90, 180, -90]));
      continue;
    }
    const used = [], deep = Math.min(x1 - x0, z1 - z0) / 2 + 0.01;
    const edges = [
      { len: x1 - x0, face: 180 * DEG, at: (s, w, d) => [x0 + s + w / 2, z0 + d / 2, w, d] },
      { len: x1 - x0, face: 0,         at: (s, w, d) => [x1 - s - w / 2, z1 - d / 2, w, d] },
      { len: z1 - z0, face: -90 * DEG, at: (s, w, d) => [x0 + d / 2, z1 - s - w / 2, d, w] },
      { len: z1 - z0, face: 90 * DEG,  at: (s, w, d) => [x1 - d / 2, z0 + s + w / 2, d, w] },
    ];
    for (const e of edges) fillEdge(e, used, deep);
  }

  if (city.boundary !== false && street.length) {
    const deepest2 = Math.max(...street.map((l) => l.D)), xa = X0 - PAVE, xb = X0 + SX + PAVE, za = Z0 - PAVE, zb = Z0 + SZ + PAVE;
    pave(walkKey, xa, za, xb, Z0); pave(walkKey, xa, Z0 + SZ, xb, zb); pave(walkKey, xa, Z0, X0, Z0 + SZ); pave(walkKey, X0 + SX, Z0, xb, Z0 + SZ);
    if (kerbKey) {
      pave(kerbKey, X0, Z0 - kerbWide, X0 + SX, Z0, kerbAlongX); pave(kerbKey, X0, Z0 + SZ, X0 + SX, Z0 + SZ + kerbWide, kerbAlongX);
      pave(kerbKey, X0 - kerbWide, Z0, X0, Z0 + SZ, kerbAlongX + 90); pave(kerbKey, X0 + SX, Z0, X0 + SX + kerbWide, Z0 + SZ, kerbAlongX + 90);
    }
    const used = [], lenX = xb - xa + 2 * deepest2, lenZ = zb - za;
    const rim = [
      { len: lenX, face: 0,          at: (s, w, d) => [xa - deepest2 + s + w / 2, za - d / 2, w, d] },     // north row, facing +Z into town
      { len: lenX, face: 180 * DEG,  at: (s, w, d) => [xb + deepest2 - s - w / 2, zb + d / 2, w, d] },     // south row, facing -Z
      { len: lenZ, face: 90 * DEG,   at: (s, w, d) => [xa - d / 2, za + s + w / 2, d, w] },                // west row, facing +X
      { len: lenZ, face: -90 * DEG,  at: (s, w, d) => [xb + d / 2, zb - s - w / 2, d, w] },                // east row, facing -X
    ];
    for (const e of rim) fillEdge(e, used, deepest2 + 0.01);
  }

  if (vehicles.length && W >= 6) {
    const rate = Math.min(0.2, vehicles.length / Math.max(1, roads.length) * 1.5), slot = 7;
    const parkAt = (x, z, alongX) => {
      let v = pick(vehicles); for (let t = 0; t < 3 && Math.max(dim.get(v.part).x, dim.get(v.part).z) > 5.5 && rnd() < 0.75; t++) v = pick(vehicles);
      const d = dim.get(v.part), wide = Math.min(d.x, d.z), longZ = d.z >= d.x, side = rnd() < 0.5 ? -1 : 1, off = side * (W / 2 - wide / 2 - 0.35);
      copy(v, alongX ? x : x + off, alongX ? z + off : z, (alongX ? (longZ ? 90 : 0) : (longZ ? 0 : 90)) + (side < 0 ? 180 : 0));
    };
    for (let j = 0; j <= nz; j++) for (let i = 0; i < nx; i++) for (let x = colX(i) + 5; x < colX(i) + cellX - 5; x += slot) if (rnd() < rate) parkAt(x, Z0 + j * (cellZ + W) + W / 2, true);
    for (let i = 0; i <= nx; i++) for (let j = 0; j < nz; j++) for (let z = rowZ(j) + 5; z < rowZ(j) + cellZ - 5; z += slot) if (rnd() < rate) parkAt(X0 + i * (cellX + W) + W / 2, z, false);
  }
  if (people.length) {
    const want = Math.min(40, Math.round(people.length * (nx * nz) / 2));
    const stood = [];
    for (let n = 0; n < want * 3 && stood.length < want; n++) {
      const cx0 = colX(Math.floor(rnd() * nx)), cz0 = rowZ(Math.floor(rnd() * nz)), onX = rnd() < 0.5, far = rnd() < 0.5;
      const x = onX ? cx0 + rnd() * cellX : (far ? cx0 + cellX - PAVE / 2 : cx0 + PAVE / 2), z = onX ? (far ? cz0 + cellZ - PAVE / 2 : cz0 + PAVE / 2) : cz0 + rnd() * cellZ;
      if (stood.some((q) => Math.hypot(q[0] - x, q[1] - z) < 2)) continue;          // nobody stands inside anybody
      stood.push([x, z]);
      const walker = copy(pick(people), x, z, rnd() * 360);
      if (rnd() < 0.66) { const m = PAVE / 2, loop = [[cx0 + m, cz0 + m], [cx0 + cellX - m, cz0 + m], [cx0 + cellX - m, cz0 + cellZ - m], [cx0 + m, cz0 + cellZ - m]]; walker.path = rnd() < 0.5 ? loop : loop.reverse(); }
    }
  }
  const streetsX = [], streetsZ = [], junctions = [];
  for (let i = 0; i <= nx; i++) streetsX.push(+(X0 + i * (cellX + W) + W / 2).toFixed(2));          // centre lines of the streets that run along Z
  for (let j = 0; j <= nz; j++) streetsZ.push(+(Z0 + j * (cellZ + W) + W / 2).toFixed(2));          // ...and of those that run along X
  for (const x of streetsX) for (const z of streetsZ) junctions.push([x, z]);
  return { rows: out, road, roadRects, roadY: dim.get(roadKey).y, tile: T, street: W, pavement: PAVE, lotsList: lotsOut, streets: { x: streetsX, z: streetsZ }, junctions, green: !yardKey && trees.length > 0, size: [SX, SZ], lots: street.length, landmarks: landmarks.length };
}

export default cityLayout;
