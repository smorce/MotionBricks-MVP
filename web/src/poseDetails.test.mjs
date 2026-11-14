import assert from 'node:assert/strict';
import * as THREE from 'three';
import {PoseDetailAdjuster, detailData} from './poseDetails.js';

assert.deepEqual(detailData({fingerDeg: 90, ankleDeg: -90}), {finger_curl_deg:40, ankle_roll_deg:-15});
assert.deepEqual(detailData({fingerDeg:'wrong', ankleDeg:'wrong'}), {finger_curl_deg:0, ankle_roll_deg:0});
const bones = new Map();
for (const side of ['left', 'right']) {
  for (const name of ['Foot','IndexProximal','IndexIntermediate','IndexDistal','ThumbProximal']) {
    bones.set(`${side}${name}`, {quaternion:new THREE.Quaternion()});
  }
}
const vrm={humanoid:{getNormalizedBoneNode:name=>bones.get(name)}};
const adjuster=new PoseDetailAdjuster();
adjuster.apply(vrm, detailData({fingerDeg:24, ankleDeg:5}));
const left=bones.get('leftIndexProximal').quaternion.clone();
const right=bones.get('rightIndexProximal').quaternion.clone();
assert.ok(left.angleTo(new THREE.Quaternion()) > 0.1);
assert.ok(Math.abs(left.z + right.z) < 1e-8, 'finger curl is mirrored');
assert.ok(Math.abs(bones.get('leftFoot').quaternion.z + bones.get('rightFoot').quaternion.z) < 1e-8);
adjuster.restore();
for (const node of bones.values()) assert.ok(node.quaternion.angleTo(new THREE.Quaternion()) < 1e-8, 'restore is exact');
adjuster.apply(vrm, detailData({fingerDeg:24, ankleDeg:5}));
assert.ok(bones.get('leftIndexProximal').quaternion.angleTo(left) < 1e-8, 'no accumulation on subsequent frame');
adjuster.restore();
adjuster.apply(vrm, detailData({fingerDeg:0, ankleDeg:0}));
assert.equal(adjuster.originals.length, 0, 'zero sliders leave source pose untouched');
