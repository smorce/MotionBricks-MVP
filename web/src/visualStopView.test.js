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
test('新実験の未一致生成を評価済みと表示しない',()=>{
 const text=formatVisualStop({stop_mode:'prepared',phase:'settled',visual_selection:{status:'experimental',action:'stop',candidate:{id:'A-0.500'},reference_distance_m:.5,target_pose_distance_m:.59}});
 assert.match(text,/未評価のA方式/);assert.match(text,/目視評価待ち/);
});
test('失敗後の待機移行を到着成功と表示しない',()=>{
 const base={stop_mode:'prepared',visual_selection:{status:'experimental',action:'stop',candidate:{id:'A-0.300'}}};
 assert.match(formatVisualStop({...base,phase:'stop_relaxing'}),/ゆっくり移行中/);
 const text=formatVisualStop({...base,phase:'stop_relaxed'});
 assert.match(text,/停止生成は失敗/);assert.doesNotMatch(text,/停止済み・接地後/);
});
test('採用ガードと診断の警告を分けて表示する',()=>{
 const text=formatVisualStop({stop_mode:'prepared',phase:'settled',visual_selection:{status:'experimental',candidate:{id:'A'}},gait:{final_stop_metrics:{policy:'prepared-minimum-guards-v1',accepted:true,warnings:['progress','swing']}}});
 assert.match(text,/通過（自然さは未評価）/);assert.match(text,/前進量・通過・遊脚・着地/);
});
