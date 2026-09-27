/** RADD-1212: built UI proof of stable, visible-first board navigation. */
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {openBrowser,until} from './lib/cdp.mjs';
import {planningFixture,sendFixture} from './lib/planning-fixture.mjs';
import {serveBuiltSpa} from './lib/spa-server.mjs';
const requests=[];
let failSecondWindow = true;
const states=Array.from({length:30},(_,i)=>({id:i===0?'todo':i===1?'progress':`state-${i}`,name:i===0?'To do':i===1?'In progress':`Stage ${i}`,category:'todo',position:i}));
const moves=[];
// RADD-1396: the queue is the slas plugin's view type, declared a list surface over its own rows.
const QUEUE='slas.queue';
let queueEnabled=true;
const queueType={key:QUEUE,label:'Queue (triage list)',icon:'list-ordered',sidebar_section:'Queues',
 list_surface:{rows_path:'/sla-queue-items',columns:['type','reporter','priority','slas.timer','state'],refresh_seconds:60}};
const fixture=planningFixture({permissions:['item.read','item.update'],states,
 capabilities:()=>({capabilities:[],nav:[],plugins:queueEnabled?['slas']:[],ui:[],view_types:queueEnabled?[queueType]:[]})});
const {cycles,view,item}=fixture;
const sprintRows=Array.from({length:201},(_,i)=>item(15000+i,cycles[i===200?1:0]));
const backlog=Array.from({length:401},(_,i)=>item(i+1));
const spa=await serveBuiltSpa(async(req,res,url)=>{
 if(url.pathname.startsWith('/api/')){
  let data=[]; const p=url.pathname;
  if(p==='/api/v1/sla-queue-items'){requests.push({queue:url});data=[{...item(url.searchParams.get('offset')==='200'?901:900),title:url.searchParams.get('offset')==='200'?'Later queue page':'Overdue queue item'}];}
  else if(p==='/api/v1/items/grouped'){
   const request=Object.fromEntries(url.searchParams);requests.push({group:request});
   if(request.after==='50' && failSecondWindow){failSecondWindow=false;res.statusCode=503;res.setHeader('content-type','application/json');res.end(JSON.stringify({detail:'Temporary fixture failure'}));return true;}
   const column_totals=Object.fromEntries(states.map((s,i)=>[s.id,i===0?80:1]));
   const lane_totals=view.swimlane_by?{high:100,normal:9}:{__all__:109};
   const column_labels=Object.fromEntries(states.map(s=>[s.id,s.name]));
   data={cells:[],total_groups:view.swimlane_by?60:30,column_points:{todo:240,progress:3},column_totals,lane_totals,column_labels,lane_labels:{high:'High',normal:'Normal'},epic_refs:{}};
   if(request.rows_only==='true') {
    const col=request.column_key,ln=request.lane_key??'__all__';
    const count=request.lane ? (ln==='high'?(col==='todo'?71:1):ln==='normal'&&col==='todo'?9:0) : col==='todo'?80:1,offset=Number(request.after??0),idx=states.findIndex(s=>s.id===col);
    const all=Array.from({length:count},(_,i)=>({...item(idx*1000+i+1),title:`Board work ${idx*1000+i+1}`,state:states[idx],priority:ln==='normal'?'normal':'high'}));
    data={...data,cells:[{column:col,lane:ln,total:null,items:all.slice(offset,offset+25),next_cursor:offset+25<count?String(offset+25):null}],column_totals:{},lane_totals:{},column_points:{}};
   }
  } else if(p==='/api/v1/items'||p==='/api/v1/items/count'){
   requests.push(url);
   const sprint=url.searchParams.getAll('cycle_id').length>0;
   const q=url.searchParams.get('q')??'';
   const pool=sprint?sprintRows:q.includes('cycle IS EMPTY')?backlog:Array.from({length:14704},(_,i)=>({...item(i+1,cycles[2]),state:{id:'done',name:'Done',category:'done'}}));
   data=p.endsWith('/count')?{total:view.view_type===QUEUE?201:pool.length}:pool.slice(Number(url.searchParams.get('offset')??0),Number(url.searchParams.get('offset')??0)+Number(url.searchParams.get('limit')??50));
  } else if(req.method==='PATCH' && p.startsWith('/api/v1/items/')){ let raw='';for await(const chunk of req)raw+=chunk; moves.push(JSON.parse(raw));data={...item(1),state:states.find(s=>s.id===moves.at(-1).state_id)??states[0]};
  } else data=fixture.route(p)??(p.includes('settings')?{value:true}:p.includes('/stats')?{}:[]);
  sendFixture(res,data);return true;
 }
});
let browser;
try{
 browser=await openBrowser({port:19467,profile:await mkdtemp('/tmp/radd-grouped-proof-'),width:1600,height:1000});
 const s=browser.session;await s.navigate(`${spa.origin}/p/DEV/v/planning`,3500);
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 1001'));
 let text=await s.eval('document.body.innerText');
 assert(text.includes('Board work 1'));assert(!text.includes('Previous groups'));assert(!text.includes('Show 25 more'));
 assert.equal(requests.filter(r=>r.group?.summary_only==='true').length,1);
 assert(requests.filter(r=>r.group?.rows_only==='true').length<8,'Only visible columns load initially');
 assert(!requests.some(r=>r.group?.column_key==='state-29'),'Far column remains unloaded');
 const metrics=await s.eval(`(()=>{const c=document.querySelector('[data-board-column="todo"]'),b=c.querySelector('[data-column-scroll]'),card=b.querySelector('[draggable]');return {height:b.clientHeight,scroll:b.scrollHeight,card:card.getBoundingClientRect().height,total:c.innerText}})()`);
 assert(metrics.scroll>metrics.height&&metrics.card>70,'Column scrolls without crushing cards');
 assert(metrics.total.includes('80')&&metrics.total.includes('240'),'Full statistics, not loaded-page totals');
 const bottom=()=>s.eval(`(()=>{const n=document.querySelector('[data-board-column="todo"] [data-column-scroll]');n.scrollTop=n.scrollHeight})()`);
 await bottom();await until(s,async()=>requests.some(r=>r.group?.after==='25'));
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 50'));
 await bottom();await until(s,async()=> (await s.eval('document.body.innerText')).includes('Retry loading'));
 assert((await s.eval('document.body.innerText')).includes('Board work 50'),'Failure keeps prior cards');
 await s.click('button',t=>t.includes('Retry loading'));
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 75'));
 await bottom();await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 80'));
 assert.deepEqual(requests.filter(r=>r.group?.column_key==='todo').map(r=>r.group.after??null),[null,'25','50','50','75']);
 assert.equal(requests.filter(r=>r.group?.summary_only==='true').length,1,'Continuation never recounts board');
 await s.eval(`document.querySelector('input[aria-label="Select DEV-1"]').click()`);
 const scrollBefore=await s.eval(`document.querySelector('[data-column-scroll]').scrollTop`);
 await s.click('button[aria-label="Jump to column"]');
 await s.eval(`(()=>{const n=document.querySelector('input[placeholder]');const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;set.call(n,'Stage 29');n.dispatchEvent(new Event('input',{bubbles:true}))})()`);
 await s.click('[role="option"]',t=>t.includes('Stage 29'));
 await until(s,async()=>requests.some(r=>r.group?.column_key==='state-29'));
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 29001'));
 await s.click('button[aria-label="Jump to column"]');await s.click('[role="option"]',t=>t.includes('To do'));
 await until(s,async()=>await s.eval(`document.querySelector('[data-board-scroll]').scrollLeft<50`));
 assert.equal(await s.eval(`document.querySelector('[data-column-scroll]').scrollTop`),scrollBefore,'Returning preserves column scroll');
 assert(await s.eval(`document.querySelector('input[aria-label="Select DEV-1"]').checked`),'Selection survives navigation');
 assert.equal(requests.filter(r=>r.group?.column_key==='todo'&&!r.group.after).length,1,'Returning reuses cached cards');
 await s.eval(`document.querySelector('[data-column-scroll]').scrollTop=0`);
 await s.screenshot('/tmp/radd-board-navigation-proof.png');
 await s.eval(`(()=>{const dt=new DataTransfer();window.proofDrag=dt;document.querySelector('[data-board-column="todo"] [draggable]').dispatchEvent(new DragEvent('dragstart',{bubbles:true,cancelable:true,dataTransfer:dt}))})()`);
 await new Promise(r=>setTimeout(r,100));
 await s.eval(`(()=>{const n=document.querySelector('[data-board-scroll]'),r=n.getBoundingClientRect();n.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:window.proofDrag,clientX:r.right-10,clientY:r.top+100}))})()`);
 await until(s,async()=>await s.eval(`document.querySelector('[data-board-scroll]').scrollLeft>0`));
 await s.eval(`document.querySelector('[data-board-scroll]').scrollLeft=0`);
 await s.eval(`(()=>{const n=document.querySelector('[data-board-column="progress"]');n.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:window.proofDrag}));n.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:window.proofDrag}))})()`);
 await until(s,async()=>moves.length>0);assert.equal(moves.at(-1).state_id,'progress');
 view.swimlane_by='priority';requests.length=0;
 await s.navigate(`${spa.origin}/p/DEV/v/planning`,1500);
 await until(s,async()=>requests.some(r=>r.group?.lane_key==='high'));
 assert.equal(await s.eval(`document.querySelectorAll('[data-board-lane]').length`),4,'Complete natural lane structure is present');
 assert(requests.filter(r=>r.group?.rows_only&&r.group.lane==='priority').every(r=>r.group.lane_key&&r.group.column_key),'Each fetch targets a complete cell');
 assert(!requests.some(r=>Number(r.group?.group_offset)>0),'No cell-set paging');
 await s.screenshot('/tmp/radd-board-swimlanes-proof.png');
 assert.deepEqual(s.consoleErrors.filter(e=>!e.includes('503')),[]);
 console.log('PASS: stable columns, visible-first requests, full totals, automatic cursor continuation/retry, searchable jump, preserved scroll/cache, drag/drop and complete swimlanes.');
 await s.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 view.swimlane_by=null;
 await s.navigate(`${spa.origin}/p/DEV/v/planning`,1500);
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 1'));
 assert(await s.eval(`(()=>{const r=document.querySelector('button[aria-label="Jump to column"]').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})()`),'Mobile column navigator stays on screen');
 await s.screenshot('/tmp/radd-board-mobile-proof.png');
 await s.send('Emulation.clearDeviceMetricsOverride');
 view.view_type='list';view.group_by='state';view.swimlane_by='priority';requests.length=0;
 await s.navigate(`${spa.origin}/p/DEV/v/planning`,2000);
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 1'));
 assert.equal(await s.eval('document.querySelectorAll("[data-list-group]").length'),30,'Every list group is present before loading its rows');
 assert(!(await s.eval('document.body.innerText')).includes('Load more in these groups'));
 assert(!(await s.eval('document.body.innerText')).includes('Next groups'));
 assert(!requests.some(r=>r.group?.column_key==='state-29'),'Distant list groups stay unloaded');
 assert(requests.filter(r=>r.group?.rows_only).every(r=>!r.group.lane),'List ignores a saved board swimlane');
 const listBottom=()=>s.eval(`(()=>{const n=document.querySelector('[data-list-group-scroll="todo"]');n.scrollTop=n.scrollHeight})()`);
 await listBottom();await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 50'));
 assert.equal(requests.filter(r=>r.group?.summary_only==='true').length,1,'List continuation does not recount');
 assert((await s.eval(`document.querySelector('[data-list-group="todo"] header').innerText`)).includes('80'),'Header retains complete total');
 await s.eval(`document.querySelector('[data-list-group="todo"] header button').click()`);
 assert.equal(await s.eval(`document.querySelectorAll('[data-list-group-scroll="todo"]').length`),0,'Collapsed group does not render rows or loader');
 await s.click('button[aria-label="Jump to group"]');await s.send('Input.insertText',{text:'Stage 29'});await s.click('[role="option"]',t=>t.includes('Stage 29'));
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 29001'));
 await s.click('button[aria-label="Jump to group"]');await s.click('[role="option"]',t=>t.includes('To do'));
 await until(s,async()=> Boolean(await s.eval(`document.querySelector('[data-list-group-scroll="todo"]') !== null`)));
 assert.equal(requests.filter(r=>r.group?.column_key==='todo'&&!r.group.after).length,1,'Returning to a collapsed group reuses its rows');
 await s.screenshot('/tmp/radd-grouped-list-navigation-proof.png');
 assert.deepEqual(s.consoleErrors.filter(e=>!e.includes('503')),[]);
 console.log('PASS: grouped list has complete searchable groups, independent scroll loading, full totals, collapse/reopen cache and no bottom batch pager.');
 view.view_type=QUEUE;view.group_by='state';view.swimlane_by=null;requests.length=0;
 await s.navigate(`${spa.origin}/p/DEV/v/planning`,2000);
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Overdue queue item'));
 assert.ok(requests.some(r=>r.queue));assert.ok(!requests.some(r=>r.pathname?.endsWith('/items')));
 // RADD-1466 (RADD-687's measurement, dropped with pager-proof in RADD-1410): the pager states the
 // TRUE total of the seeded rows (201 here), never a truncated page count or "200+".
 const SEEDED_QUEUE_ROWS=201;
 // The total is the nav's own span ("201 entries"); the page-number buttons would glue their digits onto it.
 const pagerText=()=>s.eval(`(document.querySelector('nav[aria-label="Pagination"] > span:not([data-page-size])')?.textContent ?? '').replace(/[,\\u202f\\u00a0]/g,'')`);
 await until(s,async()=>/\d{3,}/.test(await pagerText()),'pager with a total');
 const pager=await pagerText();
 const statedTotal=Math.max(...pager.match(/\d{3,}/g).map(Number));
 assert.ok(statedTotal>=SEEDED_QUEUE_ROWS,`the pager states a true total (${statedTotal} >= ${SEEDED_QUEUE_ROWS}; text: ${pager})`);
 console.log(`PASS: the pager states a true total (${statedTotal} >= ${SEEDED_QUEUE_ROWS}).`);
 assert.ok(!requests.some(r=>r.group),'A list-surface plugin type is flat: its stored axis is ignored');
 await s.click('button[aria-label="Next page"]');
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Later queue page'));
 assert.ok(requests.some(r=>r.queue?.searchParams.get('offset')==='200'));
 assert.deepEqual(s.consoleErrors.filter(e=>!e.includes('503')),[]);
 console.log('PASS: a plugin list type (the slas queue) reads its declared rows endpoint across pagination.');
 queueEnabled=false;requests.length=0;
 await s.navigate(`${spa.origin}/p/DEV/v/planning`,2000);
 await until(s,async()=> await s.eval(`!!document.querySelector('[data-plugin-missing="view"]')`));
 assert.ok(!requests.some(r=>r.queue),'A view whose type is gone asks no rows endpoint');
 assert.match(await s.eval(`document.querySelector('[data-plugin-missing="view"]').textContent`),/slas\.queue|no longer available|type/i);
 assert.deepEqual(s.consoleErrors.filter(e=>!e.includes('503')),[]);
 console.log('PASS: with slas disabled a saved queue view shows the missing-type notice instead of crashing.');
 console.log('PASS: board immediately shows rare state, loads further rows without losing other groups, displays full count and avoids global paging.');
}finally{browser?.close();await spa.close();}
