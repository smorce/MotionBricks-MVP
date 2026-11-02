// 自然さを採点せず、新実験の送信・一回生成・表示だけを確認する。
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const require=createRequire(process.env.MOTIONBRICKS_PLAYWRIGHT_PACKAGE);
const {chromium}=require('./index.js');
const out='metrics/prepared-stop';await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[],results=[];
page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('http://127.0.0.1:5188/?observation');
 await page.waitForFunction(()=>document.body.innerText.includes('表示準備完了'),null,{timeout:120000});
 if(await page.locator('#stopMode').inputValue()!=='prepared')throw Error('Expected prepared stop experiment');
 for(const [name,dx,dy] of [['2m',2,0],['1m',1,0],['30cm',.3,0],['50cm',.5,0],['turn',0,2]]){
  const before=await page.evaluate(()=>window.motionBricksObservation.state());
  const id=before.gait.move_id;
  await page.evaluate(([dx,dy])=>window.motionBricksObservation.move(dx,dy),[dx,dy]);
  await page.waitForFunction(id=>{const f=window.motionBricksObservation.state();return f.gait.move_id!==id&&f.stop_mode==='prepared'},id,{timeout:30000});
  await page.waitForFunction(()=>['settled','stop_failed'].includes(window.motionBricksObservation.state().phase),null,{timeout:45000});
  await page.waitForTimeout(1500);
  const f=await page.evaluate(()=>window.motionBricksObservation.state());
  results.push({name,phase:f.phase,selection_status:f.visual_selection?.status,reference:f.visual_selection?.candidate?.id,
    start_distance_m:f.visual_selection?.target_pose_distance_m,
    arrival_error_m:Math.hypot(f.poses[0][0]-before.poses[0][0]-dx,f.poses[0][1]-before.poses[0][1]-dy),
    human_rating:'unknown',display:await page.locator('#visualStopStatus').textContent()});
  await page.screenshot({path:`${out}/${name}.png`});
 }
 await writeFile(out+'/functional-check.json',JSON.stringify({errors,results,human_rating:'unknown'},null,2));
 if(errors.length)throw Error(errors.join('\n'));
}finally{await context.close();await browser.close();}
