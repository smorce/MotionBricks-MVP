import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {GroundedIdle} from './groundedIdle.js';

function avatar(){
  const scene=new THREE.Object3D();
  const hips=new THREE.Object3D(); hips.name='hips'; scene.add(hips);
  const spine=new THREE.Object3D(); spine.name='spine'; hips.add(spine);
  const chest=new THREE.Object3D(); chest.name='chest'; spine.add(chest);
  const leftUpperLeg=new THREE.Object3D(); leftUpperLeg.name='leftUpperLeg'; hips.add(leftUpperLeg);
  const leftLowerLeg=new THREE.Object3D(); leftLowerLeg.name='leftLowerLeg'; leftUpperLeg.add(leftLowerLeg);
  const leftFoot=new THREE.Object3D(); leftFoot.name='leftFoot'; leftLowerLeg.add(leftFoot);
  const rightUpperLeg=new THREE.Object3D(); rightUpperLeg.name='rightUpperLeg'; hips.add(rightUpperLeg);
  const rightLowerLeg=new THREE.Object3D(); rightLowerLeg.name='rightLowerLeg'; rightUpperLeg.add(rightLowerLeg);
  const rightFoot=new THREE.Object3D(); rightFoot.name='rightFoot'; rightLowerLeg.add(rightFoot);
  const nodes={hips,spine,chest,leftUpperLeg,leftLowerLeg,leftFoot,rightUpperLeg,rightLowerLeg,rightFoot};
  leftUpperLeg.rotation.z=0.165806; // ~9.5 degrees
  spine.rotation.x=0.35;
  chest.rotation.x=0.2;
  return {scene,humanoid:{getNormalizedBoneNode:n=>nodes[n]||null},nodes};
}

function idleClipToward(nodes, {spineX=0, chestX=0}={}){
  const spine=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0), spineX);
  const chest=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0), chestX);
  return new THREE.AnimationClip('idle', 1, [
    new THREE.QuaternionKeyframeTrack(`${nodes.spine.name}.quaternion`, [0, 1], [...spine.toArray(), ...spine.toArray()]),
    new THREE.QuaternionKeyframeTrack(`${nodes.chest.name}.quaternion`, [0, 1], [...chest.toArray(), ...chest.toArray()]),
  ]);
}

test('idle preserves both legs including full walking-slider rotation',()=>{
  const vrm=avatar();
  const baseline=vrm.nodes.leftUpperLeg.quaternion.clone();
  const snapChest=vrm.nodes.chest.quaternion.clone();
  const idle=new GroundedIdle(vrm);
  for(let i=0;i<300;i++)idle.update(1/60);
  assert.ok(vrm.nodes.leftUpperLeg.quaternion.angleTo(baseline)<1e-8);
  assert.ok(vrm.nodes.rightUpperLeg.quaternion.angleTo(new THREE.Quaternion())<1e-8);
  assert.equal(vrm.scene.position.length(),0);
  // No idle clip: chest stays on the snapshot aside from small breath.
  assert.ok(vrm.nodes.chest.quaternion.angleTo(snapChest)<0.01);
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

test('a completed idle cannot replace the last displayed walking root and hips',()=>{
  const vrm=avatar();
  vrm.scene.position.set(1.2,0,-0.4);
  vrm.nodes.hips.rotation.y=0.3;
  vrm.nodes.leftUpperLeg.rotation.z=-0.19;
  const expectedRoot=vrm.scene.position.clone();
  const expectedHip=vrm.nodes.hips.quaternion.clone();
  const expectedLeg=vrm.nodes.leftUpperLeg.quaternion.clone();
  const idle=new GroundedIdle(vrm);
  vrm.scene.position.x+=0.3;
  vrm.nodes.hips.rotation.y=1.1;
  vrm.nodes.leftUpperLeg.rotation.z=0.55;
  idle.update(1/60);
  assert.ok(vrm.scene.position.distanceTo(expectedRoot)<1e-9);
  assert.ok(vrm.nodes.hips.quaternion.angleTo(expectedHip)<1e-6);
  assert.ok(vrm.nodes.leftUpperLeg.quaternion.angleTo(expectedLeg)<1e-8);
});

test('upper body eases toward idle without moving feet or exceeding blend max',()=>{
  const vrm=avatar();
  const snapSpine=vrm.nodes.spine.quaternion.clone();
  const snapFoot=vrm.nodes.leftFoot.quaternion.clone();
  const snapHip=vrm.nodes.hips.quaternion.clone();
  const targetSpine=new THREE.Quaternion();
  const clip=idleClipToward(vrm.nodes, {spineX:0, chestX:0});
  const max=0.65;
  const expected=snapSpine.clone().slerp(targetSpine, max);
  const idle=new GroundedIdle(vrm, {idleClip:clip, fadeSeconds:0.8, upperBlendMax:max});
  for(let i=0;i<60;i++) idle.update(1/60);
  assert.ok(vrm.nodes.spine.quaternion.angleTo(snapSpine)>0.05, 'spine should ease toward idle');
  assert.ok(vrm.nodes.spine.quaternion.angleTo(expected)<0.02, 'blend must stop at upperBlendMax');
  assert.ok(vrm.nodes.spine.quaternion.angleTo(targetSpine)>0.05, 'must not reach full idle upright');
  assert.ok(vrm.nodes.leftFoot.quaternion.angleTo(snapFoot)<1e-8);
  assert.ok(vrm.nodes.hips.quaternion.angleTo(snapHip)<1e-8);
});
