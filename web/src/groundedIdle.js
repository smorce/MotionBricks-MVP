import * as THREE from 'three';

const NAMES = ['hips','spine','chest','upperChest','neck','head','leftEye','rightEye',
  'leftUpperLeg','leftLowerLeg','leftFoot','leftToes','rightUpperLeg','rightLowerLeg','rightFoot','rightToes',
  'leftShoulder','leftUpperArm','leftLowerArm','leftHand','rightShoulder','rightUpperArm','rightLowerArm','rightHand'];
const ease = t => { const x=Math.max(0,Math.min(1,t)); return x*x*(3-2*x); };

// Preserve the *rendered* stance. No IK, rest-pose legs, or corrective hip motion.
// MotionBricks owns locomotion until it reports a completed standing idle loop.
export class GroundedIdle {
  constructor(vrm) {
    this.vrm = vrm;
    this.elapsed = 0;
    this.rootPosition = vrm.scene.position.clone();
    this.rootQuaternion = vrm.scene.quaternion.clone();
    this.bones = NAMES.map(name => {
      const node = vrm.humanoid.getNormalizedBoneNode(name);
      return node && {name,node,q:node.quaternion.clone(),p:node.position.clone()};
    }).filter(Boolean);
  }
  update(dt) {
    this.elapsed += Math.max(0,Math.min(0.1,Number(dt)||0));
    this.vrm.scene.position.copy(this.rootPosition);
    this.vrm.scene.quaternion.copy(this.rootQuaternion);
    for (const bone of this.bones) {
      bone.node.quaternion.copy(bone.q);
      bone.node.position.copy(bone.p);
    }
    const breath = 0.004*Math.sin(this.elapsed*2*Math.PI/4.2)*ease(this.elapsed/0.45);
    const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),breath);
    for (const bone of this.bones) {
      if(bone.name==='spine'||bone.name==='chest') bone.node.quaternion.multiply(q);
    }
  }
  // Starting a new walk: interpolate joint rotations only. Live root keeps moving.
  blendToLive(weight) {
    const t=ease(weight);
    for(const bone of this.bones) {
      bone.node.quaternion.slerpQuaternions(bone.q,bone.node.quaternion.clone(),t);
      if(bone.name==='hips') bone.node.position.lerpVectors(bone.p,bone.node.position.clone(),t);
    }
  }
}
