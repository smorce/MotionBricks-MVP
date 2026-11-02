// Polyfork clips.mjs. Its API is in API.md beside this file: you do not need to read this code.
// The commented source is https://polyfork.dev/cdn/clips.mjs
import * as THREE from 'three';

export const CLIP_NAMES = ['Idle', 'Walk', 'Run', 'Agree', 'Head shake', 'Laughing', 'Drinking', 'Drunk idle',
  'Punch', 'Kick', 'Hard landing', 'Swimming', 'Treading water', 'Thriller', 'Swing', 'Twist', 'Hip hop',
  'Sitting', 'Sitting talking', 'Sit down', 'Stand up', 'Driving', 'Phone call', 'Talking', 'Arms folded',
  'Leaning on rail', 'Calling from rail', 'Interact', 'Pick up', 'Fixing', 'Crouch', 'Eating', 'Opening',
  'Holding torch', 'Holding lantern', 'Harvesting', 'Planting', 'Watering', 'Chopping wood', 'Walk formal',
  'Walk carrying', 'Jog', 'Pushing', 'Dance'];

const slug = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, '-');
const HERE = new URL('.', import.meta.url).href;
const fetched = new Map();      // url -> promise, so ten characters fetch Walk once
const CDN = 'https://polyfork.dev/cdn/';
const HOME = /^https:\/\/polyfork\.dev\//.test(HERE) ? HERE : CDN;
const getClip = (base, name) => {
  const url = `${base}anim-${slug(name)}.json`;
  if (!fetched.has(url)) {
    fetched.set(url, fetch(url).then((r) => {
      if (!r.ok) throw new Error(`clips.mjs: no clip "${name}" (HTTP ${r.status}). The names are: ${CLIP_NAMES.join(', ')}`);
      return r.json();
    }));
  }
  return fetched.get(url);
};

const BAKED_HIP = 0.95;

function toClip(raw, name, bones, hips, inPlace) {
  const tracks = [];
  for (const [bone, values] of Object.entries(raw.tracks)) {
    const b = bones[bone];
    if (!b || !values.length) continue;
    tracks.push(new THREE.QuaternionKeyframeTrack(`${b.uuid}.quaternion`, raw.times.slice(), Float32Array.from(values)));
  }
  let rest = hips.position.clone();
  for (let o = hips.parent; o; o = o.parent) {
    const r = o.userData?.restHips;
    if (Array.isArray(r) && r.length === 3) { rest = new THREE.Vector3(...r); break; }
  }
  const ratio = (rest.y || BAKED_HIP) / BAKED_HIP;
  const pos = new Float32Array(raw.hips.length);
  for (let i = 0; i < raw.hips.length; i += 3) {
    pos[i] = rest.x + (inPlace ? 0 : raw.hips[i] * ratio);
    pos[i + 1] = rest.y + raw.hips[i + 1] * ratio;
    pos[i + 2] = rest.z + (inPlace ? 0 : raw.hips[i + 2] * ratio);
  }
  tracks.push(new THREE.VectorKeyframeTrack(`${hips.uuid}.position`, raw.times.slice(), pos));
  return new THREE.AnimationClip(name, -1, tracks);
}

export async function animate(character, { clips = ['Idle', 'Walk', 'Run'], inPlace = true, fade = 0.2, base = HOME } = {}) {
  const bones = {};
  character.traverse((o) => { if (o.isBone && !bones[o.name]) bones[o.name] = o; });
  const hips = bones.Hips;
  if (!['Hips', 'Spine2', 'LeftForeArm', 'RightUpLeg'].every((n) => bones[n])) {
    throw new Error('clips.mjs: this is not one of our humanoids (it lacks the Mixamo bones Hips, Spine2, '
      + 'LeftForeArm, RightUpLeg), so these clips do not fit it. Animals and machines move differently: '
      + 'see walk.mjs, or the `animation` field of get_asset.');
  }
  if (!base.endsWith('/')) base += '/';
  const raws = await Promise.all(clips.map((n) => getClip(base, n)));
  const mixer = new THREE.AnimationMixer(character);
  const actions = {};
  clips.forEach((n, i) => { actions[n] = mixer.clipAction(toClip(raws[i], n, bones, hips, inPlace)); });

  let current = null;
  const play = (name, { fade: f = fade, loop = true, timeScale = 1 } = {}) => {
    const next = actions[name];
    if (!next) throw new Error(`clips.mjs: "${name}" was not loaded. Loaded: ${Object.keys(actions).join(', ')}. Pass { clips: [...] } to animate().`);
    next.timeScale = timeScale;
    if (next === current) return next;
    next.reset();
    next.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
    next.clampWhenFinished = !loop;
    next.play();
    if (current) current.crossFadeTo(next, f, false);
    current = next;
    return next;
  };

  const scale = (hips.position.y || BAKED_HIP) / BAKED_HIP;
  const locomotion = (speed) => {
    const s = Math.abs(speed) / scale;
    const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
    if (s < 0.15 || !actions.Walk) return play(actions.Idle ? 'Idle' : clips[0]);
    if (s < 2.8 || !actions.Run) return play('Walk', { timeScale: clamp(s / 1.45, 0.55, 1.9) });
    return play('Run', { timeScale: clamp(s / 3.9, 0.7, 1.6) });
  };

  if (actions.Idle) play('Idle', { fade: 0 });
  return { mixer, actions, play, locomotion, update: (dt) => mixer.update(dt), names: Object.keys(actions) };
}

export default animate;
