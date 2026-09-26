/** Backup's schedule-editor slot and Automations' own inspector editor: independent transports and
 * draft lifetimes. Both are core plugins bundled with the host (RADD-1373), so the server's loaded
 * set is their only lifecycle; Automations no longer contributes a schedule-editor slot — its editor
 * lives in the rule inspector and is exercised there. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
import { CORE_PLUGINS } from "./lib/core-plugins.mjs";
const dist=new URL('../dist/',import.meta.url).pathname;
const active=new Set();let hold=false,fail=false;
const requests=[],pending=[],aborts=[],writes=[];
const original={kind:'interval',minutes:7};
const scheduledRule={id:'scheduled',name:'Seven minute sweep',enabled:false,version:1,orientation:'vertical',triggers:[],position:0,last_run_at:null,last_run_status:'',created_at:'2026-09-25T12:00:00Z',updated_at:'2026-09-25T12:00:00Z',nodes:[{id:'trg1',kind:'trigger',type:'trigger.event',params:{event:'schedule',schedule:original},x:0,y:0}],edges:[]};
const catalog={triggers:[],trigger_kinds:[{key:'schedule',label:'On a schedule',group:'Time',description:'Runs on a clock',params_schema:{},default_params:{},has_event:false,seeds:[]}],nodes:[],node_arity:[],tokens:[],schedule_kinds:[],operators:[],payload_paths:[],manual_trigger:'manual',schedule_trigger:'schedule',can_act_as:false,max_chain_depth:3};
const harness=`import{createElement as h,useState}from'react';import{definePlugin,SlotId,Slot,SettingsPage}from'@radd/plugin-sdk';
function Harness(){const[b,setB]=useState({kind:'monthly',time:'09:00',day:31});window.__schedules={b,setB};return h(SettingsPage,{title:'Schedule ownership proof'},h('section',{'data-schedule':'backup'},h('h2',{},'backup'),h(Slot,{id:'backup.schedule.editor',value:b,onChange:setB,fallback:h('p',{},'Schedule unavailable'),errorFallback:h('p',{},'Schedule unavailable')})));}
export default definePlugin({contributions:[{id:'schedule-proof',slot:SlotId.settingsPage,match:'/settings/schedule-proof',render:()=>h(Harness)}]});`;
const server=http.createServer(async(req,res)=>{
 const p=new URL(req.url,'http://fixture').pathname;
 // Only the harness is a remote; Backup's and Automations' UI are part of the host bundle.
 if(p.startsWith('/plugins/')){if(p.split('/')[2]!=='fixture'){res.writeHead(404);res.end();return;}res.setHeader('content-type','text/javascript');res.end(harness);return;}
 if(p.startsWith('/api/')){
  res.setHeader('content-type','application/json');
  if(p.endsWith('/schedule/preview')){
   let raw='';for await(const chunk of req)raw+=chunk;const entry={path:p,body:JSON.parse(raw)};requests.push(entry);
   res.on('close',()=>{if(!res.writableEnded)aborts.push(entry);});
   const finish=()=>{if(fail){res.statusCode=503;res.end(JSON.stringify({detail:'Preview service unavailable'}));return;}
    const invalid=entry.body.expression==='bad';res.end(JSON.stringify({timezone:'Asia/Amman',next_runs:invalid?[]:['2026-10-01T06:00:00Z','2026-11-01T06:00:00Z'],error:invalid?'Invalid cron from engine':null}));};
   if(hold)pending.push(finish);else finish();return;
  }
  if(!['GET','HEAD'].includes(req.method)&&!p.endsWith('/preferences'))writes.push({path:p,method:req.method});
  let data=[];
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:'admin',global_role:'admin',permissions:['*'],timezone:'UTC'};
  else if(p.includes('capabilities'))data={capabilities:[],plugins:[...CORE_PLUGINS.filter(name=>!['automations','backup'].includes(name)),'fixture',...active],remotes:[{name:'fixture',remote_entry:'/plugins/fixture/remoteEntry.js',ui_api_version:'1.10.0'}],nav:[{key:'fixture',plugin:'fixture',path:'/settings/schedule-proof',section:'settings',label:'Schedule proof',requires:[]},{key:'backup',plugin:'backup',path:'/settings/backups',section:'settings',label:'Backups',requires:[]}],widget_types:[],view_types:[]};
  else if(p.endsWith('/backups/status'))data={maintenance:false,directory:'/fixture',directory_writable:true,tools_problem:null,key_problem:null,pg_dump:{version:'16'},pg_restore:{version:'16'},encryption_enabled:true,key_id:'fixture',key_file:'/fixture/key'};
  else if(p.endsWith('/backups/schedules'))data=[{id:'saved-backup',name:'Saved seven minute backup',config:original,keep_last:7,include_attachments:true,enabled:false}];
  else if(p.endsWith('/automations/catalog'))data=catalog;
  else if(p.endsWith('/automations'))data=[scheduledRule];
  else if(p.endsWith('/summary'))data={total:0,related_count:0,permissions:[]};
  else if(p.includes('notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('preferences'))data={};
  res.end(JSON.stringify(data));return;
 }
 const f=path.join(dist,p),target=existsSync(f)&&statSync(f).isFile()?f:path.join(dist,'index.html');res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;const checks=[];
try{
 browser=await openBrowser({port:18839,profile:await mkdtemp('/tmp/radd-schedules-'),scale:1});const s=browser.session;
 const ev=code=>s.eval(`(()=>{${code}})()`);
 const scope=owner=>`[data-schedule="${owner}"]`;
 const text=(owner,t)=>s.eval(`document.querySelector(${JSON.stringify(scope(owner))})?.innerText.includes(${JSON.stringify(t)})`);
 const runs=owner=>s.eval(`Array.from(document.querySelectorAll(${JSON.stringify(scope(owner)+' span')})).some(el=>el.textContent==='Next runs')`);
 const until=async(fn,label)=>{for(let i=0;i<250;i++){if(await fn())return;await new Promise(r=>setTimeout(r,40));}throw Error(label+': '+await s.eval('document.body.innerText')+' '+JSON.stringify(s.consoleErrors));};
 const pause=ms=>new Promise(r=>setTimeout(r,ms));
 const refresh=()=>s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
 const set=async value=>ev(`window.__schedules.setB(${JSON.stringify(value)});`);
 const draft=()=>s.eval('window.__schedules.b');
 const change=async(owner,label)=>{await s.click(scope(owner)+' button[aria-haspopup=listbox]');await until(()=>s.eval("document.querySelectorAll('[role=option]').length>0"),'schedule choices');await s.click('[role=option]',new Function('t',`return t===${JSON.stringify(label)}`));};
 const type=async(selector,value)=>ev(`const el=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event('input',{bubbles:true}));`);
 const contrast=()=>s.eval(`(()=>{
   const luminance=rgb=>rgb.slice(0,3).map(n=>{const x=n/255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4}).reduce((sum,x,i)=>sum+x*[.2126,.7152,.0722][i],0);
   const rgb=color=>color.match(/[\\d.]+/g).map(Number);
   return Array.from(document.querySelectorAll('[data-schedule="backup"] p,[data-schedule="backup"] span')).filter(el=>el.textContent.trim()&&!el.children.length).map(el=>{
     const fg=rgb(getComputedStyle(el).color);let parent=el,bg;
     while(parent){const candidate=rgb(getComputedStyle(parent).backgroundColor);if(candidate.length===3||candidate[3]===1){bg=candidate;break;}parent=parent.parentElement;}
     if(!bg)throw Error('No opaque background found');
     const a=luminance(fg),b=luminance(bg);return {text:el.textContent,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
   });
 })()`);
 const flush=()=>{while(pending.length)pending.shift()();};
 await s.send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/settings/schedule-proof`});await until(()=>text('backup','Schedule unavailable'),'initially absent');await pause(400);assert.equal(requests.length,0);checks.push('an absent Backup renders the fallback with no preview requests');
 active.add('backup');await refresh();await until(()=>runs('backup'),'backup loads independently');assert(requests.every(r=>r.path==='/api/v1/backups/schedule/preview'));assert(!(await text('backup','Create issue')));assert(await text('backup','attachment and retention'));assert(await text('backup','Schedule timezone: Asia/Amman'));assert(await text('backup','your timezone (UTC)'));checks.push('Backup previews through its own endpoint with its own help and both timezones, Automations not loaded');
 await change('backup','Weekly');await until(()=>text('backup','Mon'),'weekly defaults');assert.deepEqual(await draft(),{kind:'weekly',time:'09:00',weekdays:[0]});await s.click(scope('backup')+' button',t=>t==='Wed');assert.deepEqual(await s.eval('window.__schedules.b.weekdays'),[0,2]);await type(scope('backup')+' input[type=time]','10:30');assert.equal(await s.eval('window.__schedules.b.time'),'10:30');checks.push('kind changes remove incompatible fields; weekday and time controls update the caller draft');
 await change('backup','Custom (cron)');await until(()=>text('backup','Start from'),'cron examples');await s.click(scope('backup')+' button',t=>t==='08:00 on weekdays');assert.equal(await s.eval('window.__schedules.b.expression'),'0 8 * * 1-5');await type(scope('backup')+' input','bad');await until(()=>text('backup','Invalid cron from engine'),'engine refusal');assert(!(await runs('backup')));checks.push('cron examples update the draft and server refusals replace next-run dates');
 hold=true;await set({kind:'daily',time:'11:00'});await until(()=>text('backup','Checking next runs'),'old preview hidden immediately');assert(!(await runs('backup')));await until(()=>pending.length>=1,'held first draft');let n=requests.length,abortsBefore=aborts.length;await set({kind:'daily',time:'12:00'});await until(()=>aborts.length>abortsBefore,'replaced request aborted');await until(()=>requests.length>n,'second draft request');hold=false;flush();await until(()=>runs('backup'),'latest draft completes');assert.equal(requests.at(-1).body.time,'12:00');checks.push('editing hides old dates during debounce and aborts the superseded transport');
 hold=true;await set({kind:'daily',time:'15:00'});await until(()=>text('backup','Checking next runs'),'intermediate draft');await set({kind:'daily',time:'12:00'});await until(()=>text('backup','Checking next runs'),'return to former draft');assert(!(await runs('backup')));await until(()=>pending.length>=1,'return draft request');hold=false;flush();await until(()=>runs('backup'),'return draft fresh response');checks.push('returning to an earlier draft never revives its previous preview');
 hold=true;await set({kind:'daily',time:'13:00'});await until(()=>pending.length>=1,'request before disable');n=aborts.length;const preserved=await draft();active.delete('backup');await refresh();await until(()=>text('backup','Schedule unavailable'),'open withdrawal');await until(()=>aborts.length>n,'withdraw abort');hold=false;flush();assert.deepEqual(await draft(),preserved);const count=requests.length;await pause(500);assert.equal(requests.length,count);active.add('backup');await refresh();await until(()=>runs('backup'),'reenabled fresh preview');assert(requests.length>count);assert.deepEqual(await draft(),preserved);assert.equal(await s.eval(`document.querySelectorAll('${scope('backup')} input[type=time]').length`),1);checks.push('Backup withdrawal aborts its open preview and preserves the draft; re-enable previews afresh with one set of controls');
 fail=true;await set({kind:'monthly',time:'09:00',day:31});await until(()=>text('backup','Preview unavailable'),'failed transport');assert(!(await runs('backup')));fail=false;await s.click(scope('backup')+' button',t=>t==='Retry preview');await until(()=>runs('backup'),'retry');assert.equal(await s.eval('window.__schedules.b.day'),31);checks.push('HTTP failure shows an explicit retry and preserves the complete schedule');
 // Pending debounce must not start a request after unmount.
 await pause(400);const beforeDebounce=requests.length;await set({kind:'daily',time:'14:00'});active.delete('backup');await refresh();await until(()=>text('backup','Schedule unavailable'),'disable before debounce');await pause(500);assert.equal(requests.length,beforeDebounce);assert.deepEqual(await draft(),{kind:'daily',time:'14:00'});checks.push('withdrawal during debounce prevents the request from starting and keeps the draft');
 active.add('backup');await refresh();await until(()=>runs('backup'),'backup back for the theme check');
 await ev("document.documentElement.classList.add('light')");await until(()=>s.eval(`getComputedStyle(document.querySelector('${scope('backup')} input[type=time]')).colorScheme==='light'`),'light time input');for(const sample of await contrast())assert(sample.ratio>=4.5,JSON.stringify(sample));await s.screenshot('/tmp/radd-schedule-contributions-light.png');await ev("document.documentElement.classList.remove('light')");await until(()=>s.eval(`getComputedStyle(document.querySelector('${scope('backup')} input[type=time]')).colorScheme==='dark'`),'dark time input');for(const sample of await contrast())assert(sample.ratio>=4.5,JSON.stringify(sample));await s.screenshot('/tmp/radd-schedule-contributions-dark.png');checks.push('native time inputs follow both themes; schedule help and dates meet 4.5:1 contrast');
 await s.send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/settings/backups`});await until(()=>s.eval("document.body?.innerText.includes('Saved seven minute backup')"),'actual backup page');await s.click('button',t=>t==='Edit');await until(()=>s.eval("document.querySelector('[role=dialog]')?.innerText.includes('Every 7 minutes (saved interval)')"),'actual saved schedule');await until(()=>s.eval("Array.from(document.querySelectorAll('[role=dialog] span')).some(el=>el.textContent==='Next runs')"),'actual preview');assert(!active.has('automations'));assert(!(await s.eval("document.querySelector('[role=dialog]').innerText.includes('Create issue')")));assert.equal(requests.at(-1).path,'/api/v1/backups/schedule/preview');assert.deepEqual(requests.at(-1).body,original);await s.screenshot('/tmp/radd-backup-schedule.png');checks.push('actual host Backup settings renders its owner contribution and previews saved config without Automations');
 // Automations' schedule editor is its own, inside the rule inspector: it keeps a non-preset saved
 // interval, carries the Automations help and previews through the Automations endpoint only.
 active.add('automations');const beforeAutomation=requests.length;
 await s.send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/settings/automations`});await until(()=>s.eval("document.querySelector('[aria-label=\"Edit Seven minute sweep\"]')!==null"),'automations list');
 await s.click('[aria-label="Edit Seven minute sweep"]');await until(()=>s.eval(`document.querySelector('[data-node-id="trg1"]')!==null`),'scheduled trigger on the canvas');await s.click('[data-node-id="trg1"]');
 await until(()=>s.eval("document.body.innerText.includes('Every 7 minutes (saved interval)')"),'inspector schedule editor');await until(()=>s.eval("Array.from(document.querySelectorAll('span')).some(el=>el.textContent==='Next runs')"),'automation preview');
 const automationRequests=requests.slice(beforeAutomation);assert(automationRequests.length>0);assert(automationRequests.every(r=>r.path==='/api/v1/automations/schedule/preview'),JSON.stringify(automationRequests));assert.deepEqual(automationRequests.at(-1).body,original);
 assert(await s.eval("document.body.innerText.includes('Add a Create issue action for recurring work')"));assert(await s.eval("document.body.innerText.includes('Schedule timezone: Asia/Amman')"));assert(await s.eval("document.body.innerText.includes('your timezone (UTC)')"));assert(!(await s.eval("document.body.innerText.includes('attachment and retention')")));
 await s.screenshot('/tmp/radd-automation-schedule.png');checks.push('Automations inspector keeps the saved 7-minute interval, shows its own help and both timezones, and previews only through its endpoint');
 assert.equal(writes.length,0,JSON.stringify(writes));assert(!s.consoleErrors.some(e=>/Invalid hook|not exported|Maximum update depth/.test(e)));console.log(JSON.stringify({passed:true,checks,requests:requests.length,aborts:aborts.length}));
}finally{while(pending.length)pending.shift()();if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}
