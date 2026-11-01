import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {StopStanceHistory} from './stopStanceHistory.js';
import {GroundedIdle} from './groundedIdle.js';

function avatar(){
 const scene=new THREE.Object3D();
 const hips=new THREE.Object3D();scene.add(hips);
 const nodes={};
 for(const side of ['left','right']){
  const upper=new THREE.Object3D(),lower=new THREE.Object3D(),foot=new THREE.Object3D();
  hips.add(upper);upper.add(lower);lower.add(foot);
  upper.position.set(side==='left'?.1:-.1,-.25,0);
  lower.position.y=-.35;foot.position.y=-.35;
  nodes[side+'UpperLeg']=upper;
  nodes[side+'LowerLeg']=lower;
  nodes[side+'Foot']=foot;
 }
 nodes.hips=hips;
 return {scene,humanoid:{getNormalizedBoneNode:n=>nodes[n]??null},nodes};
}

test('a wide official idle cannot overwrite the captured stopping leg pose',()=>{
 const vrm=avatar(),h=new StopStanceHistory();
 const expected=vrm.nodes.leftUpperLeg.quaternion.clone();
 h.sample(vrm,{speed:0.15,time:10,dt:1/60});
 h.sample(vrm,{speed:0.10,time:26,dt:1/60});
 vrm.nodes.leftUpperLeg.rotation.z=0.6;
 const idle=new GroundedIdle(vrm,h.select(40));
 idle.update(1/60);
 assert.ok(vrm.nodes.leftUpperLeg.quaternion.angleTo(expected)<1e-7);
});

test('stale support snapshots fall back to the most recent pre-idle pose',()=>{
 const vrm=avatar(),h=new StopStanceHistory();
 h.sample(vrm,{speed:0.1,time:0,dt:1/60});
 h.sample(vrm,{speed:0.1,time:20,dt:1/60});
 vrm.nodes.leftUpperLeg.rotation.z=0.24;
 h.sample(vrm,{speed:0.8,time:1000,dt:1/60});
 assert.ok(h.select(1000).bones.get('leftUpperLeg')
    .angleTo(vrm.nodes.leftUpperLeg.quaternion)<1e-7);
});
