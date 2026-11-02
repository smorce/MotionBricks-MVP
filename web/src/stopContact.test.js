import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyOwner, reduceOwner} from './poseOwner.js';

test('未接地の停止フレームをGroundedIdleへ渡さない', () => {
  const owner = reduceOwner(emptyOwner(), {
    phase: 'settled', moveId: 1, settleSeq: 1, bothPlanted: false,
  });
  assert.equal(owner.mode, 'live');
  assert.equal(owner.capture, false);
});

test('接地情報が欠落した停止フレームを保存しない', () => {
  assert.equal(reduceOwner(emptyOwner(), {phase: 'settled'}).capture, false);
});
