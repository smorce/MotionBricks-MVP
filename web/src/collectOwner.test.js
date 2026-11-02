import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyOwner, reduceOwner} from './poseOwner.js';
test('生成準備では停止姿勢を保持する', () => {
  const held=reduceOwner(emptyOwner(), {phase:'settled', bothPlanted:true,moveId:1,settleSeq:2});
  const prepared=reduceOwner({...held,capture:false}, {phase:'collect_preparing',moveId:1,settleSeq:2});
  assert.equal(prepared.mode,'collect_preparing');
  assert.equal(prepared.capture,false);
  assert.equal(prepared.blend,false);
});
test('古い収束フレームを無視する', () => {
  const owner={...emptyOwner(),seenMove:4,moveId:4};
  assert.equal(reduceOwner(owner,{phase:'collecting',moveId:3,settleSeq:2}),owner);
});
