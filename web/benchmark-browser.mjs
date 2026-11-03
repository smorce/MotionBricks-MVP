import {pathToFileURL} from 'node:url';
import {mkdir,writeFile} from 'node:fs/promises';
const {chromium}=await import(pathToFileURL(process.env.MOTIONBRICKS_PLAYWRIGHT_MODULE).href);
const out='metrics/natural-arrival';await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[],results=[],stream=[];
page.on('websocket',socket=>socket.on('framereceived',({payload})=>{
 const frame=JSON.parse(String(payload));
 if(frame.type==='frame')stream.push({at:performance.now(),move_id:frame.gait?.move_id,phase:frame.phase,underflows:frame.pipeline_underflows});
}));page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('http://127.0.0.1:5188/?observation');
 await page.waitForFunction(()=>document.body.innerText.includes('表示準備完了'),null,{timeout:120000});
 await page.selectOption('#stopMode','prepared');
 await page.getByRole('button',{name:'歩行デバッグを表示',exact:true}).click();
 async function capture(name){await page.waitForTimeout(300);await page.screenshot({path:`${out}/${name}.png`});await writeFile(`${out}/${name}.txt`,await page.locator('body').innerText());}
 async function state(){return await page.evaluate(()=>window.motionBricksObservation.state());}
 async function terminal(id){await page.waitForFunction(id=>{const f=window.motionBricksObservation.state();return f?.gait?.move_id!==id && ['settled','stop_failed'].includes(f.phase);},id,{timeout:45000});}
 await capture('floor-before');const initial=await state();
 await page.mouse.click(855,740);
 await page.waitForTimeout(1000);await capture('floor-after-1s');
 await terminal(initial.gait.move_id);await capture('floor-after-stop');
 results.push({name:'floor-click',frame:await state()});
 await writeFile(out+'/browser-progress.json',JSON.stringify({results,errors},null,2));
 // 描画と接地を準備してから60秒計測する。
 await page.waitForTimeout(5000);
 await page.evaluate(()=>{window.measurement={times:[],durations:[],last:null};function sample(t){const m=window.measurement;if(m.last!==null)m.times.push(t-m.last);m.last=t;if(m.times.length<4000)requestAnimationFrame(sample);}requestAnimationFrame(sample);});
 const start=Date.now();
 for(const [name,dx,dy] of [['straight',2,0],['turn',0,2],['short',.3,.02],['diagonal',1,1]]){
  const before=await state();
  await page.evaluate(([x,y])=>window.motionBricksObservation.move(x,y),[dx,dy]);
  await terminal(before.gait.move_id);
  const after=await state();results.push({name,phase:after.phase,error_m:Math.hypot(after.poses[0][0]-before.poses[0][0]-dx,after.poses[0][1]-before.poses[0][1]-dy),reason:after.gait.stop_failure_reason,frame:after});
  await writeFile(out+'/browser-progress.json',JSON.stringify({results,errors},null,2));
 }
 if(Date.now()-start<60000)await page.waitForTimeout(60000-(Date.now()-start));
 const render=await page.evaluate(()=>{const v=window.measurement.times.slice(0,3600).sort((a,b)=>a-b);return {count:v.length,p95_ms:v[Math.floor(v.length*.95)],max_ms:v.at(-1),frames_over_100ms:v.filter(t=>t>100).length,diagnostics:window.motionBricksPerformance()};});
 const stages=await fetch('http://127.0.0.1:8765/performance').then(r=>r.json());
 const intervals=stream.slice(1).flatMap((frame,index)=>{
  const previous=stream[index];
  return frame.move_id===previous.move_id && ['moving','decelerating','final_step','stop_retry'].includes(previous.phase)?[frame.at-previous.at]:[];
 }).sort((a,b)=>a-b);
 const delivery={count:intervals.length,p95_ms:intervals[Math.floor(intervals.length*.95)],gaps_over_100ms:intervals.filter(v=>v>100).length};
 const functional_passed=results.every(result=>(result.phase||result.frame.phase)==='settled' && (result.error_m??result.frame.gait.goal_error_m)<=.05+1e-9);
 const performance_passed=render.p95_ms<=20 && delivery.gaps_over_100ms===0;
 await writeFile(out+'/browser-after.json',JSON.stringify({render,delivery,stages,results,errors,functional_passed,performance_passed},null,2));
 if(!functional_passed || !performance_passed || errors.length)process.exitCode=1;
 console.log(JSON.stringify({render,delivery,functional_passed,performance_passed,results:results.map(({frame,...rest})=>rest),errors}));
}finally{await browser.close();}
