import {pathToFileURL} from 'node:url';
import {mkdir,writeFile} from 'node:fs/promises';

const {chromium}=await import(pathToFileURL(process.env.MOTIONBRICKS_PLAYWRIGHT_MODULE).href);
const out=process.cwd()+'/metrics/stop-browser';
await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
try {
  const context=await browser.newContext({viewport:{width:1440,height:1000},recordVideo:{dir:out,size:{width:1440,height:1000}}});
  await context.addInitScript(()=>{
    const Original=window.WebSocket;
    window.WebSocket=class extends Original {
      constructor(url,protocols){super(String(url).replace(':8765',':8776'),protocols);}
    };
  });
  const page=await context.newPage();
  await page.route('http://127.0.0.1:8765/**',async route=>{
    const response=await route.fetch({url:route.request().url().replace(':8765',':8776')});
    await route.fulfill({response});
  });
  await page.goto('http://127.0.0.1:5188');
  await page.waitForTimeout(5000);
  await page.screenshot({path:out+'/before.png'});
  await page.mouse.click(1200,680);
  const rows=[];
  for(let i=0;i<30;i++){
    await page.waitForTimeout(500);
    await page.screenshot({path:out+`/frame-${String(i).padStart(2,'0')}.png`});
    rows.push({time:i*.5,text:await page.locator('body').innerText()});
  }
  await writeFile(out+'/observations.json',JSON.stringify(rows,null,2));
  console.log(rows.at(-1));
  await page.reload();
  await page.waitForTimeout(3000);
  await page.screenshot({path:out+'/after-reload.png'});
  await writeFile(out+'/after-reload.txt',await page.locator('body').innerText());
  await context.close();
} finally {
  await browser.close();
}
