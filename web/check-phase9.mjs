// 実VRMで左右比較、全件表示、視点切替と評価の書き出しを確認する。
import {createRequire} from 'node:module';
import {mkdir,writeFile,copyFile} from 'node:fs/promises';
const require=createRequire(process.env.MOTIONBRICKS_PLAYWRIGHT_PACKAGE);
const {chromium}=require('./index.js');
const out='metrics/phase9';await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1600,height:1000},recordVideo:{dir:out,size:{width:1600,height:1000}}});
const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('http://127.0.0.1:5188/stop-distance-lab.html');
 await page.locator('#manifestFile').setInputFiles(out+'/comparison.json');
 await page.locator('#vrmFile').setInputFiles('ロゼ.vrm');
 await page.waitForFunction(()=>!document.querySelector('#play').disabled,null,{timeout:120000});
 await page.locator('#loop').uncheck();
 for(const scenario of ['30cm','30cm-50cm','50cm','1m','2m','5m','90-turn','idle-restart']){
  await page.locator('#scenario').selectOption(scenario);
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('2候補を表示'),null,{timeout:120000});
  await page.locator('#play').click();await page.waitForTimeout(3500);
  for(const view of ['front','side','quarter']){
   await page.locator('#view').selectOption(view);await page.waitForTimeout(100);
   await page.screenshot({path:`${out}/${scenario}-${view}.png`});
   for(const moment of ['stop_start','last_step','landing','stopped','after_one_second','idle']){
    await page.locator('#moment').selectOption(moment);await page.waitForTimeout(50);
    if(!(await page.locator('#status').textContent()).includes('未記録'))await page.screenshot({path:`${out}/${scenario}-${moment}-${view}.png`});
   }
  }
 }
 await page.locator('#scenario').selectOption('all');await page.locator('#count').selectOption('1000');
 await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('16候補を表示'),null,{timeout:120000});
 if(await page.locator('canvas').count()!==16)throw Error('Expected sixteen synchronized candidates');
 const download=page.waitForEvent('download');await page.locator('#export').click();await (await download).saveAs(out+'/review-template.json');
 await writeFile(out+'/browser-check.json',JSON.stringify({errors,human_rating:'unknown'},null,2));
 if(errors.length)throw Error(errors.join('\n'));
}finally{const video=page.video();await context.close();if(video)await copyFile(await video.path(),out+'/synchronized.webm');await browser.close();}
