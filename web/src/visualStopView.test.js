import test from 'node:test';
import assert from 'node:assert/strict';
import {formatVisualStop} from './visualStopView.js';
test('未確認状態を自然とは表示しない',()=>{
 assert.match(formatVisualStop({stop_mode:'visual',visual_selection:{status:'unknown'}}),/未確認/);
});
test('候補とXを表示し新しい生成は評価待ちにする',()=>{
 const text=formatVisualStop({stop_mode:'visual',visual_selection:{status:'matched',candidate:{id:'A-0.500'},x_m:.5,similarity:.8,action:'stop'}});
 assert.match(text,/A-0.500/);assert.match(text,/50cm/);assert.match(text,/評価待ち/);
});
test('従来方式にX未確認を付けない',()=>{
 assert.equal(formatVisualStop({stop_mode:'legacy'}),'実行方式：従来の停止制御');
});
