/** RADD-1201: real built board/queue UI, bounded groups and server queue ordering. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
const dist=new URL('../dist/',import.meta.url).pathname;
const requests=[];
const stars=new Set(Array.from({length:52},(_,i)=>i+2));
const writes=[];let failStar=false;
const project={id:'project',key:'DEV',name:'Development',permissions:['item.read'],created_at:'2026-01-01'};
const cycles=[{id:'active',name:'Current sprint',status:'active',start_date:'2026-09-10',end_date:'2026-09-24'}, {id:'draft',name:'Next sprint',status:'draft',start_date:null,end_date:null},{id:'closed',name:'Historical sprint',status:'completed'}];
const view={id:'planning',project_id:project.id,name:'Planning',view_type:'board',query:'',query_string:'project_id=project',group_by:'state',swimlane_by:null,quick_filters:[],columns:['item','priority','state'],column_order:[],hidden_columns:[],cycle_filter:null,can_edit:false,can_manage:false};
const item=(n,cycle=null)=>({id:`i-${n}`,key:`DEV-${n}`,number:n,project_id:project.id,title:`${cycle?'Sprint':'Backlog'} work ${n}`,description:'',state:{id:'todo',name:'To do',category:'todo',color:'#999'},priority:'high',kind:'issue',type:null,assignee:null,reporter:null,team:null,cycle,labels:[],custom_fields:{},starred:stars.has(n),flagged:false,visibility:'public',created_at:'2026-09-01',updated_at:'2026-09-17',comment_count:0,attachment_count:0});
const sprintRows=Array.from({length:201},(_,i)=>item(15000+i,cycles[i===200?1:0]));
const backlog=Array.from({length:401},(_,i)=>item(i+1));
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://local');
 if(url.pathname.startsWith('/api/')){
  let data=[]; const p=url.pathname;
  if(p.endsWith('/star') && ['PUT','DELETE'].includes(req.method)) {
   const n=Number(p.split('/')[4].replace('i-',''));writes.push({n,method:req.method});
   if(failStar){failStar=false;res.statusCode=500;res.setHeader('content-type','application/json');res.end(JSON.stringify({detail:'Fixture write failed'}));return;}
   if(req.method==='PUT')stars.add(n);else stars.delete(n);
   res.setHeader('content-type','application/json');res.end(JSON.stringify(item(n)));return;
  }
  if(p==='/api/v1/sla-queue-items'){requests.push({queue:url});data=[{...item(url.searchParams.get('offset')==='200'?901:900),title:url.searchParams.get('offset')==='200'?'Later queue page':'Overdue queue item'}];}
  else if(p==='/api/v1/items/grouped'){
   const request={after:url.searchParams.get('after'),item_offset:Number(url.searchParams.get('after')??url.searchParams.get('item_offset')??0),axis:url.searchParams.get('axis'),column_key:url.searchParams.get('column_key')};requests.push({group:request});

   const make=(n,state)=>({...item(n),title:`Board work ${n}`,state:{id:state,name:state==='todo'?'To do':'In progress',category:state==='todo'?'todo':'in_progress'}});
   const all=Array.from({length:80},(_,i)=>make(i+1,'todo'));const rare=make(300,'progress');
   data={cells:[{column:'todo',lane:'__all__',total:80,next_cursor:request.item_offset+25<80?String(request.item_offset+25):null,items:all.slice(request.item_offset,request.item_offset+25)},{column:'progress',lane:'__all__',total:1,items:request.item_offset?[]:[rare]}],total_groups:2,column_points:{todo:240,progress:3},column_totals:{todo:80,progress:1},lane_totals:{__all__:81}};
   if(request.column_key) data.cells=data.cells.filter(c=>c.column===request.column_key);
  } else if(p==='/api/v1/items'||p==='/api/v1/items/count'){
   requests.push(url);
   const q=url.searchParams.get('q')??'';
   let pool=[...stars].sort((a,b)=>a-b).map(n=>({...item(n),title:`Saved issue ${n}`,state:n===3?{id:'done',name:'Done',category:'done'}:item(n).state}));
   if(q.includes('category NOT IN'))pool=pool.filter(i=>i.state.category!=='done');
   else if(q.includes('category IN'))pool=pool.filter(i=>i.state.category==='done');
   if(q.includes('title ~')) {const term=JSON.parse(q.match(/title ~ ("(?:[^"\\]|\\.)*")/)?.[1]??'""');pool=pool.filter(i=>i.title.includes(term));}
   const offset=Number(url.searchParams.get('after')??0),limit=Number(url.searchParams.get('limit')??50);
   data=p.endsWith('/count')?{total:pool.length}:pool.slice(offset,offset+limit);
   if(url.searchParams.get('cursor_mode')==='true')res.setHeader('X-Next-Cursor',offset+limit<pool.length?String(offset+limit):'');
  } else if(p==='/api/v1/auth/me')data={id:'person',name:'Tester',email:'tester@example.com',global_role:'member',instance_role:'member',permissions:[],timezone:'UTC'};
  else if(p==='/api/v1/views/planning')data=view;
  else if(p==='/api/v1/views')data=[view];
  else if(p==='/api/v1/projects/summary')data={total:1,related_count:1,permissions:['item.read']};
  else if(p==='/api/v1/page-spaces/summary')data={total:0,permissions:[]};
  else if(p==='/api/v1/projects')data=[project];
  else if(p.startsWith('/api/v1/projects/'))data=project;
  else if(p==='/api/v1/cycles')data=cycles;
  else if(p==='/api/v1/states')data=[{id:'todo',name:'To do',category:'todo',position:1},{id:'progress',name:'In progress',category:'in_progress',position:2}];
  else if(p.includes('/capabilities'))data={capabilities:[],nav:[],plugins:[],ui:[],view_types:[]};
  else if(p.includes('/notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('/preferences'))data={};
  else if(p.includes('/config'))data={};
  else if(p.includes('settings'))data={value:true};
  else if(p.includes('/stats'))data={};
  res.setHeader('content-type','application/json');res.setHeader('X-Total-Count',String(Array.isArray(data)?data.length:0));res.end(JSON.stringify(data));return;
 }
 const file=path.join(dist,url.pathname==='/'?'index.html':url.pathname);
 const target=existsSync(file)&&statSync(file).isFile()?file:path.join(dist,'index.html');
 res.setHeader('content-type',target.endsWith('.js')?'application/javascript':target.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
try{
 browser=await openBrowser({port:19465,profile:await mkdtemp('/tmp/radd-grouped-proof-'),width:1600,height:1000});
 const s=browser.session;await s.navigate(`http://127.0.0.1:${server.address().port}/p/DEV/v/planning`,3500);
 const until=async (test)=>{for(let i=0;i<100;i++){if(await test())return;await new Promise(r=>setTimeout(r,50));}throw new Error(await s.eval('document.body.innerText')+'\n'+s.consoleErrors.join('\n'));};
 await until(async()=> (await s.eval('document.body.innerText')).includes('Board work 300'));
 await s.click('button[aria-label="Star DEV-1"]');
 await until(async()=>await s.eval(`Boolean(document.querySelector('button[aria-label="Unstar DEV-1"]:not(:disabled)'))`));
 assert.equal(await s.eval('location.search'),'','Starring must not open peek');
 await s.eval(`document.querySelector('button[aria-label="Unstar DEV-1"]').focus()`);
 await s.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r',unmodifiedText:'\r'});
 await s.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
 await until(async()=>await s.eval(`Boolean(document.querySelector('button[aria-label="Star DEV-1"]:not(:disabled)'))`));
 assert.equal(await s.eval('location.search'),'','Keyboard starring must not open peek');
 failStar=true;
 await s.click('button[aria-label="Star DEV-1"]');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Could not star DEV-1'));
 assert(!stars.has(1),'Failed writes must not save a star');
 await s.click('button[aria-label="Dismiss"]');
 await until(async()=>await s.eval(`Boolean(document.querySelector('button[aria-label="Star DEV-1"]:not(:disabled)'))`));
 await s.click('button[aria-label="Star DEV-1"]');
 await until(async()=>stars.has(1));
 await s.click('a[href="/starred"]');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Saved issue 50'));
 let text=await s.eval('document.body.innerText');
 assert(text.includes('Done'),'Completed stars are included by default');
 assert(text.includes('53 matching'));assert(!text.includes('Saved issue 53'));
 await s.click('button',t=>t==='Show more');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Saved issue 53'));
 assert(requests.some(r=>r.searchParams?.get('after')==='50'));
 await s.click('button[aria-label="Unstar DEV-1"]');
 await until(async()=> !await s.eval(`Boolean(document.querySelector('li[aria-label="DEV-1"]'))`));
 assert(!stars.has(1));
 await s.click('input[type="search"]');await s.send('Input.insertText',{text:'Saved issue 53'});
 await until(async()=>await s.eval(`document.querySelectorAll('main li[aria-label]').length===1 && document.querySelector('main').innerText.includes('Saved issue 53')`));
 await s.eval(`const input=document.querySelector('input[type="search"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'');input.dispatchEvent(new Event('input',{bubbles:true}));`);
 await until(async()=> (await s.eval('document.body.innerText')).includes('Saved issue 2'));
 await s.eval(`(()=>{const el=[...document.querySelectorAll('label')].find(e=>e.textContent.startsWith('Status')).querySelector('select');el.value='completed';el.dispatchEvent(new Event('change',{bubbles:true}));})()`);
 await until(async()=>await s.eval(`document.querySelectorAll('main li[aria-label]').length===1 && document.querySelector('main').innerText.includes('Saved issue 3')`));
 await s.eval(`(()=>{const el=[...document.querySelectorAll('label')].find(e=>e.textContent.startsWith('Status')).querySelector('select');el.value='all';el.dispatchEvent(new Event('change',{bubbles:true}));})()`);
 await until(async()=> (await s.eval('document.body.innerText')).includes('Saved issue 50'));
 await s.click('button[aria-label="Collapse sidebar"]');
 assert(await s.eval(`Boolean(document.querySelector('a[aria-label="Starred"]'))`),'Collapsed navigation retains Starred');
 await s.click('button[aria-label="Expand sidebar"]');
 await s.screenshot('/tmp/radd-starred-proof.png');
 await s.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
 await s.screenshot('/tmp/radd-starred-mobile-proof.png');
 assert(await s.eval('document.documentElement.scrollWidth<=window.innerWidth'),'No horizontal page overflow');
 stars.clear();
 await s.navigate(`http://127.0.0.1:${server.address().port}/starred`,1500);
 await until(async()=> (await s.eval('document.body.innerText')).includes('No starred issues yet'));
 assert.deepEqual(s.consoleErrors.filter(e=>!e.includes('500')),[]);
 console.log('PASS: read-only quick stars, keyboard isolation, failure recovery, personal pin board, completed issues, cursor paging, search beyond first page, status filters and mobile layout.');
}finally{browser?.close();await new Promise(resolve=>server.close(resolve));}
