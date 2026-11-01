import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {StopFootPlant, solvePlantedFoot} from './stopFootPlant.js';

function mockHumanoid() {
  const root = new THREE.Object3D();
  const hips = new THREE.Object3D();
  root.add(hips);
  const nodes = new Map();
  for (const side of ['left', 'right']) {
    const upper = new THREE.Object3D();
    const lower = new THREE.Object3D();
    const foot = new THREE.Object3D();
    upper.position.set(side === 'left' ? 0.1 : -0.1, -0.15, 0);
    lower.position.set(0, -0.4, 0);
    foot.position.set(0, -0.4, 0);
    hips.add(upper); upper.add(lower); lower.add(foot);
    nodes.set(side + 'UpperLeg', upper);
    nodes.set(side + 'LowerLeg', lower);
    nodes.set(side + 'Foot', foot);
  }
  return {root, hips, nodes, human:{getNormalizedBoneNode: name => nodes.get(name)}};
}

test('planted feet remain in world space across an idle-stance baseline change', () => {
  const {hips, nodes, human} = mockHumanoid();
  const lock = new StopFootPlant(human);
  const left = nodes.get('leftFoot');
  left.updateWorldMatrix(true, false);
  const target = left.getWorldPosition(new THREE.Vector3());
  hips.position.x += 0.025;
  // Simulate an official idle stance changing the left thigh rotation.
  nodes.get('leftUpperLeg').rotation.z += 0.12;
  lock.update(1 / 60);
  left.updateWorldMatrix(true, false);
  assert.ok(left.getWorldPosition(new THREE.Vector3()).distanceTo(target) < 0.004);
});

test('foot solver preserves ankle world orientation', () => {
  const {hips, nodes} = mockHumanoid();
  const upper = nodes.get('rightUpperLeg');
  const lower = nodes.get('rightLowerLeg');
  const foot = nodes.get('rightFoot');
  foot.rotation.y = 0.4;
  foot.updateWorldMatrix(true, false);
  const rotation = foot.getWorldQuaternion(new THREE.Quaternion());
  const target = foot.getWorldPosition(new THREE.Vector3());
  target.x -= 0.018;
  solvePlantedFoot([upper, lower, foot], target);
  foot.updateWorldMatrix(true, false);
  assert.ok(foot.getWorldQuaternion(new THREE.Quaternion()).angleTo(rotation) < 1e-5);
  assert.ok(foot.getWorldPosition(new THREE.Vector3()).distanceTo(target) < 0.004);
});
