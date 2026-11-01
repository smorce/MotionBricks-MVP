import * as THREE from 'three';

// 停止時の足幅を保ち、高い側の足を着地させてから呼吸へ移る。
export class SettledIdle {
  constructor(humanoid) {
    this.elapsed = 0;
    this.bones = [];
    for (const name of ['hips', 'spine', 'chest', 'upperChest',
      'leftUpperLeg', 'leftLowerLeg', 'leftFoot', 'leftToes',
      'rightUpperLeg', 'rightLowerLeg', 'rightFoot', 'rightToes']) {
      const node = humanoid.getNormalizedBoneNode(name);
      if (node) this.bones.push({name, node, q:node.quaternion.clone(), p:node.position.clone()});
    }
    this.legs = ['left', 'right'].map(side => {
      const joints = ['UpperLeg', 'LowerLeg', 'Foot'].map(part => humanoid.getNormalizedBoneNode(side + part));
      if (joints.some(node => !node)) return null;
      joints[2].updateWorldMatrix(true, false);
      return {joints, start:joints[2].getWorldPosition(new THREE.Vector3())};
    }).filter(Boolean);
    this.floor = Math.min(...this.legs.map(leg => leg.start.y));
  }

  update(dt) {
    this.elapsed += Math.max(0, Math.min(0.1, Number(dt) || 0));
    for (const bone of this.bones) {
      bone.node.quaternion.copy(bone.q);
      bone.node.position.copy(bone.p);
    }
    const t = Math.min(1, this.elapsed / 0.45);
    const blend = t * t * (3 - 2 * t);
    for (const {joints, start} of this.legs) {
      const target = start.clone();
      const lifted = start.y - this.floor > 0.008;
      target.y = lifted ? THREE.MathUtils.lerp(start.y, this.floor, blend) + 0.015 * Math.sin(Math.PI * t) : start.y;
      // 二関節の反復IK。横方向の着地点は変更しない。
      for (let iteration = 0; iteration < 6; iteration++) {
        for (const joint of [joints[1], joints[0]]) {
          joint.updateWorldMatrix(true, true);
          const origin = joint.getWorldPosition(new THREE.Vector3());
          const from = joints[2].getWorldPosition(new THREE.Vector3()).sub(origin);
          const to = target.clone().sub(origin);
          if (from.lengthSq() < 1e-10 || to.lengthSq() < 1e-10) continue;
          const delta = new THREE.Quaternion().setFromUnitVectors(from.normalize(), to.normalize());
          const world = joint.getWorldQuaternion(new THREE.Quaternion()).premultiply(delta);
          const parent = joint.parent.getWorldQuaternion(new THREE.Quaternion());
          joint.quaternion.copy(parent.invert().multiply(world));
        }
      }
    }
    const breath = Math.sin(this.elapsed * Math.PI * 2 / 4.2) * 0.006 * blend;
    for (const bone of this.bones) {
      if (bone.name === 'chest' || bone.name === 'spine') {
        bone.node.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), breath));
      }
    }
  }
}
