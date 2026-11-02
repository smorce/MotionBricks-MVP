import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyOwner, reduceOwner, shouldApplyStance} from './poseOwner.js';
import {markerColor} from './gaitView.js';
import {runtimeJointToThree, threeJointToRuntime} from './coords.js';

test('settled stance is kept when a later frame only changes speed', () => {
  let owner = reduceOwner(emptyOwner(), {phase: 'moving', moveId: 4, settleSeq: 0});
  owner = reduceOwner(owner, {phase: 'settled', moveId: 4, settleSeq: 2, actualSpeed: 0});
  assert.equal(owner.mode, 'settled');
  assert.equal(owner.capture, true);
  owner = {...owner, capture: false};
  owner = reduceOwner(owner, {phase: 'settled', moveId: 4, settleSeq: 2, actualSpeed: 1.8});
  assert.equal(owner.mode, 'settled');
  assert.equal(owner.capture, false);
  assert.equal(shouldApplyStance(owner), false);
});

test('a delayed settle from the previous move does not replace the new walk', () => {
  let owner = reduceOwner(emptyOwner(), {phase: 'settled', moveId: 3, settleSeq: 1});
  owner = reduceOwner(owner, {phase: 'moving', moveId: 4, settleSeq: 1});
  assert.equal(owner.mode, 'live');
  assert.equal(owner.blend, true);
  const stale = reduceOwner(owner, {phase: 'settled', moveId: 3, settleSeq: 1});
  assert.equal(stale.mode, 'live');
  assert.equal(stale.seenMove, 4);
});

test('walking still receives the stance slider exactly once per live frame', () => {
  const owner = reduceOwner(emptyOwner(), {phase: 'final_step', moveId: 1, settleSeq: 0});
  assert.equal(shouldApplyStance(owner), true);
  assert.equal(markerColor(true), 0x3ddc84);
  assert.equal(markerColor(false), 0xff4d4d);
});

test('runtime foot positions round-trip through the same root correction', () => {
  const rest = {x: 0.1, y: -0.2, z: 0.9};
  const spawn = {x: 1, z: 3};
  const point = {x: 0.4, y: 0.2, z: 0.02};
  const three = runtimeJointToThree(point, rest, spawn, 0.05);
  const back = threeJointToRuntime(three, rest, spawn, 0.05);
  assert.ok(Math.abs(back.x - point.x) < 1e-9);
  assert.ok(Math.abs(back.y - point.y) < 1e-9);
  assert.ok(Math.abs(back.z - point.z) < 1e-9);
});
