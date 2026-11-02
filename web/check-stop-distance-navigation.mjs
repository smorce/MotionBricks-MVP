// 元の目的地に対する実到着を、通常制御のまま検証する。
import {writeFile} from 'node:fs/promises';

const socket=new WebSocket(`ws://127.0.0.1:${process.env.MOTIONBRICKS_TEST_PORT??'8776'}/ws`);
let latest;
let pending;
const cases=[];
socket.onmessage=event=>{
  const row=JSON.parse(event.data);
  if(row.type!=='frame') return;
  latest=row;
  if(!pending) return;
  if(row.gait?.move_id===pending.previousMoveId) return;
  pending.frames++;
  if(!['settled','idle'].includes(row.phase)) pending.started=true;
  if(pending.started && ['settled','stop_failed'].includes(row.phase)) {
    const error=Math.hypot(row.poses[0][0]-pending.goal[0],row.poses[0][1]-pending.goal[1]);
    const result={case:pending.name,phase:row.phase,error_m:error,frames:pending.frames,gait:row.gait};
    cases.push(result);const done=pending.done;clearTimeout(pending.timer);pending=null;done();
  }
};
await new Promise(resolve=>socket.onopen=resolve);
while(!latest) await new Promise(resolve=>setTimeout(resolve,100));
for(const [name,dx,dy] of [['30cm',.3,0],['50cm-after-30cm',.5,0],['50cm',.5,0],['1m',1,0],['2m',2,0],['5m',5,0],['turn',0,.5],['restart',.3,0]]) {
  await new Promise(done=>{
    const goal=[latest.poses[0][0]+dx,latest.poses[0][1]+dy];
    pending={name,goal,previousMoveId:latest.gait?.move_id,frames:0,started:false,done,timer:setTimeout(()=>{
      cases.push({case:name,phase:'timeout'});pending=null;done();
    },45000)};
    socket.send(JSON.stringify({type:'move',x:goal[0],y:goal[1],hold_stance:true}));
  });
  console.log(cases.at(-1).case,cases.at(-1).phase,cases.at(-1).error_m);
}
await writeFile('metrics/stop-distance-lab/navigation.json',JSON.stringify(cases,null,2));
socket.close();
if(cases.some(row=>row.phase!=='settled'||row.error_m>.08)) process.exitCode=1;
