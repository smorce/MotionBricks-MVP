import {pathToFileURL} from 'node:url';
import {mkdir,writeFile} from 'node:fs/promises';

const {chromium}=await import(pathToFileURL(process.env.MOTIONBRICKS_PLAYWRIGHT_MODULE).href);
const out=process.cwd()+'/metrics/pr5-video';
await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000},recordVideo:{dir:out,size:{width:1440,height:1000}}});
await context.addInitScript(()=>{
  const Original=window.WebSocket;
  window.WebSocket=class extends Original {
    constructor(url,protocols){
      super(String(url).replace(':8765',':8776'),protocols);
      window.qaSocket=this;
      this.addEventListener('message',event=>{
        const row=JSON.parse(event.data);
        if(row.type==='frame') window.qaFrame=row;
      });
    }
  };
});
const page=await context.newPage();
await page.route('http://127.0.0.1:8765/**',async route=>{
  const response=await route.fetch({url:route.request().url().replace(':8765',':8776')});
  await route.fulfill({response});
});
const results=[];
try {
  await page.goto('http://127.0.0.1:5189');
  await page.waitForFunction(()=>window.qaFrame&&document.body.innerText.includes('ロゼVRM 読み込み済み'));
  for(const distance of [.3,2,5,.3]) {
    const move=await page.evaluate(distance=>{
      const frame=window.qaFrame;
      const goal=[frame.poses[0][0]+distance,frame.poses[0][1]];
      window.qaSocket.send(JSON.stringify({type:'move',x:goal[0],y:goal[1],hold_stance:true}));
      return {goal,previous:frame.gait?.move_id};
    },distance);
    let status='completed';
    try {await page.waitForFunction(previous=>window.qaFrame.gait?.move_id!==previous&&['settled','stop_failed'].includes(window.qaFrame.phase),move.previous,{timeout:90000});}
    catch {status='timeout';}
    await page.screenshot({path:`${out}/${results.length}-stop.png`});
    const frame=await page.evaluate(()=>window.qaFrame);
    results.push({distance,status,phase:frame.phase,error_m:Math.hypot(frame.poses[0][0]-move.goal[0],frame.poses[0][1]-move.goal[1]),gait:frame.gait,text:await page.locator('body').innerText()});
    await page.waitForTimeout(3000);
    await page.screenshot({path:`${out}/${results.length-1}-idle.png`});
    await writeFile(out+'/results.json',JSON.stringify(results,null,2));
    console.log(distance,frame.phase,results.at(-1).error_m);
  }
} finally {
  await context.close();
  await browser.close();
}
