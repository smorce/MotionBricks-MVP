// 通常画面から実歩行を送り、方式切り替えと選択表示を確認する。
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const require=createRequire(process.env.MOTIONBRICKS_PLAYWRIGHT_PACKAGE);
const {chromium}=require('./index.js');
const out='metrics/phase9-live';await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage(),errors=[],results=[];
page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('http://127.0.0.1:5188/?observation');
 await page.waitForFunction(()=>document.body.innerText.includes('表示準備完了'),null,{timeout:120000});
 if(await page.locator('#stopMode').inputValue()!=='visual')throw Error('Expected visual experiment as the selected mode');
 for(const [mode,dx,dy] of [['visual',2,0],['visual',1,0],['legacy',.3,0]]){
  await page.locator('#stopMode').selectOption(mode);
  const id=await page.evaluate(()=>window.motionBricksObservation.state().gait.move_id);
  await page.evaluate(([dx,dy])=>window.motionBricksObservation.move(dx,dy),[dx,dy]);
  await page.waitForFunction(([id,mode])=>{const f=window.motionBricksObservation.state();return f.gait.move_id!==id&&f.stop_mode===mode},[id,mode],{timeout:30000});
  await page.waitForFunction(()=>['settled','stop_failed'].includes(window.motionBricksObservation.state().phase),null,{timeout:45000});
  await page.waitForTimeout(1500);
  const f=await page.evaluate(()=>window.motionBricksObservation.state());
  results.push({mode,dx,dy,phase:f.phase,selected:f.visual_selection?.candidate?.id,x_m:f.visual_selection?.x_m,display:await page.locator('#visualStopStatus').textContent()});
  await page.screenshot({path:`${out}/${mode}-${dx}m.png`});
 }
 await page.locator('#stopMode').selectOption('visual');
 await writeFile(out+'/verification.json',JSON.stringify({errors,results},null,2));
 if(errors.length)throw Error(errors.join('\n'));
}finally{await context.close();await browser.close();}
