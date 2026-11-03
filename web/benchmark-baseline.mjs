import {pathToFileURL} from 'node:url';
import {writeFile} from 'node:fs/promises';
const {chromium}=await import(pathToFileURL(process.env.MOTIONBRICKS_PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const stream=[],errors=[],results=[],requests=[];let latestFrame=null;
page.on('pageerror',error=>errors.push(error.message));
page.on('websocket',socket=>{socket.on('framesent',({payload})=>{const request=JSON.parse(String(payload));if(request.type==='move')requests.push(request);});socket.on('framereceived',({payload})=>{const f=JSON.parse(String(payload));if(f.type==='error')errors.push(f);if(f.type==='frame'){latestFrame=f;stream.push({at:performance.now(),id:f.gait?.move_id,phase:f.phase});}});});
try {
 await page.goto(process.env.BENCHMARK_URL||'http://127.0.0.1:5190/?observation&wsPort=8766');
 await page.waitForFunction(()=>document.body.innerText.includes('表示準備完了'),null,{timeout:120000});
 await page.selectOption('#stopMode','prepared');
 await page.getByRole('button',{name:'歩行デバッグを表示',exact:true}).click();
 await page.waitForTimeout(5000);
 await page.screenshot({path:`metrics/natural-arrival/${process.env.BENCHMARK_LABEL||'baseline'}-before.png`});
 await page.evaluate(()=>{window.measurement={times:[],largeGaps:[],last:null};function sample(t){const m=window.measurement;if(m.last!==null){const interval=t-m.last;m.times.push(interval);if(interval>100)m.largeGaps.push({interval_ms:interval,phase:window.motionBricksObservation.state()?.phase});}m.last=t;if(m.times.length<4000)requestAnimationFrame(sample);}requestAnimationFrame(sample);});
 const start=Date.now();
 for(const [dx,dy] of [[2,0],[0,2],[.3,.02],[1,1],[1,-.03]]){
  await page.evaluate(([x,y])=>window.motionBricksObservation.move(x,y),[dx,dy]);
  await page.waitForTimeout(10000);
  results.push({delta:[dx,dy],phase:latestFrame?.phase,mode:latestFrame?.stop_mode,error_m:latestFrame?.gait?.goal_error_m,reason:latestFrame?.gait?.stop_failure_reason});
 }
 if(Date.now()-start<60000)await page.waitForTimeout(60000-(Date.now()-start));
 const times=await page.evaluate(()=>window.measurement.times.slice(0,3600).sort((a,b)=>a-b));
 const intervals=stream.slice(1).flatMap((frame,index)=>frame.id===stream[index].id&&['moving','decelerating','final_step','stop_retry'].includes(stream[index].phase)?[frame.at-stream[index].at]:[]).sort((a,b)=>a-b);
 const largeGaps=await page.evaluate(()=>window.measurement.largeGaps);
 const report={stop_mode:'prepared',results,requests,commit:process.env.BENCHMARK_LABEL||'278e6d4',duration_ms:Date.now()-start,render:{count:times.length,p95_ms:times[Math.floor(times.length*.95)],max_ms:times.at(-1),frames_over_100ms:times.filter(t=>t>100).length,large_gaps:largeGaps},delivery:{count:intervals.length,p95_ms:intervals[Math.floor(intervals.length*.95)],gaps_over_100ms:intervals.filter(t=>t>100).length,max_ms:intervals.at(-1)},errors};
 report.functional_passed=results.every(r=>r.phase==='settled'&&r.error_m<=.05+1e-9)&&errors.length===0;
 report.performance_passed=report.render.p95_ms<=20&&report.delivery.gaps_over_100ms===0;
 if(!report.functional_passed||!report.performance_passed)process.exitCode=1;
 await writeFile(`metrics/natural-arrival/browser-${process.env.BENCHMARK_LABEL||'baseline'}.json`,JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();}
