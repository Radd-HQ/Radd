/** RADD-1208/1209: My Work previews stay bounded and children display progressively, against a fixture API. */
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {openBrowser,until} from './lib/cdp.mjs';
import {planningFixture,sendFixture} from './lib/planning-fixture.mjs';
import {serveBuiltSpa} from './lib/spa-server.mjs';
const requests=[];
const fixture=planningFixture();
const {item}=fixture;
// My Work reads its layout from the server since RADD-1334: these are dashboards/personal.py's defaults.
const myWork=[['assigned','Assigned to me',8,360],['due','Due soon',4,360],['activity','My activity',8,360],['inbox','Inbox',4,360],['starred','Starred',4,280]]
 .map(([widget_type,title,width,height],position)=>({id:`w-${widget_type}`,widget_type,title,width,height,collapsed:false,position,config:{}}));
const spa=await serveBuiltSpa(async(req,res,url)=>{
 if(url.pathname.startsWith('/api/')){
  let data=[]; const p=url.pathname;
  if(p==='/api/v1/sla-queue-items'){requests.push({queue:url});data=[{...item(url.searchParams.get('offset')==='200'?901:900),title:url.searchParams.get('offset')==='200'?'Later queue page':'Overdue queue item'}];}
  else if(p==='/api/v1/items/grouped'){
   const request={item_offset:Number(url.searchParams.get('item_offset')??0),axis:url.searchParams.get('axis'),column_key:url.searchParams.get('column_key')};requests.push({group:request});
   const make=(n,state)=>({...item(n),child_count:n===1?120:0,title:`Board work ${n}`,state:{id:state,name:state==='todo'?'To do':'In progress',category:state==='todo'?'todo':'in_progress'}});
   const all=Array.from({length:30},(_,i)=>make(i+1,'todo'));const rare=make(300,'progress');
   data={cells:[{column:'todo',lane:'__all__',total:30,items:all.slice(request.item_offset,request.item_offset+25)},{column:'progress',lane:'__all__',total:1,items:request.item_offset?[]:[rare]}],total_groups:2,column_points:{todo:90,progress:3},column_totals:{todo:30,progress:1},lane_totals:{__all__:31}};
   if(request.column_key) data.cells=data.cells.filter(c=>c.column===request.column_key);
  } else if(p==='/api/v1/items'||p==='/api/v1/items/count'){
   requests.push(url);
   const q=url.searchParams.get('q')??'';
   const parent=url.searchParams.get('parent_id');
   const label=parent?'Child':q.includes('starred')?'Starred':q.includes('target <=')?'Due':'Assigned';
   const pool=Array.from({length:parent?120:60},(_,i)=>({...item(i+1000),title:`${label} preview ${i+1}`}));
   const offset=Number(url.searchParams.get('after')??url.searchParams.get('offset')??0);
   const limit=Number(url.searchParams.get('limit')??50);
   data=p.endsWith('/count')?{total:pool.length}:pool.slice(offset,offset+limit);
   if(url.searchParams.get('cursor_mode')==='true') res.setHeader('X-Next-Cursor',offset+limit<pool.length?String(offset+limit):'');
  } else if(p==='/api/v1/dashboards/my-work/widgets')data=myWork;
  else data=fixture.route(p)??(p.includes('/settings')?{value:true}:p.includes('/stats')?{}:[]);
  sendFixture(res,data);return true;
 }
});
let browser;
try{
 browser=await openBrowser({port:19463,profile:await mkdtemp('/tmp/radd-grouped-proof-'),width:1600,height:1000});
 const s=browser.session;await s.navigate(`${spa.origin}/p/DEV/v/planning`,3500);
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 300'));
 assert(!requests.some(r=>r.searchParams?.has('parent_id')),'Collapsed children make no request');
 await s.click('button[aria-label="Show children of DEV-1"]');
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Child preview 50'));
 assert(!(await s.eval('document.body.innerText')).includes('Child preview 51'));
 assert(requests.some(r=>r.searchParams?.get('parent_id')==='i-1'&&r.searchParams.get('limit')==='50'));
 await s.click('button',t=>t.includes('Show 50 more children'));
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Child preview 100'));
 await s.click('button',t=>t.includes('Show 50 more children'));
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Child preview 120'));
 await s.screenshot('/tmp/radd-children-preview-proof.png');
 requests.length=0;
 await s.navigate(`${spa.origin}/`,2500);
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Due preview 25'));
 assert(!(await s.eval('document.body.innerText')).includes('Due preview 26'));
 assert((await s.eval('document.body.innerText')).includes('Starred preview 8'));
 assert(!(await s.eval('document.body.innerText')).includes('Starred preview 9'));
 assert(requests.some(r=>r.searchParams?.get('q')?.includes('ORDER BY target ASC, priority DESC, number DESC')));
 assert(requests.some(r=>r.searchParams?.get('q')?.includes('target IS EMPTY OR target >')));
 await s.click('section[aria-label="Due soon"] button',t=>t==='Show more');
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Due preview 50'));
 await s.click('section[aria-label="Due soon"] button',t=>t==='Show more');
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Due preview 60'));
 assert.equal(await s.eval(`document.querySelectorAll('section[aria-label="Due soon"] li').length`),60);
 assert(requests.some(r=>r.searchParams?.get('after')==='25'),'Show more uses a cursor');
 assert(!requests.some(r=>r.searchParams?.has('offset')),'My Work does not send offsets');
 await s.screenshot('/tmp/radd-my-work-preview-proof.png');
 assert.deepEqual(s.consoleErrors,[]);
 console.log('PASS: deferred children, 50-row progressive children to exhaustion, bounded My Work, server ordering, all matches reachable.');
}finally{browser?.close();await spa.close();}
