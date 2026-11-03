import test from 'node:test';
import assert from 'node:assert/strict';
import {PlaybackBuffer} from './playbackBuffer.js';
test('古い初期スナップショットの直後に届く現在時刻へ基準を合わせる',()=>{
 const b=new PlaybackBuffer(100);
 b.push({sequence:1,simulation_time:0,poses:[1]},1000);
 b.push({sequence:301,simulation_time:5,poses:[301]},1010);
 assert.equal(b.sample(1110).b.sequence,301);
 assert.equal(b.sample(1110).blend,1);
});
test('遅延時は最後の検証済み姿勢を保持し、古い連番を捨てる',()=>{
 const b=new PlaybackBuffer(100);
 assert.equal(b.push({sequence:1,simulation_time:0,poses:[1]},0),true);
 b.push({sequence:2,simulation_time:.1,poses:[2]},100);
 assert.equal(b.sample(150).blend,.5);
 assert.equal(b.sample(500).b.poses[0],2);
 assert.equal(b.push({sequence:1,simulation_time:0,poses:[0]},510),false);
});

test('欠損後は保持した時刻から再開する',()=>{
 const b=new PlaybackBuffer(100);
 b.push({sequence:1,simulation_time:0,poses:[1]},0);
 b.push({sequence:2,simulation_time:.1,poses:[2]},100);
 b.sample(500);
 b.push({sequence:3,simulation_time:.2,poses:[3]},600);
 assert.equal(b.sample(600).a.poses[0],2);
 assert.equal(b.sample(600).blend,0);
 assert.ok(b.sample(650).blend<1);
 assert.equal(b.sample(700).b.poses[0],3);
});

test('再クリック後は新しい要求のフレームが届くまで旧区間を受け取らない',()=>{
 const b=new PlaybackBuffer();
 b.push({sequence:1,simulation_time:0,gait:{move_id:2}},0);
 b.beginMove(2);
 assert.equal(b.sample(20),null);
 assert.equal(b.push({sequence:2,simulation_time:.02,gait:{move_id:2}},30),false);
 assert.equal(b.push({sequence:3,simulation_time:.03,gait:{move_id:3}},40),true);
});
