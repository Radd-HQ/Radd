/** RADD-1197 / RADD-1202: built Planning workflow against a local fixture API. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
const dist=new URL('../dist/',import.meta.url).pathname;
const requests=[];
const project={id:'project',key:'DEV',name:'Development',permissions:['item.read','item.update'],created_at:'2026-01-01'};
const cycles=[{id:'active',name:'Current sprint',status:'active',start_date:'2026-09-10',end_date:'2026-09-24'}, {id:'draft',name:'Next sprint',status:'draft',start_date:null,end_date:null},{id:'soon',name:'Dated upcoming sprint',status:'upcoming',start_date:'2026-10-01',end_date:'2026-10-14'},{id:'closed',name:'Historical sprint',status:'completed',start_date:'2026-08-01',end_date:'2026-08-15'}];
const view={id:'planning',project_id:project.id,name:'Planning',view_type:'planning',query:'',query_string:'project_id=project',group_by:'cycle',swimlane_by:null,quick_filters:[],columns:['item','priority','state'],column_order:[],hidden_columns:[],cycle_filter:null,can_edit:true,can_manage:true};
const item=(n,cycle=null)=>({id:`i-${n}`,key:`DEV-${n}`,number:n,project_id:project.id,title:`${cycle?'Sprint':'Backlog'} work ${n}`,description:'',state:{id:'todo',name:'To do',category:'todo',color:'#999'},priority:'high',kind:'issue',type:null,assignee:null,reporter:null,team:null,cycle,labels:[],custom_fields:{},starred:false,flagged:false,visibility:'public',created_at:'2026-09-01',updated_at:'2026-09-17',comment_count:0,attachment_count:0});
const sprintRows=Array.from({length:201},(_,i)=>item(15000+i,cycles[i===200?1:0]));
const completed={...item(16000,cycles[0]),title:'Completed active work',state:{id:'done',name:'Done',category:'done'}};
sprintRows.push(completed);
const recoveryRows=[{...item(17000,cycles[3]),title:'Unfinished historical work'}];
const historyRows=[{...item(18000,cycles[3]),title:'Finished historical work',state:completed.state}];
const backlog=Array.from({length:401},(_,i)=>item(i+1));
const writes=[];
const itemWrites=[];
const server=http.createServer(async (req,res)=>{
 const url=new URL(req.url,'http://local');
 if(url.pathname.startsWith('/api/')){
  let data=[]; const p=url.pathname;
  if(req.method==='PATCH' && p.startsWith('/api/v1/items/')) {
   let raw='';for await(const c of req)raw+=c;const patch=JSON.parse(raw);itemWrites.push(patch);
   const row=recoveryRows[0];const updated={...row,cycle:cycles.find(c=>c.id===patch.cycle_id)};
   if(patch.cycle_id==='draft'){recoveryRows.splice(0);sprintRows.push(updated);}
   res.setHeader('content-type','application/json');res.end(JSON.stringify(updated));return;
  }
  if(req.method==='PATCH' && p==='/api/v1/views/planning') {
   let body='';for await(const c of req)body+=c;
   const patch=JSON.parse(body);writes.push(patch);Object.assign(view,patch);
   res.setHeader('content-type','application/json');res.end(JSON.stringify(view));return;
  }

  if(p==='/api/v1/items'||p==='/api/v1/items/count'){
   requests.push(url);
   const sprint=url.searchParams.getAll('cycle_id').length>0;
   const q=url.searchParams.get('q')??'';
   let pool;
   if(q.includes('cycle.status = completed')) pool=q.includes('category NOT IN')?recoveryRows:historyRows;
   else if(sprint) pool=sprintRows.filter(i=>url.searchParams.getAll('cycle_id').includes(i.cycle.id)).filter(i=>q.includes('OR cycle.status = active')||i.state.category!=='done');
   else if(q.includes('cycle IS EMPTY')) {
    pool=backlog;
    if(q.includes('title ~')) { const match=q.match(/title ~ "([^"]*)"/);pool=pool.filter(i=>i.title.includes(match?.[1]??'')); }
    if(q.includes('ORDER BY updated DESC'))pool=[...pool].reverse();
   } else throw new Error('Planning fetched an unpartitioned global page: '+url);

   if(q.includes('title ~')) { const term=JSON.parse(q.match(/title ~ ("(?:[^"\\]|\\.)*")/)?.[1]??'""'); pool=pool.filter(i=>i.title.includes(term)); }
   data=p.endsWith('/count')?{total:pool.length}:pool.slice(Number(url.searchParams.get('offset')??0),Number(url.searchParams.get('offset')??0)+Number(url.searchParams.get('limit')??50));
  } else if(p==='/api/v1/auth/me')data={id:'person',name:'Tester',email:'tester@example.com',global_role:'member',instance_role:'member',permissions:[],timezone:'UTC'};
  else if(p==='/api/v1/views/planning')data=view;
  else if(p==='/api/v1/views')data=[view];
  else if(p==='/api/v1/projects/summary')data={total:1,related_count:1,permissions:['item.read','item.update']};
  else if(p==='/api/v1/page-spaces/summary')data={total:0,permissions:[]};
  else if(p==='/api/v1/projects')data=[project];
  else if(p.startsWith('/api/v1/projects/'))data=project;
  else if(p==='/api/v1/cycles')data=cycles;
  else if(p==='/api/v1/states')data=[{id:'todo',name:'To do',category:'todo',position:1}];
  else if(p.includes('/capabilities'))data={capabilities:[],nav:[],plugins:[],ui:[],view_types:[]};
  else if(p.includes('/notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('/preferences'))data={};
  else if(p.includes('/config'))data={};
  else if(p.includes('/settings'))data={value:false};
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
 browser=await openBrowser({port:19442,profile:await mkdtemp('/tmp/radd-planning-proof-'),width:1600,height:1000});
 const s=browser.session;await s.navigate(`http://127.0.0.1:${server.address().port}/p/DEV/v/planning`,3500);
 const until=async (test)=>{for(let i=0;i<100;i++){if(await test())return;await new Promise(r=>setTimeout(r,50));}throw new Error(await s.eval('document.body.innerText')+'\n'+s.consoleErrors.join('\n'));};
 await until(async()=> (await s.eval('document.body.innerText')).includes('Sprint work 15200'));
 const names=await s.eval(`Array.from(document.querySelectorAll('section[aria-label]')).filter(e=>e.querySelector('header button')).map(e=>e.getAttribute('aria-label'))`);
 assert.deepEqual(names,['Current sprint','Dated upcoming sprint','Next sprint','Needs rescheduling','Backlog']);
 let text=await s.eval('document.body.innerText');assert.ok(text.includes('Backlog work 1'));assert.equal(await s.eval(`Boolean(document.querySelector('section[aria-label="History · Historical sprint"]'))`),false);assert.ok(text.includes('201 open sprint issues · 401 backlog · 1 need rescheduling'));
 assert.ok(requests.every(url=>url.searchParams.getAll('cycle_id').length||url.searchParams.get('q')?.includes('cycle IS EMPTY')||url.searchParams.get('q')?.includes('cycle.status = completed')),'No globally paged request');
 const before=requests.filter(u=>u.pathname.endsWith('/items')&&u.searchParams.has('cycle_id')).length;
 await s.click('button[aria-label="Next page"]');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Backlog work 201'));
 text=await s.eval('document.body.innerText');assert.ok(text.includes('Sprint work 15200'));assert.ok(!text.includes('Backlog work 1\n'));
 assert.equal(requests.filter(u=>u.pathname.endsWith('/items')&&u.searchParams.has('cycle_id')).length,before,'Backlog paging must not reload sprint work');

 assert(text.includes('Unfinished historical work'));assert(text.includes('Completed active work'));
 assert(!text.includes('Finished historical work'));
 // Collapse stays local and restores its rows; no view PATCH.
 await s.click('section[aria-label="Current sprint"] header button');
 assert.equal(await s.eval(`document.querySelector('section[aria-label="Current sprint"] header button').getAttribute('aria-expanded')`),'false');
 assert.equal(writes.length,0);
 await s.click('section[aria-label="Current sprint"] header button');
 // Controls live in Display, not a second toolbar. Each section has its own search.
 assert(!await s.eval(`Boolean(document.querySelector('[aria-label="Planning controls"]'))`));
 assert.equal(await s.eval(`document.querySelectorAll('section button[aria-label^="Search "]').length`),5);
 const display=()=>s.click('button',t=>t.trim()==='Display');
 await display();
 // Show completed applies only to the sprint stream, never backlog pagination.
 const completedToggle=`[...document.querySelectorAll('label')].find(l=>l.textContent.includes('Show completed issues in active sprints')).querySelector('input')`;
 await s.eval(completedToggle+'.click()');
 await until(async()=>{const t=await s.eval('document.body.innerText');return !t.includes('Completed active work')&&t.includes('Backlog work 201');});
 await s.eval(completedToggle+'.click()');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Completed active work'));
 // History is explicitly requested and kept separate from unfinished work.
 await s.eval(`[...document.querySelectorAll('label')].find(l=>l.textContent.includes('Completed sprint history')).querySelector('input').click()`);
 await until(async()=> (await s.eval('document.body.innerText')).includes('Finished historical work'));
 assert((await s.eval('document.body.innerText')).includes('Unfinished historical work'));
 await s.eval(`[...document.querySelectorAll('label')].find(l=>l.textContent.includes('Completed sprint history')).querySelector('input').click()`);
 await display();
 await s.click('button[aria-label="Search Backlog"]');
 // Search only the backlog; empty explanations are visible.
 await s.click('input[type="search"]');await s.send('Input.insertText',{text:'nothing matches'});
 await until(async()=> (await s.eval('document.body.innerText')).includes('No issue titles match this section’s filter.'));
 assert((await s.eval('document.body.innerText')).includes('Sprint work 15200'));
 await s.eval(`document.querySelector('input[type="search"]').select()`);await s.send('Input.insertText',{text:'Backlog work 401'});
 await until(async()=> (await s.eval('document.body.innerText')).includes('Backlog work 401'));
 await s.eval(`document.querySelector('input[type="search"]').select()`);await s.send('Input.insertText',{text:'Backlog work'});
 await until(async()=> (await s.eval('document.body.innerText')).includes('200 shown · 401 matching'));
 assert(!await s.eval(`Boolean(document.querySelector('button[aria-label="Next page"]'))`));
 await s.click('button',t=>t==='Show more matches');
 await until(async()=> (await s.eval('document.body.innerText')).includes('400 shown · 401 matching'));
 await s.click('button',t=>t==='Show more matches');
 await until(async()=> (await s.eval('document.body.innerText')).includes('401 shown · 401 matching'));
 await s.eval(`document.querySelector('input[type="search"]').select()`);await s.send('Input.insertText',{text:' '});
 await until(async()=>await s.eval(`document.querySelector('section[aria-label="Backlog"] ul')?.children.length===200 && Boolean(document.querySelector('button[aria-label="Next page"]'))`));
 // Exercise the kit select controls through their rendered buttons/options.
 const pick=async(label,option)=>{
  await s.eval(`[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===${JSON.stringify(label)}).scrollIntoView({block:'center'})`);
  await s.click('button',new Function('text',`return text.trim()===${JSON.stringify(label)}`));
  await until(async()=>await s.eval(`Boolean(document.querySelector('[role="option"]'))`));
  await s.click('[role="option"]',new Function('text',`return text.trim()===${JSON.stringify(option)}`));
 };
 await pick('Priority','Recently updated');
 await until(async()=>requests.some(u=>u.searchParams.get('q')?.includes('cycle IS EMPTY')&&u.searchParams.get('q')?.includes('ORDER BY updated DESC')));
 await pick('Recently updated','Manual');
 await until(async()=>requests.some(u=>u.searchParams.get('q')?.includes('cycle IS EMPTY')&&u.searchParams.get('q')?.includes('ORDER BY rank')));
 await display();
 await pick('Choose a sprint…','Current sprint');
 await until(async()=>!await s.eval(`Boolean(document.querySelector('section[aria-label="Current sprint"]'))`));
 assert(writes.some(p=>p.hidden_columns?.includes('active')));
 assert((await s.eval('document.body.innerText')).includes('Restore 1 hidden sprint'));
 await s.click('button',t=>t.includes('Restore 1 hidden sprint'));
 await until(async()=>await s.eval(`Boolean(document.querySelector('section[aria-label="Current sprint"]'))`));
 await display();

 // Sprint quick search stays scoped and does not rewrite progress from its one result.

 await s.click('button[aria-label="Search Current sprint"]');
 await s.click('input[aria-label="Search titles in Current sprint"]');await s.send('Input.insertText',{text:'Sprint work 15099'});
 await until(async()=>await s.eval(`document.querySelector('section[aria-label="Current sprint"] ul').children.length===1 && document.querySelector('section[aria-label="Current sprint"] ul').innerText.includes('Sprint work 15099')`));
 assert((await s.eval(`document.querySelector('section[aria-label="Current sprint"] header').innerText`)).includes('1/201'));
 assert((await s.eval('document.body.innerText')).includes('Unfinished historical work'));
 await s.eval(`document.querySelector('[aria-label="Select DEV-15099"]').click()`);
 await s.eval(`document.querySelector('[aria-label="Select DEV-15200"]').dispatchEvent(new MouseEvent('click',{bubbles:true,shiftKey:true}))`);
 assert.equal(await s.eval(`document.querySelectorAll('section input[type="checkbox"]:checked').length`),2,'Shift selection must use filtered rows');
 await s.click('input[aria-label="Search titles in Current sprint"]');
 await s.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
 await s.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape'});
 await until(async()=>await s.eval(`document.querySelector('section[aria-label="Current sprint"] ul').children.length===201`));
 assert.equal(await s.eval('document.activeElement.getAttribute("aria-label")'),'Search Current sprint');
 assert.equal(await s.eval(`document.querySelectorAll('section input[type="checkbox"]:checked').length`),0,'Changing filter clears selection');
 // The recovery section is a source of work, never a writable synthetic sprint ID.
 const drag=async(source,target)=>{
  await s.eval(`document.querySelector(${JSON.stringify(source)}).dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:new DataTransfer()}))`);
  await new Promise(r=>setTimeout(r,100));
  await s.eval(`document.querySelector(${JSON.stringify(target)}).dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:new DataTransfer()}))`);
  await new Promise(r=>setTimeout(r,250));
 };
 await drag('section[aria-label="Current sprint"] ul>li','section[aria-label="Needs rescheduling"]');
 assert.equal(itemWrites.length,0,'Needs rescheduling must not accept a fabricated cycle ID');
 await drag('section[aria-label="Needs rescheduling"] ul>li','section[aria-label="Next sprint"]');
 await until(async()=>itemWrites.length===1);
 assert.equal(itemWrites[0].cycle_id,'draft');
 await until(async()=> (await s.eval(`document.querySelector('section[aria-label="Next sprint"]').innerText`)).includes('Unfinished historical work'));
 // Collapse the large groups to inspect all sections and controls in one screenshot.
 for(const name of ['Current sprint','Next sprint','Backlog']) await s.click(`section[aria-label="${name}"] header button`);
 await s.screenshot('/tmp/radd-planning-workflow-proof.png');

 // Reopening retains personal controls. Read-only viewers cannot change shared visibility.
 view.can_edit=false;view.can_manage=false;project.permissions=['item.read'];
 view.query='priority = high ORDER BY created DESC';view.query_string='project_id=project&q='+encodeURIComponent(view.query);
 await s.navigate(`http://127.0.0.1:${server.address().port}/p/DEV/v/planning`,2000);
 await s.click('button',t=>t.trim()==='Display');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Saved and temporary filters still apply'));
 assert((await s.eval('document.body.innerText')).includes('Manual'));
 assert(!(await s.eval('document.body.innerText')).includes('Hide a sprint for this view'));
 assert(requests.some(u=>u.searchParams.get('q')?.includes('priority = high')&&u.searchParams.get('q')?.includes('cycle IS EMPTY')));
 assert.equal(await s.eval(`document.querySelector('section[aria-label="Current sprint"] header button').getAttribute('aria-expanded')`),'false');
 await display();
 await s.screenshot('/tmp/radd-planning-controls-proof.png');
 // Search opens a collapsed group without toggling other cards.
 await s.click('button[aria-label="Search Backlog"]');
 assert.equal(await s.eval(`document.querySelector('section[aria-label="Backlog"] header button').getAttribute('aria-expanded')`),'true');
 await s.screenshot('/tmp/radd-planning-search-proof.png');
 await s.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
 await display();
 await new Promise(r=>setTimeout(r,300));
 await s.screenshot('/tmp/radd-planning-display-mobile-proof.png');
 const rect=await s.eval(`(()=>{const r=document.querySelector('[aria-label="Card display options"]').getBoundingClientRect();return {left:r.left,right:r.right,height:r.height}})()`);
 assert(rect.left>=0&&rect.right<=390&&rect.height<=844,'Display must fit mobile viewport');
 assert.deepEqual(s.consoleErrors,[]);
 console.log('PASS: Planning workflow, section search across 401 matches, unchanged progress, Display controls, keyboard focus, collapsed search and mobile popover bounds.');
}finally{browser?.close();await new Promise(resolve=>server.close(resolve));}
