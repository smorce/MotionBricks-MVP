import {mkdir, writeFile} from 'node:fs/promises';
const out=process.env.PHASE81_OUTPUT??'metrics/phase8-1-visual/baseline-sequence';
await mkdir(out,{recursive:true});
const socket=new WebSocket('ws://127.0.0.1:8776/ws');
let latest, pending;
socket.onmessage=event=>{
  const frame=JSON.parse(event.data);
  if(frame.type!=='frame')return;
  latest=frame;
  if(!pending||frame.gait?.move_id===pending.previous)return;
  pending.frames.push(frame);
  if(['settled','stop_failed'].includes(frame.phase))pending.done();
};
await new Promise(resolve=>socket.onopen=resolve);
while(!latest)await new Promise(resolve=>setTimeout(resolve,100));
for(const distance of JSON.parse(process.env.PHASE81_DISTANCES??'[0.3,0.5]')){
  const before=latest, frames=[];
  await new Promise(done=>{
    const timer=setTimeout(done,180000);
    pending={previous:before.gait?.move_id,frames,done:()=>{clearTimeout(timer);done();}};
    socket.send(JSON.stringify({type:'move',x:before.poses[0][0]+distance,y:before.poses[0][1],hold_stance:true}));
  });
  pending=null;
  await writeFile(`${out}/${distance}.json`,JSON.stringify({before,frames}));
  console.log(distance,latest.phase,latest.gait?.goal_error_m);
}
socket.close();
