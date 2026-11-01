import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {alignIdleLegsToCurrentPose} from './idleHandoff.js';

test('idle legs retain the stopped baseline and relative animation', () => {
  const node = new THREE.Object3D();
  node.name = 'leg';
  node.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), 0.3);
  const start = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -0.2);
  const end = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), -0.1);
  const source = new THREE.AnimationClip('idle', 1, [new THREE.QuaternionKeyframeTrack('leg.quaternion', [0, 1], [...start, ...end])]);
  const clip = source.clone();
  const vrm = {humanoid: {getNormalizedBoneNode: name => name === 'leftUpperLeg' ? node : null}};
  alignIdleLegsToCurrentPose(vrm, clip);
  assert.ok(new THREE.Quaternion().fromArray(clip.tracks[0].values).angleTo(node.quaternion) < 1e-6);
  const expected = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), 0.4);
  assert.ok(new THREE.Quaternion().fromArray(clip.tracks[0].values, 4).angleTo(expected) < 1e-6);
  assert.deepEqual(Array.from(source.tracks[0].values), [...new Float32Array([...start, ...end])]);
});
