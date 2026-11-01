import * as THREE from 'three';

const LOCKED = [
  'hips',
  'leftUpperLeg', 'leftLowerLeg', 'leftFoot', 'leftToes',
  'rightUpperLeg', 'rightLowerLeg', 'rightFoot', 'rightToes',
];
const UPPER = [
  'spine', 'chest', 'upperChest', 'neck', 'head', 'leftEye', 'rightEye',
  'leftShoulder', 'leftUpperArm', 'leftLowerArm', 'leftHand',
  'rightShoulder', 'rightUpperArm', 'rightLowerArm', 'rightHand',
];
const NAMES = [...LOCKED, ...UPPER];
const ease = t => { const x = Math.max(0, Math.min(1, t)); return x * x * (3 - 2 * x); };

function trackFor(clip, nodeName, property) {
  if (!clip?.tracks || !nodeName) return null;
  return clip.tracks.find((t) => t.name === `${nodeName}.${property}`) || null;
}

// Preserve the *rendered* stance. No IK, rest-pose legs, or corrective hip motion.
// Upper body may ease toward idle.vrma with a capped blend; legs and hips stay frozen.
export class GroundedIdle {
  constructor(vrm, { idleClip = null, fadeSeconds = 0.8, upperBlendMax = 0.65 } = {}) {
    this.vrm = vrm;
    this.elapsed = 0;
    this.fadeSeconds = Math.max(1e-3, Number(fadeSeconds) || 0.8);
    this.upperBlendMax = Math.max(0, Math.min(1, Number(upperBlendMax) || 0));
    this.rootPosition = vrm.scene.position.clone();
    this.rootQuaternion = vrm.scene.quaternion.clone();
    this.bones = NAMES.map((name) => {
      const node = vrm.humanoid.getNormalizedBoneNode(name);
      return node && { name, node, q: node.quaternion.clone(), p: node.position.clone() };
    }).filter(Boolean);
    this.locked = this.bones.filter((b) => LOCKED.includes(b.name));
    this.upper = this.bones.filter((b) => UPPER.includes(b.name));
    this.upperTargets = new Map();
    if (idleClip) {
      for (const bone of this.upper) {
        const track = trackFor(idleClip, bone.node.name, 'quaternion');
        if (!track || track.values.length < 4) continue;
        this.upperTargets.set(
          bone.name,
          new THREE.Quaternion().fromArray(track.values, 0).normalize(),
        );
      }
    }
  }

  update(dt) {
    this.elapsed += Math.max(0, Math.min(0.1, Number(dt) || 0));
    this.vrm.scene.position.copy(this.rootPosition);
    this.vrm.scene.quaternion.copy(this.rootQuaternion);

    for (const bone of this.locked) {
      bone.node.quaternion.copy(bone.q);
      bone.node.position.copy(bone.p);
    }

    const weight = ease(this.elapsed / this.fadeSeconds) * this.upperBlendMax;
    for (const bone of this.upper) {
      bone.node.position.copy(bone.p);
      const target = this.upperTargets.get(bone.name);
      if (target && weight > 0) {
        bone.node.quaternion.slerpQuaternions(bone.q, target, weight);
      } else {
        bone.node.quaternion.copy(bone.q);
      }
    }

    const breath = 0.004 * Math.sin(this.elapsed * 2 * Math.PI / 4.2) * ease(this.elapsed / 0.45);
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), breath);
    for (const bone of this.upper) {
      if (bone.name === 'spine' || bone.name === 'chest') bone.node.quaternion.multiply(q);
    }
  }

  // Starting a new walk: interpolate joint rotations only. Live root keeps moving.
  blendToLive(weight) {
    const t = ease(weight);
    for (const bone of this.bones) {
      bone.node.quaternion.slerpQuaternions(bone.q, bone.node.quaternion.clone(), t);
      if (bone.name === 'hips') bone.node.position.lerpVectors(bone.p, bone.node.position.clone(), t);
    }
  }
}
