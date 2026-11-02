import * as THREE from 'three';
export const MAP = {
  Hips:'hips', Spine1:'spine', Chest:'chest',
  Neck2:'neck', Head:'head', LeftEye:'leftEye', RightEye:'rightEye',
  LeftShoulder:'leftShoulder', LeftArm:'leftUpperArm', LeftForeArm:'leftLowerArm', LeftHand:'leftHand',
  LeftHandThumbEnd:'leftThumbDistal', LeftHandMiddleEnd:'leftMiddleDistal',
  RightShoulder:'rightShoulder', RightArm:'rightUpperArm', RightForeArm:'rightLowerArm', RightHand:'rightHand',
  RightHandThumbEnd:'rightThumbDistal', RightHandMiddleEnd:'rightMiddleDistal',
  LeftLeg:'leftUpperLeg', LeftShin:'leftLowerLeg', LeftFoot:'leftFoot', LeftToeBase:'leftToes',
  RightLeg:'rightUpperLeg', RightShin:'rightLowerLeg', RightFoot:'rightFoot', RightToeBase:'rightToes',
};
// World basis conversion: NVIDIA demos Z-up => Three.js Y-up.
export const basis=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),-Math.PI/2);
export const basisInv=basis.clone().invert();
export const q=(arr)=>new THREE.Quaternion(arr[3],arr[4],arr[5],arr[6]);
export function toThreeWorldQuat(v){return basis.clone().multiply(v).multiply(basisInv)}
export function calcWorldQuats(pose,parents){
  const out=[];
  for(let i=0;i<pose.length;i++){
    const local=q(pose[i]);
    out.push(parents[i] < 0 ? local : out[parents[i]].clone().multiply(local));
  }
  return out;
}

export function applySomaRotations(vrm, rig, pose, restSourceWorld, restDestWorld){
  const world=calcWorldQuats(pose,rig.parents);
  const used=new Set();
  for(let i=0;i<world.length;i++){
    const bone=MAP[rig.joint_names[i]];
    if(!bone||used.has(bone)||!restDestWorld.has(bone))continue;
    used.add(bone);
    const node=vrm.humanoid.getNormalizedBoneNode(bone);
    if(!node)continue;
    const delta=world[i].clone().multiply(restSourceWorld[i].clone().invert());
    const desired=toThreeWorldQuat(delta).multiply(restDestWorld.get(bone));
    const parentWorld=node.parent.getWorldQuaternion(new THREE.Quaternion());
    node.quaternion.copy(parentWorld.invert().multiply(desired));
    node.updateMatrixWorld(true);
  }
}
