import * as THREE from 'three';

const LEG_BONES=['leftUpperLeg','leftLowerLeg','leftFoot','leftToes',
  'rightUpperLeg','rightLowerLeg','rightFoot','rightToes'];
const FEET=['leftFoot','rightFoot'];
const MAX_SNAPSHOT_AGE_MS=800;
const MAX_ROOT_DRIFT_M=0.12;

/**
 * Remember the last displayed locomotion leg pose BEFORE the idle clip takes
 * control. A pre-idle leg snapshot is the only way to avoid preserving the
 * already-expanded idle pose.
 *
 * We prefer the first low-speed, double-supported sample during stopping.
 * This is a stance filter, NOT foot IK; it cannot pull a planted foot along.
 */
export class StopStanceHistory {
  constructor(){
    this.latest=null;
    this.supported=null;
    this.previousFeet=null;
  }

  sample(vrm,{speed=Infinity, time=performance.now(), dt=1/60}={}){
    const humanoid=vrm.humanoid;
    const bones=new Map();
    for(const name of LEG_BONES){
      const node=humanoid.getNormalizedBoneNode(name);
      if(node) bones.set(name,node.quaternion.clone());
    }
    if(!bones.has('leftUpperLeg')||!bones.has('rightUpperLeg')) return;
    vrm.scene.updateMatrixWorld(true);
    const feet=FEET.map(name=>{
      const node=humanoid.getNormalizedBoneNode(name);
      return node?.getWorldPosition(new THREE.Vector3())??null;
    });
    const sample={
      time,bones,
      root:vrm.scene.position.clone(),
      feet:feet.map(p=>p?.clone()??null),
    };
    this.latest=sample;

    if(!feet[0]||!feet[1])return;
    // A double-support event is safer than freezing a swing leg.
    const level=Math.abs(feet[0].y-feet[1].y)<=0.035;
    const sampleDt=Math.max(0.001,Number(dt)||1/60);
    const stable=this.previousFeet!=null && feet.every((foot,i)=>
      foot.distanceTo(this.previousFeet[i])/sampleDt <=0.22);
    this.previousFeet=feet.map(foot=>foot.clone());
    if(!this.supported && Number.isFinite(speed) && speed<=0.25 && level && stable)
      this.supported=sample;
  }

  select(time=performance.now()){
    if(!this.latest)return null;
    const candidate=this.supported;
    if(!candidate)return this.latest;
    if(time-candidate.time>MAX_SNAPSHOT_AGE_MS)return this.latest;
    if(candidate.root.distanceTo(this.latest.root)>MAX_ROOT_DRIFT_M)return this.latest;
    return candidate;
  }
}
