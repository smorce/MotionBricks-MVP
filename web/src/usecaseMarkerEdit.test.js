import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyMarkerOverrides,
  formatMarkerOverridesJson,
  formatMarkerReadout,
  markerOverrides,
  moveUsecaseMarker,
  roundCoord,
} from './usecaseMarkerEdit.js';

test('roundCoord keeps two decimal places', () => {
  assert.equal(roundCoord(1.234), 1.23);
  assert.equal(roundCoord(-8.609), -8.61);
});

test('moveUsecaseMarker updates x/z on the usecase', () => {
  const usecase = {id: 'counter-order', title: 'カウンターで注文', x: -8.6, z: -9.4};
  assert.deepEqual(moveUsecaseMarker(usecase, -8.55, -9.12), {x: -8.55, z: -9.12});
  assert.equal(usecase.x, -8.55);
  assert.equal(usecase.z, -9.12);
});

test('markerOverrides skips marker:false and incomplete rows', () => {
  const cases = [
    {id: 'a', x: 1, z: 2},
    {id: 'b', marker: false, x: 3, z: 4},
    {id: 'c', x: Number.NaN, z: 1},
  ];
  assert.deepEqual(markerOverrides(cases), {a: {x: 1, z: 2}});
});

test('applyMarkerOverrides mutates matching cases', () => {
  const cases = [
    {id: 'a', x: 1, z: 2},
    {id: 'b', x: 3, z: 4},
  ];
  applyMarkerOverrides(cases, {a: {x: 9.1, z: -2.25}, missing: {x: 0, z: 0}});
  assert.deepEqual(cases[0], {id: 'a', x: 9.1, z: -2.25});
  assert.deepEqual(cases[1], {id: 'b', x: 3, z: 4});
});

test('format helpers expose copyable JSON and a short readout', () => {
  const cases = [{id: 'a', title: '席A', x: 1.2, z: -3.4}];
  assert.equal(formatMarkerOverridesJson(cases), '{\n  "a": {\n    "x": 1.2,\n    "z": -3.4\n  }\n}');
  assert.equal(formatMarkerReadout(cases[0]), '席A: x=1.20, z=-3.40');
  assert.equal(formatMarkerReadout(null), 'リングをドラッグして位置を調整');
});
