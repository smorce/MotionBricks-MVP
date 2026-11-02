// 実VRMの同期表示・シーク・評価保存・動画を確認する。
import {pathToFileURL} from 'node:url';
import {mkdir, writeFile} from 'node:fs/promises';
const {chromium}=await import(pathToFileURL(process.env.MOTIONBRICKS_PLAYWRIGHT_MODULE).href);
const out='metrics/stop-distance-lab';
await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1600,height:1000},recordVideo:{dir:out,size:{width:1600,height:1000}}});
const page=await context.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('http://127.0.0.1:5188/stop-distance-lab.html');
 await page.locator('#manifestFile').setInputFiles(out+'/comparison.json');
 await page.locator('#vrmFile').setInputFiles('ロゼ.vrm');
 await page.waitForFunction(()=>!document.querySelector('#play').disabled,null,{timeout:120000});
 await page.locator('#play').click();await page.waitForTimeout(2500);
 await page.locator('#play').click();
 for(const view of ['front','side','quarter']){await page.locator('#view').selectOption(view);await page.waitForTimeout(300);await page.screenshot({path:out+'/'+view+'.png'});}
 const shotPromise=page.waitForEvent('download');await page.locator('#shot').click();await (await shotPromise).saveAs(out+'/comparison-image.png');
 await page.locator('#count').selectOption('8');
 await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('8候補を表示'),null,{timeout:120000});
 if(await page.locator('canvas').count()!==8)throw Error('Expected eight VRM canvases');
 await page.locator('#time').fill('0.5');await page.locator('#time').dispatchEvent('input');
 await page.locator('.review input').first().fill('自動操作で保存経路を確認。自然さは人間の評価待ち。');
 const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();await (await downloadPromise).saveAs(out+'/reviews.json');
 await page.screenshot({path:out+'/eight-candidates.png',fullPage:true});
 await page.locator('#offset').fill('8');await page.locator('#offset').dispatchEvent('change');
 await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('8候補を表示'),null,{timeout:120000});
 if(!(await page.locator('.name').first().textContent()).includes('0.300'))throw Error('Candidate paging failed');
 await writeFile(out+'/browser-check.json',JSON.stringify({errors,canvasCount:8,review:'unknown'},null,2));
 if(errors.length)throw Error(errors.join('\n'));
}catch(error){await page.screenshot({path:out+'/browser-failure.png'});console.error(await page.locator('#status').textContent(),errors);throw error;}finally{await context.close();await browser.close();}
