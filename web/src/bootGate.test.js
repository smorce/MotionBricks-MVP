import test from 'node:test';
import assert from 'node:assert/strict';
import {isSceneBootReady, spawnOffset} from './bootGate.js';

test('boot stays closed until every dependency is ready', () => {
  const base = {
    spawn: {x: 1, z: 2},
    hasVrm: true,
    hasRig: true,
    hasPose: true,
    hasRetarget: true,
  };
  assert.equal(isSceneBootReady(base), true);
  assert.equal(isSceneBootReady({...base, spawn: null}), false);
  assert.equal(isSceneBootReady({...base, spawn: {x: NaN, z: 2}}), false);
  assert.equal(isSceneBootReady({...base, hasVrm: false}), false);
  assert.equal(isSceneBootReady({...base, hasRig: false}), false);
  assert.equal(isSceneBootReady({...base, hasPose: false}), false);
  assert.equal(isSceneBootReady({...base, hasRetarget: false}), false);
});

test('spawnOffset refuses a zero fallback when spawn is missing', () => {
  assert.equal(spawnOffset(null), null);
  assert.equal(spawnOffset(undefined), null);
  assert.equal(spawnOffset({x: 0, z: NaN}), null);
  assert.deepEqual(spawnOffset({x: 0, z: 0}), {x: 0, z: 0});
  assert.deepEqual(spawnOffset({x: 3.5, z: -1}), {x: 3.5, z: -1});
});
