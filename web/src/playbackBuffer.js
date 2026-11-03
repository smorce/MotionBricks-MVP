export class PlaybackBuffer {
  constructor(delayMs=100){this.delayMs=delayMs;this.clear();}
  clear(){this.frames=[];this.sequence=-1;this.offset=null;this.lastArrival=null;this.afterMoveId=null;}
  beginMove(moveId){this.clear();this.afterMoveId=moveId;}
  push(frame,now){
    if(this.afterMoveId!==null && (frame.gait?.move_id??0)<=this.afterMoveId)return false;
    if(!Number.isFinite(frame.sequence)||!Number.isFinite(frame.simulation_time)||frame.sequence<=this.sequence)return false;
    const previous=this.frames.at(-1);
    if(previous && this.lastArrival!==null && now-this.lastArrival>this.delayMs && now-this.offset-this.delayMs>previous.simulation_time*1000){
      this.offset=now-previous.simulation_time*1000-this.delayMs;
    }
    this.lastArrival=now;
    this.sequence=frame.sequence;
    if(this.offset===null)this.offset=now-frame.simulation_time*1000;
    if(frame.simulation_time*1000>now-this.offset+this.delayMs){
      this.frames=[];
      this.offset=now-frame.simulation_time*1000;
    }
    this.frames.push(frame);
    if(this.frames.length>120)this.frames.shift();
    return true;
  }
  sample(now){
    if(!this.frames.length)return null;
    const time=(now-this.offset-this.delayMs)/1000;
    while(this.frames.length>2 && this.frames[1].simulation_time<=time)this.frames.shift();
    const a=this.frames[0], b=this.frames[1]||a;
    const span=b.simulation_time-a.simulation_time;
    return {a,b,blend:span>0?Math.max(0,Math.min(1,(time-a.simulation_time)/span)):1};
  }
}
