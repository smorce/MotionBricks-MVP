import assert from 'node:assert/strict';
import * as THREE from 'three';
import {abductUpperArms, adductUpperLegs, clampLegAdductDeg, pointFeetForward, stanceData} from './stance.js';

const spread = new THREE.Vector3(0.07, -0.76, 0.05);
const left = new THREE.Quaternion();
const right = new THREE.Quaternion();
adductUpperLegs(left, right, THREE.MathUtils.degToRad(3.5));

const leftFoot = spread.clone().applyQuaternion(left);
const rightFoot = new THREE.Vector3(-spread.x, spread.y, spread.z).applyQuaternion(right);
assert.ok(leftFoot.x < spread.x, 'left foot moves inward');
assert.ok(rightFoot.x > -spread.x, 'right foot moves inward');
assert.ok(leftFoot.x > 0, 'left foot stays on the left side');
assert.ok(Math.abs(leftFoot.z - spread.z) < 0.01, 'forward axis is unchanged');

const identity = new THREE.Quaternion();
const untouched = identity.clone();
adductUpperLegs(identity, identity, 0);
assert.ok(identity.angleTo(untouched) < 1e-8, 'zero adduction leaves the pose');

assert.equal(clampLegAdductDeg('nope'), 0);
assert.equal(clampLegAdductDeg(-4), 0);
assert.equal(clampLegAdductDeg(30), 24);
assert.equal(clampLegAdductDeg(8.25), 8.25);
assert.deepEqual(stanceData({legDeg: 8.24}), {
  leg_adduct_deg: 8.2,
  arm_abduct_deg: 0,
  toe_forward_deg: 0,
});
assert.deepEqual(stanceData({legDeg: 99, armDeg: -3, toeDeg: 50}), {
  leg_adduct_deg: 24,
  arm_abduct_deg: 0,
  toe_forward_deg: 40,
});

const hanging = new THREE.Vector3(0.02, -0.55, 0.08);
const leftArm = new THREE.Quaternion();
const rightArm = new THREE.Quaternion();
abductUpperArms(leftArm, rightArm, THREE.MathUtils.degToRad(12));
const leftHand = hanging.clone().applyQuaternion(leftArm);
const rightHand = new THREE.Vector3(-hanging.x, hanging.y, hanging.z).applyQuaternion(rightArm);
assert.ok(leftHand.x > hanging.x, 'left hand moves outward');
assert.ok(rightHand.x < -hanging.x, 'right hand moves outward');

const up = new THREE.Vector3(0, 1, 0);
const leftToeOut = new THREE.Quaternion().setFromAxisAngle(up, THREE.MathUtils.degToRad(18));
const rightToeOut = new THREE.Quaternion().setFromAxisAngle(up, THREE.MathUtils.degToRad(-18));
pointFeetForward(leftToeOut, rightToeOut, THREE.MathUtils.degToRad(18));
const leftToe = new THREE.Vector3(0, 0, 1).applyQuaternion(leftToeOut);
const rightToe = new THREE.Vector3(0, 0, 1).applyQuaternion(rightToeOut);
assert.ok(Math.abs(leftToe.x) < 0.02, 'left toes face forward');
assert.ok(Math.abs(rightToe.x) < 0.02, 'right toes face forward');
assert.ok(leftToe.z > 0.9 && rightToe.z > 0.9, 'toes keep pointing ahead');
