import {pathToFileURL} from 'node:url';
import {writeFile} from 'node:fs/promises';
const {chromium}=await import(pathToFileURL(process.env.MOTIONBRICKS_PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const results=[],errors=[],received=[],requests=[];let source=null,firstNew=null;
page.on('pageerror',e=>errors.push(e.message));
page.on('websocket',socket=>{socket.on('framesent',({payload})=>{const request=JSON.parse(String(payload));if(request.type==='move')requests.push(request);});socket.on('framereceived',({payload})=>{const f=JSON.parse(String(payload));if(f.type==='error')errors.push(f);if(f.type==='frame'){received.push({sequence:f.sequence,move_id:f.gait?.move_id,phase:f.phase});if(received.length>30)received.shift();}if(source && f.type==='frame' && f.gait?.move_id>source.gait.move_id && !firstNew)firstNew=f;});});
try {
 await page.goto('http://127.0.0.1:5188/?observation');
 await page.waitForFunction(()=>document.body.innerText.includes('表示準備完了'),null,{timeout:120000});
 await page.selectOption('#stopMode','prepared');
 const state=()=>page.evaluate(()=>window.motionBricksObservation.state());
 const move=(x,y)=>page.evaluate(([x,y])=>window.motionBricksObservation.move(x,y),[x,y]);
 async function terminal(id){try{await page.waitForFunction(id=>{const f=window.motionBricksObservation.state();return f.gait.move_id!==id&&['settled','stop_failed'].includes(f.phase);},id,{timeout:30000});}catch(error){await writeFile('metrics/natural-arrival/scenario-timeout.json',JSON.stringify({sourceId:id,state:await state(),errors,received},null,2));await page.screenshot({path:'metrics/natural-arrival/scenario-timeout.png'});throw error;}}
 async function save(name,before,dx,dy){const after=await state();results.push({name,phase:after.phase,error_m:Math.hypot(after.poses[0][0]-before.poses[0][0]-dx,after.poses[0][1]-before.poses[0][1]-dy),reason:after.gait.stop_failure_reason,underflows:after.pipeline_underflows});await writeFile('metrics/natural-arrival/scenarios.json',JSON.stringify({results,errors,requests},null,2));}
 for(const [name,dx,dy] of [['right-offset',1,-.03],['left-offset',1,.03],['long',4,0]]){
  const before=await state();await move(dx,dy);await terminal(before.gait.move_id);await save(name,before,dx,dy);
 }
 const before=await state();await move(4,0);
 await page.waitForFunction(id=>{const f=window.motionBricksObservation.state();return f.gait.move_id!==id&&f.phase==='moving';},before.gait.move_id,{timeout:30000});
 source=await state();await move(0,2);await terminal(source.gait.move_id);await save('reclick',source,0,2);
 results.at(-1).source_join_m=firstNew?Math.hypot(firstNew.poses[0][0]-source.poses[0][0],firstNew.poses[0][1]-source.poses[0][1]):null;
 const capture=await page.evaluate(()=>{const o=window.motionBricksObservation;o.environment(true);const c=o.capture();o.environment(false);return c;});
 await writeFile('metrics/natural-arrival/final-capture.json',JSON.stringify({...capture,images:undefined},null,2));
 for(const [name,url] of Object.entries(capture.images)){const {writeFile}=await import('node:fs/promises');await writeFile(`metrics/natural-arrival/final-${name}.png`,Buffer.from(url.split(',')[1],'base64'));}
 const passed=results.every(r=>r.phase==='settled'&&r.error_m<=.05+1e-9)&&results.at(-1).source_join_m<=.06&&errors.length===0;
 await writeFile('metrics/natural-arrival/scenarios.json',JSON.stringify({results,errors,requests,passed},null,2));console.log(JSON.stringify({results,errors,requests,passed}));if(!passed)process.exitCode=1;
} finally {await browser.close();}
