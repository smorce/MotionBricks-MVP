import test from 'node:test';
import assert from 'node:assert/strict';
import {validateVrmSamples} from './collectValidation.js';
const sample=(left, right)=>({left:{foot:left,toe:[left[0]+.1,left[1],left[2]],hip:[0,1,.1],knee:[.1,.5,.1]},right:{foot:right,toe:[right[0]+.1,right[1],right[2]],hip:[0,1,-.1],knee:[.1,.5,-.1]},root:[0,1,0]});
const baseline=sample([-.4,0,.1],[0,0,-.1]);
test('小さいフレーム移動でも累積ルート移動を拒否する',()=>{
  const samples=Array.from({length:41},(_,i)=>({...sample([-.4+.4*Math.min(i/35,1),Math.sin(Math.PI*Math.min(i/35,1))*.08,.1],[0,0,-.1]),root:[i*.005,1,0]}));
  const result=validateVrmSamples(samples,baseline,'left');
  assert.equal(result.accepted,false);
  assert.equal(result.root_displacement_m,.2);
  assert.match(result.reason,/root excursion/);
});
test('VRM上の支持足滑りを拒否する',()=>{
  const samples=[baseline,sample([-.2,.08,.1],[.04,0,-.1]),sample([0,0,.1],[0,0,-.1])];
  const result=validateVrmSamples(samples,baseline,'left');
  assert.equal(result.accepted,false);
  assert.match(result.reason,/slip/);
});
test('VRM上で足を持ち上げない収束を拒否する',()=>{
  const result=validateVrmSamples([baseline,sample([-.2,0,.1],[0,0,-.1]),sample([0,0,.1],[0,0,-.1])],baseline,'left');
  assert.equal(result.accepted,false);
  assert.match(result.reason,/lift/);
});

test('自然な踏み直しはVRM検証に合格する',()=>{
  const samples=Array.from({length:41},(_,i)=>{
    const t=Math.min(i/35,1);
    return sample([-.4+.4*t,Math.sin(Math.PI*t)*.08,.1],[0,0,-.1]);
  });
  const result=validateVrmSamples(samples,baseline,'left');
  assert.equal(result.accepted,true,result.reason);
});

test('事前検証の例外時も表示姿勢を復元する',async()=>{
  const {preflightCollect}=await import('./collectValidation.js');
  let restored=false;
  assert.throws(()=>preflightCollect([1],{capture:()=>42,restore:value=>{assert.equal(value,42);restored=true;},sample:()=>baseline,apply:()=>{throw new Error('conversion failed');}},'left'));
  assert.equal(restored,true);
});
