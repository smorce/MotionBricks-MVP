/** VRM変換・脚補正後のワールド座標を、画面に出す前に検証する。 */
const delta=(a,b)=>a.map((v,i)=>v-b[i]);
const dot=(a,b)=>a.reduce((sum,v,i)=>sum+v*b[i],0);
const length=a=>Math.hypot(...a);
const horizontal=(a,b)=>Math.hypot(a[0]-b[0],a[2]-b[2]);
function bend(leg){
  const axis=delta(leg.foot,leg.hip), knee=delta(leg.knee,leg.hip);
  const scale=dot(knee,axis)/dot(axis,axis);
  return knee.map((v,i)=>v-scale*axis[i]);
}
export function validateVrmSamples(samples, baseline, swing, {slipLimit=.02,minLift=.025}={}){
  const result={accepted:false,reason:'Invalid VRM samples',support_slip_m:0,lift_m:0};
  if(!['left','right'].includes(swing)||samples.length<3) return result;
  const valid=s=>['root'].every(k=>s[k]?.length===3&&s[k].every(Number.isFinite))&&['left','right'].every(side=>['hip','knee','foot','toe'].every(k=>s[side]?.[k]?.length===3&&s[side][k].every(Number.isFinite)));
  if(!valid(baseline)||!samples.every(valid)) return result;
  const support=swing==='left'?'right':'left';
  result.support_slip_m=Math.max(...samples.flatMap(s=>['foot','toe'].map(k=>horizontal(s[support][k],baseline[support][k]))));
  result.lift_m=Math.max(...samples.map(s=>Math.min(...['foot','toe'].map(k=>s[swing][k][1]-baseline[swing][k][1]))));
  const end=samples.at(-1);
  result.root_displacement_m=horizontal(end.root,baseline.root);
  result.root_excursion_m=Math.max(...samples.map(s=>horizontal(s.root,baseline.root)));
  result.root_path_m=samples.reduce((sum,s,i)=>sum+horizontal(s.root,i?samples[i-1].root:baseline.root),0);
  const reject=reason=>({...result,reason});
  if(result.root_excursion_m>.08) return reject('VRM root excursion exceeds limit');
  if(result.support_slip_m>slipLimit) return reject('VRM support foot slip exceeds limit');
  if(result.lift_m<minLift) return reject('VRM swing foot did not lift');
  if(['foot','toe'].some(k=>Math.abs(end[swing][k][1]-baseline[swing][k][1])>.04)) return reject('VRM swing foot did not land');
  if(samples.some(s=>['left','right'].some(side=>['foot','toe'].some(k=>s[side][k][1]<baseline[side][k][1]-.02)))) return reject('VRM foot penetrated ground');
  if(horizontal(end.left.foot,end.right.foot)>=horizontal(baseline.left.foot,baseline.right.foot)-.005) return reject('VRM stance did not improve');
  for(let i=0;i<samples.length;i++){
    const s=samples[i],previous=i?samples[i-1]:baseline;
    if(length(delta(s.root,previous.root))>.04) return reject('VRM root discontinuity');
    for(const side of ['left','right']){
      const leg=s[side], original=baseline[side];
      const upper=delta(leg.knee,leg.hip),lower=delta(leg.foot,leg.knee);
      if(length(upper)*length(lower)<1e-8||dot(upper,lower)/(length(upper)*length(lower))<-.5) return reject('VRM invalid knee bend');
      const a=bend(original),b=bend(leg);
      if(length(a)>.01&&length(b)>.01&&dot(a,b)<0) return reject('VRM knee bend reversed');
      if(i>=samples.length-3&&['foot','toe'].some(k=>length(delta(leg[k],previous[side][k]))>.01)) return reject('VRM final feet are unstable');
    }
  }
  return {...result,accepted:true,reason:''};
}

export function preflightCollect(frames, {capture,restore,apply,sample}, swing){
  const held=capture();
  try{
    const baseline=sample();
    const samples=frames.map(frame=>{apply(frame);return sample();});
    return validateVrmSamples(samples,baseline,swing);
  }finally{
    restore(held);
  }
}
