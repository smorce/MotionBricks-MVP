import test from 'node:test';
import assert from 'node:assert/strict';
import {compareFootHeights} from './footHeightDiagnostics.js';

test('Z-upとY-upの床基準を揃え、VRMだけ浮く接地足を測定する', () => {
  const foot = {z: 1.02, toe_z: 1, planted: true};
  const sample = {foot: [0, .12, 0], toe: [0, .1, 0]};
  const metrics = compareFootHeights({left: foot, right: foot}, {left: sample, right: sample}, 1, 0);
  assert.ok(Math.abs(metrics.left.ankle_delta_m - .1) < 1e-10);
  assert.equal(metrics.left.toe_delta_m, .1);
  assert.equal(metrics.left.planted, true);
});

 test('SOMA world floor remains fixed while foot heights change', () => {
  const foot = {z: .109, toe_z: .021, planted: false};
  const sample = {foot: [0, .203, 0], toe: [0, .060, 0]};
  const metrics = compareFootHeights({left: foot, right: foot}, {left: sample, right: sample}, 0, 0);
  assert.equal(metrics.left.soma_height_m.toe, .021);
  assert.ok(Math.abs(metrics.left.toe_delta_m - .039) < 1e-10);
});
