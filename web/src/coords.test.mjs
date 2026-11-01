import assert from 'node:assert/strict';
import {threePointToRuntime} from './coords.js';

assert.deepEqual(threePointToRuntime(1.5, 2), {x: 1.5, y: -2});
assert.deepEqual(threePointToRuntime(0, 0), {x: 0, y: -0});
