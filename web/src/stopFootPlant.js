import * as THREE from 'three';

// Keep feet in world space while MotionBricks blends from locomotion to its idle clip.
// An airborne foot remains animation-driven until it reaches the support-foot height.
export class StopFootPlant {
  constructor(humanoid) {
    this.elapsed = 0;
    this.legs = ['left', 'right'].map(side => {
      const joints = ['UpperLeg', 'LowerLeg', 'Foot'].map(part => humanoid.getNormalizedBoneNode(side + part));
      if (joints.some(node => !node)) return null;
      joints[2].updateWorldMatrix(true, false);
      return {
        joints,
        position: joints[2].getWorldPosition(new THREE.Vector3()),
        anchor: null,
      };
    }).filter(Boolean);
    this.floorY = Math.min(...this.legs.map(leg => leg.position.y));
    for (const leg of this.legs) {
      if (leg.position.y <= this.floorY + 0.025) leg.anchor = leg.position.clone();
    }
  }

  update(dt) {
    const step = Math.max(0, Math.min(0.1, Number(dt) || 0));
    this.elapsed += step;
    for (const leg of this.legs) {
      const foot = leg.joints[2];
      foot.updateWorldMatrix(true, false);
      const current = foot.getWorldPosition(new THREE.Vector3());
      if (!leg.anchor) {
        const descending = step > 0 && (current.y - leg.position.y) / step <= 0.03;
        if (this.elapsed >= 0.08 && current.y <= this.floorY + 0.035 &&
            (descending || this.elapsed >= 0.35)) {
          leg.anchor = current.clone();
        }
      }
      leg.position.copy(current);
      if (leg.anchor) solvePlantedFoot(leg.joints, leg.anchor);
    }
  }
}

// Two-joint CCD in world coordinates. Preserve the animated ankle orientation.
export function solvePlantedFoot(joints, target) {
  const [upper, lower, foot] = joints;
  foot.updateWorldMatrix(true, false);
  const ankleOrientation = foot.getWorldQuaternion(new THREE.Quaternion());
  for (let iteration = 0; iteration < 8; iteration++) {
    for (const joint of [lower, upper]) {
      joint.updateWorldMatrix(true, true);
      const origin = joint.getWorldPosition(new THREE.Vector3());
      const from = foot.getWorldPosition(new THREE.Vector3()).sub(origin);
      const to = target.clone().sub(origin);
      if (from.lengthSq() < 1e-10 || to.lengthSq() < 1e-10) continue;
      const delta = new THREE.Quaternion().setFromUnitVectors(from.normalize(), to.normalize());
      const world = joint.getWorldQuaternion(new THREE.Quaternion()).premultiply(delta);
      const parentWorld = joint.parent.getWorldQuaternion(new THREE.Quaternion());
      joint.quaternion.copy(parentWorld.invert().multiply(world));
    }
    foot.updateWorldMatrix(true, false);
    if (foot.getWorldPosition(new THREE.Vector3()).distanceToSquared(target) < 1e-8) break;
  }
  foot.updateWorldMatrix(true, false);
  const parentWorld = foot.parent.getWorldQuaternion(new THREE.Quaternion());
  foot.quaternion.copy(parentWorld.invert().multiply(ankleOrientation));
}
