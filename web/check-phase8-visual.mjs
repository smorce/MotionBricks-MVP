import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';

const require=createRequire(process.env.MOTIONBRICKS_PLAYWRIGHT_PACKAGE);
const {chromium}=require('./index.js');
const output=resolve('metrics/phase8-visual');
await mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000},recordVideo:{dir:output}});
const page=await context.newPage();
const results=[];
const capture=async label=>{
  const data=await page.evaluate(()=>window.motionBricksObservation.capture());
  const folder=resolve(output,label);
  await mkdir(folder,{recursive:true});
  for(const [angle,url] of Object.entries(data.images)) {
    await writeFile(resolve(folder,`${angle}.png`),Buffer.from(url.split(',')[1],'base64'));
  }
  delete data.images;
  await writeFile(resolve(folder,'frame.json'),JSON.stringify(data,null,2));
  return data;
};
try {
  await page.routeWebSocket('ws://127.0.0.1:8765/ws',ws=>ws.connectToServer('ws://127.0.0.1:8776/ws'));
  await page.goto('http://127.0.0.1:5188/?observation');
  await page.locator('#vrmFile').setInputFiles(resolve('ロゼ.vrm'));
  await page.waitForFunction(()=>document.body.innerText.includes('表示準備完了'));
  await page.waitForTimeout(1500);
  const cases=[['V01',.3,0],['V02',.5,0],['V03',1,0],['V04',2,0],['V05',5,0],
    ['V06',0,1],['V07',.3,0],['V08',.3,0],['V09',.5,0],['V10',.3,0]];
  for(const [name,dx,dy] of cases) {
    if(name==='V10') {
      await page.reload();
      await page.locator('#vrmFile').setInputFiles(resolve('ロゼ.vrm'));
      await page.waitForFunction(()=>document.body.innerText.includes('表示準備完了'));
      await page.waitForTimeout(1500);
    }
    const before=await capture(`${name}-before`);
    await page.evaluate(([dx,dy])=>window.motionBricksObservation.move(dx,dy),[dx,dy]);
    await page.waitForTimeout(500);
    await capture(`${name}-motion`);
    let row={case:name};
    try {
      await page.waitForFunction(id=>{
        const frame=window.motionBricksObservation.state();
        return frame?.gait?.move_id!==id&&['settled','stop_failed'].includes(frame?.phase);
      },before.frame.gait.move_id,{timeout:60000});
      const stop=await capture(`${name}-stop`);
      await page.waitForTimeout(3000);
      await capture(`${name}-idle`);
      const goal=[before.frame.poses[0][0]+dx,before.frame.poses[0][1]+dy];
      const error=Math.hypot(stop.frame.poses[0][0]-goal[0],stop.frame.poses[0][1]-goal[1]);
      row={...row,phase:stop.frame.phase,error_m:error,
        NAVIGATION_PASS:stop.frame.phase==='settled'&&error<=.08,
        POSE_PASS:null,IDLE_PASS:null,
        reason:stop.frame.gait.stop_failure_reason};
    } catch(error) {row.error=String(error);}
    results.push(row);
    await writeFile(resolve(output,'visual-results.json'),JSON.stringify(results,null,2));
    console.log(JSON.stringify(row));
  }
} finally {
  await context.close();
  await browser.close();
}
if(results.length!==10||results.some(row=>!row.NAVIGATION_PASS||row.POSE_PASS!==true||row.IDLE_PASS!==true))process.exitCode=1;
