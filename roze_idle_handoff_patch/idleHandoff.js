/**
 * MotionBricks -> idle.vrma orientation-preserving handoff for three-vrm.
 * This file does NOT modify the NVIDIA motion model or the VRM asset.
 *
 * The existing app MUST stop writing MotionBricks bone transforms when this
 * handoff starts.  Otherwise AnimationMixer and MotionBricks will fight.
 */
import * as THREE from 'three';

const UP = new THREE.Vector3(0, 1, 0);
const EULER_ORDER = 'YXZ';
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const ease = (t) => t * t * (3 - 2 * t);
const wrapPi = (a) => Math.atan2(Math.sin(a), Math.cos(a));

function yawOf(q) {
  return new THREE.Euler().setFromQuaternion(q, EULER_ORDER).y;
}

function getTrack(clip, name, property) {
  return clip.tracks.find((t) => t.name === `${name}.${property}`);
}

/**
 * Make a new, independent VRMA clip whose hips start at the EXACT local pose
 * that the MotionBricks renderer is displaying. Keep the scene root untouched.
 *
 * preserveYaw=true prevents an idle clip from rotating the entire body.
 * false preserves any relative root heading turns authored in the VRMA.
 */
export function alignIdleClipToCurrentPose(vrm, inputClip, { preserveYaw = true } = {}) {
  const hips = vrm.humanoid.getNormalizedBoneNode('hips');
  if (!hips) throw new Error('VRM normalized hips bone was not found');
  hips.updateWorldMatrix(true, false);
  const clip = inputClip.clone();
  clip.name = `${inputClip.name || 'idle'}_heading_aligned`;
  const rootName = hips.name;
  const rootQTrack = getTrack(clip, rootName, 'quaternion');
  const rootPTrack = getTrack(clip, rootName, 'position');
  const currentQ = hips.quaternion.clone().normalize();
  const currentP = hips.position.clone();
  const currentYaw = yawOf(currentQ);
  let sourceYaw = 0;

  if (rootQTrack) {
    if (!rootQTrack.values || rootQTrack.values.length < 4 || rootQTrack.values.length % 4 !== 0) {
      throw new Error('VRMA hips quaternion keyframes are malformed');
    }
    const firstQ = new THREE.Quaternion().fromArray(rootQTrack.values, 0).normalize();
    sourceYaw = yawOf(firstQ);
    const q = new THREE.Quaternion();
    const e = new THREE.Euler(0, 0, 0, EULER_ORDER);
    for (let i = 0; i < rootQTrack.values.length; i += 4) {
      q.fromArray(rootQTrack.values, i).normalize();
      e.setFromQuaternion(q, EULER_ORDER);
      e.y = currentYaw + (preserveYaw ? 0 : wrapPi(e.y - sourceYaw));
      q.setFromEuler(e).normalize().toArray(rootQTrack.values, i);
    }
  }

  // Anchor the HIP translation, not VRM.scene.position. The scene's existing
  // world transform is the position determined by MotionBricks click movement.
  if (rootPTrack) {
    if (!rootPTrack.values || rootPTrack.values.length < 3 || rootPTrack.values.length % 3 !== 0) {
      throw new Error('VRMA hips position keyframes are malformed');
    }
    const firstP = new THREE.Vector3().fromArray(rootPTrack.values, 0);
    const deltaYaw = wrapPi(currentYaw - sourceYaw);
    const rot = new THREE.Quaternion().setFromAxisAngle(UP, deltaYaw);
    for (let i = 0; i < rootPTrack.values.length; i += 3) {
      const delta = new THREE.Vector3().fromArray(rootPTrack.values, i)
        .sub(firstP).applyQuaternion(rot);
      currentP.clone().add(delta).toArray(rootPTrack.values, i);
    }
  }

  // Force a fresh keyframe binding in AnimationMixer.
  clip.resetDuration();
  return { clip, hips, currentYaw, sourceYaw, hadHipsRotation: Boolean(rootQTrack) };
}

/**
 * Begin idle playback without a one-frame snap.
 * Must be called AFTER the last displayed MotionBricks pose has been applied.
 *
 * API:
 *   const handoff = new IdleHandoff(vrm, idleClip, { fadeSeconds: .45 });
 *   handoff.update(deltaSeconds); // on every render frame, instead of applyPose
 *   handoff.stop();               // before moving again
 */
export class IdleHandoff {
  constructor(vrm, idleClip, {
    fadeSeconds = 0.45,
    preserveYaw = true,
    debug = false,
  } = {}) {
    if (!vrm?.humanoid || !vrm?.scene || !idleClip) {
      throw new Error('IdleHandoff needs a loaded vrm and a VRMA AnimationClip');
    }
    if (!(Number.isFinite(fadeSeconds) && fadeSeconds > 0)) {
      throw new Error('fadeSeconds must be positive');
    }
    this.vrm = vrm;
    this.fadeSeconds = fadeSeconds;
    this.elapsed = 0;
    this.active = true;
    this.debug = debug;

    const aligned = alignIdleClipToCurrentPose(vrm, idleClip, { preserveYaw });
    this.clip = aligned.clip;
    this.rootPosition = vrm.scene.position.clone();
    this.rootRotation = vrm.scene.quaternion.clone();

    // Capture the actual outgoing pose for ALL nodes driven by the new clip.
    // The AnimationMixer will overwrite these nodes on each update. During
    // the short transition, blend its pose from the outgoing values.
    this.snapshots = [];
    const seen = new Set();
    for (const track of this.clip.tracks) {
      let prop = null;
      if (track.name.endsWith('.quaternion')) prop = 'quaternion';
      else if (track.name.endsWith('.position')) prop = 'position';
      if (!prop) continue;
      const nodeName = track.name.slice(0, -(prop.length + 1));
      const node = vrm.scene.getObjectByName(nodeName);
      if (!node || seen.has(`${node.uuid}.${prop}`)) continue;
      seen.add(`${node.uuid}.${prop}`);
      this.snapshots.push({ node, prop, original: node[prop].clone() });
    }

    this.mixer = new THREE.AnimationMixer(vrm.scene);
    this.action = this.mixer.clipAction(this.clip);
    this.action.reset().setLoop(THREE.LoopRepeat, Infinity).play();
    if (debug) {
      console.info('[RozeIdleHandoff]', {
        outgoingYawDeg: THREE.MathUtils.radToDeg(aligned.currentYaw),
        vrmaStartYawDeg: THREE.MathUtils.radToDeg(aligned.sourceYaw),
        hadHipsRotation: aligned.hadHipsRotation,
        outgoingNodes: this.snapshots.length,
        fadeSeconds, preserveYaw,
      });
    }
  }

  update(deltaSeconds) {
    if (!this.active) return;
    const dt = Math.max(0, Math.min(0.1, Number(deltaSeconds) || 0));
    this.elapsed += dt;
    this.mixer.update(dt);
    const weight = ease(clamp01(this.elapsed / this.fadeSeconds));
    if (weight < 1) {
      for (const { node, prop, original } of this.snapshots) {
        if (prop === 'quaternion') {
          node.quaternion.slerpQuaternions(original, node.quaternion.clone(), weight);
        } else {
          node.position.lerpVectors(original, node.position.clone(), weight);
        }
      }
    }
    // Prevent a separate root-motion writer from resetting the world placement
    // during idle. Scene root is NOT a valid place to apply VRMA root motion.
    this.vrm.scene.position.copy(this.rootPosition);
    this.vrm.scene.quaternion.copy(this.rootRotation);
  }

  stop() {
    if (!this.active) return;
    this.active = false;
    this.action.stop();
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.vrm.scene);
    this.snapshots.length = 0;
  }
}
