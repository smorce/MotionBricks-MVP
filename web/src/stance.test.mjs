import assert from 'node:assert/strict';
import * as THREE from 'three';
import {
  abductUpperArms,
  adductUpperLegs,
  clampLegAdductDeg,
  curlFinger,
  FINGER_JOINTS,
  pointFeetForward,
  poseFingers,
  poseStance,
  stanceData,
  stanceFromSaved,
  rollAnkles,
} from './stance.js';

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
  finger_curl_deg: 0,
  ankle_roll_deg: 0,
});
assert.deepEqual(stanceData({legDeg: 99, armDeg: -3, toeDeg: 50, fingerDeg: 80, ankleDeg: -40}), {
  leg_adduct_deg: 24,
  arm_abduct_deg: 0,
  toe_forward_deg: 40,
  finger_curl_deg: 45,
  ankle_roll_deg: -15,
});
assert.equal(stanceData({fingerDeg: 12.24, ankleDeg: 8.26}).finger_curl_deg, 12.2);
assert.equal(stanceData({fingerDeg: 12.24, ankleDeg: 8.26}).ankle_roll_deg, 8.3);
assert.deepEqual(stanceFromSaved({}), {
  leg_adduct_deg: 11,
  arm_abduct_deg: 8,
  toe_forward_deg: 12.5,
  finger_curl_deg: 9.5,
  ankle_roll_deg: 12,
});
assert.equal(stanceFromSaved({leg_adduct_deg: 0}).leg_adduct_deg, 0);
assert.equal(stanceFromSaved({leg_adduct_deg: 0}).finger_curl_deg, 9.5);

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

const deg = THREE.MathUtils.degToRad;
const leftCurl = new THREE.Quaternion();
const rightCurl = new THREE.Quaternion();
curlFinger(leftCurl, 'left', deg(30));
curlFinger(rightCurl, 'right', deg(30));
const leftTip = new THREE.Vector3(1, 0, 0).applyQuaternion(leftCurl);
const rightTip = new THREE.Vector3(-1, 0, 0).applyQuaternion(rightCurl);
assert.ok(leftTip.y < -0.4 && leftTip.x > 0.8, 'left fingers curl toward the palm');
assert.ok(rightTip.y < -0.4 && rightTip.x < -0.8, 'right fingers curl toward the palm');
assert.ok(Math.abs(leftTip.z) < 0.02 && Math.abs(rightTip.z) < 0.02, 'curl stays in the palm plane');

const leftRoll = new THREE.Quaternion();
const rightRoll = new THREE.Quaternion();
rollAnkles(leftRoll, rightRoll, deg(20));
const leftSole = new THREE.Vector3(0, -1, 0).applyQuaternion(leftRoll);
const rightSole = new THREE.Vector3(0, -1, 0).applyQuaternion(rightRoll);
const leftHeading = new THREE.Vector3(0, 0, 1).applyQuaternion(leftRoll);
const rightHeading = new THREE.Vector3(0, 0, 1).applyQuaternion(rightRoll);
assert.ok(leftSole.x > 0.3, 'left sole tilts outward');
assert.ok(rightSole.x < -0.3, 'right sole tilts outward');
assert.ok(Math.abs(leftHeading.x) < 1e-6 && Math.abs(rightHeading.x) < 1e-6, 'roll leaves the toe heading');
assert.ok(leftHeading.z > 0.99 && rightHeading.z > 0.99, 'toes keep pointing ahead');

const limbNames = ['leftUpperLeg', 'rightUpperLeg', 'leftUpperArm', 'rightUpperArm', 'leftFoot', 'rightFoot'];
const nodes = {};
for (const name of limbNames) {
  nodes[name] = {quaternion: new THREE.Quaternion().setFromEuler(new THREE.Euler(0.2, -0.1, 0.05))};
}
for (const [leftName, rightName] of FINGER_JOINTS) {
  nodes[leftName] = {quaternion: new THREE.Quaternion()};
  nodes[rightName] = {quaternion: new THREE.Quaternion()};
}
const originals = Object.fromEntries(limbNames.map((name) => [name, nodes[name].quaternion.clone()]));
const posed = stanceData({legDeg: 8, armDeg: 6, toeDeg: 10, fingerDeg: 20, ankleDeg: -6});
const getNode = (name) => nodes[name];
poseStance(getNode, posed, 1);
assert.ok(nodes.leftIndexProximal.quaternion.angleTo(new THREE.Quaternion()) > 0.05, 'finger curl leaves the rest pose');
const curled = nodes.leftIndexProximal.quaternion.clone();
poseFingers(getNode, 20, {replaceUnmapped: true});
assert.ok(nodes.leftIndexProximal.quaternion.angleTo(curled) < 1e-5, 'repeating the curl does not stack');
assert.ok(nodes.leftFoot.quaternion.angleTo(originals.leftFoot) > 0.05, 'ankle roll reaches the foot');
poseStance(getNode, posed, -1);
for (const name of limbNames) {
  assert.ok(nodes[name].quaternion.angleTo(originals[name]) < 1e-5, `${name} returns after undo`);
}
assert.ok(nodes.leftIndexProximal.quaternion.angleTo(new THREE.Quaternion()) < 1e-5, 'finger curl undo returns to rest');
