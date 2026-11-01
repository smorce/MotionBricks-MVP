import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {SettledIdle} from './settledIdle.js';

test('breathing does not accumulate or move the pelvis', () => {
  const nodes = new Map(['hips', 'spine', 'chest'].map(name => [name, new THREE.Object3D()]));
  const idle = new SettledIdle({getNormalizedBoneNode:name => nodes.get(name)});
  for (let i=0;i<180;i++) idle.update(1/60);
  assert.ok(nodes.get('chest').quaternion.angleTo(new THREE.Quaternion()) > 0.001);
  assert.ok(nodes.get('chest').quaternion.angleTo(new THREE.Quaternion()) < 0.007);
  assert.equal(nodes.get('hips').position.length(), 0);
  assert.equal(nodes.get('hips').quaternion.angleTo(new THREE.Quaternion()), 0);
});
