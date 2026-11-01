import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {GroundedIdle} from './groundedIdle.js';

function avatar(){
  const scene=new THREE.Object3D();
  const hips=new THREE.Object3D();scene.add(hips);
  const spine=new THREE.Object3D();hips.add(spine);
  const chest=new THREE.Object3D();spine.add(chest);
  const leftUpperLeg=new THREE.Object3D();hips.add(leftUpperLeg);
  const leftLowerLeg=new THREE.Object3D();leftUpperLeg.add(leftLowerLeg);
  const leftFoot=new THREE.Object3D();leftLowerLeg.add(leftFoot);
  const rightUpperLeg=new THREE.Object3D();hips.add(rightUpperLeg);
  const rightLowerLeg=new THREE.Object3D();rightUpperLeg.add(rightLowerLeg);
  const rightFoot=new THREE.Object3D();rightLowerLeg.add(rightFoot);
  const nodes={hips,spine,chest,leftUpperLeg,leftLowerLeg,leftFoot,rightUpperLeg,rightLowerLeg,rightFoot};
  leftUpperLeg.rotation.z=0.165806; // ~9.5 degrees
  return {scene,humanoid:{getNormalizedBoneNode:n=>nodes[n]||null},nodes};
}

test('idle preserves both legs including full walking-slider rotation',()=>{
  const vrm=avatar();
  const baseline=vrm.nodes.leftUpperLeg.quaternion.clone();
  const idle=new GroundedIdle(vrm);
  for(let i=0;i<300;i++)idle.update(1/60);
  assert.ok(vrm.nodes.leftUpperLeg.quaternion.angleTo(baseline)<1e-8);
  assert.ok(vrm.nodes.rightUpperLeg.quaternion.angleTo(new THREE.Quaternion())<1e-8);
  assert.equal(vrm.scene.position.length(),0);
  assert.ok(vrm.nodes.chest.quaternion.angleTo(new THREE.Quaternion())<0.005);
});

test('switching back to walking blends leg rotations without a snap',()=>{
  const vrm=avatar();
  const idle=new GroundedIdle(vrm);
  const before=vrm.nodes.leftUpperLeg.quaternion.clone();
  vrm.nodes.leftUpperLeg.quaternion.identity();
  idle.blendToLive(0);
  assert.ok(vrm.nodes.leftUpperLeg.quaternion.angleTo(before)<1e-8);
  vrm.nodes.leftUpperLeg.quaternion.identity();
  idle.blendToLive(1);
  assert.ok(vrm.nodes.leftUpperLeg.quaternion.angleTo(new THREE.Quaternion())<1e-8);
});
