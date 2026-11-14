import * as THREE from 'three';

// VRM normalized humanoid: the fingers curl about their local Z axes.
// Opposite signs preserve a mirrored, relaxed shape on left and right hands.
const FINGERS = ['Index', 'Middle', 'Ring', 'Little'];
const JOINTS = [['Proximal', 1], ['Intermediate', 0.7], ['Distal', 0.35]];
const AXIS = new THREE.Vector3(0, 0, 1);

export function clampDetailDeg(value, min, max) {
  const n = Number(value);
  return Number.isFinite(n) ? Math.max(min, Math.min(max, n)) : 0;
}

export function detailData({fingerDeg = 0, ankleDeg = 0} = {}) {
  return {
    finger_curl_deg: Number(clampDetailDeg(fingerDeg, 0, 40).toFixed(1)),
    ankle_roll_deg: Number(clampDetailDeg(ankleDeg, -15, 15).toFixed(1)),
  };
}

/**
 * Temporary, reversible render-only corrections.
 * Restore BEFORE the next MotionBricks / GroundedIdle / VRMA update so these
 * corrections never accumulate or contaminate the captured settled pose.
 */
export class PoseDetailAdjuster {
  constructor() { this.originals = []; }
  restore() {
    for (const {node, quaternion} of this.originals) {
      node.quaternion.copy(quaternion);
    }
    this.originals.length = 0;
  }
  apply(vrm, {finger_curl_deg = 0, ankle_roll_deg = 0} = {}) {
    if (!vrm?.humanoid) return;
    const human = vrm.humanoid;
    const curl = THREE.MathUtils.degToRad(clampDetailDeg(finger_curl_deg, 0, 40));
    const roll = THREE.MathUtils.degToRad(clampDetailDeg(ankle_roll_deg, -15, 15));
    const q = new THREE.Quaternion();
    const rotate = (name, radians) => {
      if (!radians) return;
      const node = human.getNormalizedBoneNode(name);
      if (!node) return; // Some VRMs omit individual finger joints.
      this.originals.push({node, quaternion: node.quaternion.clone()});
      node.quaternion.multiply(q.setFromAxisAngle(AXIS, radians));
    };
    for (const side of ['left', 'right']) {
      const mirror = side === 'left' ? 1 : -1;
      for (const finger of FINGERS) {
        for (const [joint, weight] of JOINTS) {
          rotate(`${side}${finger}${joint}`, mirror * curl * weight);
        }
      }
      // Thumb bends less, so the hand looks relaxed rather than clenched.
      rotate(`${side}ThumbProximal`, mirror * curl * 0.35);
      rotate(`${side}ThumbDistal`, mirror * curl * 0.2);
      // Signed roll, mirrored between feet. Does not rotate the toes' heading.
      rotate(`${side}Foot`, mirror * roll);
    }
  }
}
