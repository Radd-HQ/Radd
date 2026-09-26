/** RADD-1210/1211: quick stars, the Starred pin board and its remembered layouts, against a fixture API. */
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {openBrowser,until} from './lib/cdp.mjs';
import {planningFixture,sendFixture} from './lib/planning-fixture.mjs';
import {serveBuiltSpa} from './lib/spa-server.mjs';
const requests=[];
const stars=new Set(Array.from({length:52},(_,i)=>i+2));
const writes=[];let failStar=false;
const fixture=planningFixture({starred:n=>stars.has(n)});
const {item}=fixture;
const spa=await serveBuiltSpa(async(req,res,url)=>{
 if(url.pathname.startsWith('/api/')){
  let data=[]; const p=url.pathname;
  if(p.endsWith('/star') && ['PUT','DELETE'].includes(req.method)) {
   const n=Number(p.split('/')[4].replace('i-',''));writes.push({n,method:req.method});
   if(failStar){failStar=false;res.statusCode=500;res.setHeader('content-type','application/json');res.end(JSON.stringify({detail:'Fixture write failed'}));return true;}
   if(req.method==='PUT')stars.add(n);else stars.delete(n);
   res.setHeader('content-type','application/json');res.end(JSON.stringify(item(n)));return true;
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
  } else data=fixture.route(p)??(p.includes('settings')?{value:true}:p.includes('/stats')?{}:[]);
  sendFixture(res,data);return true;
 }
});
let browser;
try{
 browser=await openBrowser({port:19465,profile:await mkdtemp('/tmp/radd-grouped-proof-'),width:1600,height:1000});
 const s=browser.session;await s.navigate(`${spa.origin}/p/DEV/v/planning`,3500);
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Board work 300'));
 await s.click('button[aria-label="Star DEV-1"]');
 await until(s,async()=>await s.eval(`Boolean(document.querySelector('button[aria-label="Unstar DEV-1"]:not(:disabled)'))`));
 assert.equal(await s.eval('location.search'),'','Starring must not open peek');
 await s.eval(`document.querySelector('button[aria-label="Unstar DEV-1"]').focus()`);
 await s.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r',unmodifiedText:'\r'});
 await s.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
 await until(s,async()=>await s.eval(`Boolean(document.querySelector('button[aria-label="Star DEV-1"]:not(:disabled)'))`));
 assert.equal(await s.eval('location.search'),'','Keyboard starring must not open peek');
 failStar=true;
 await s.click('button[aria-label="Star DEV-1"]');
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Could not star DEV-1'));
 assert(!stars.has(1),'Failed writes must not save a star');
 await s.click('button[aria-label="Dismiss"]');
 await until(s,async()=>await s.eval(`Boolean(document.querySelector('button[aria-label="Star DEV-1"]:not(:disabled)'))`));
 await s.click('button[aria-label="Star DEV-1"]');
 await until(s,async()=>stars.has(1));
 await s.click('a[href="/starred"]');
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Saved issue 50'));
 let text=await s.eval('document.body.innerText');
 assert(text.includes('Done'),'Completed stars are included by default');
 assert(text.includes('53 matching'));assert(!text.includes('Saved issue 53'));
 await s.click('button',t=>t==='Show more');
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Saved issue 53'));
 assert(requests.some(r=>r.searchParams?.get('after')==='50'));
 const beforeLayout=requests.filter(r=>r.pathname==='/api/v1/items').length;
 await s.click('button',t=>t==='List');
 assert.equal(await s.eval(`document.querySelectorAll('ul[aria-label="Starred list"]>li').length`),53,'Layout retains every loaded issue');
 assert.equal(requests.filter(r=>r.pathname==='/api/v1/items').length,beforeLayout,'Layout is presentation only');
 assert.equal(await s.eval(`document.querySelector('[aria-label="Starred layout"] button[aria-pressed="true"]').textContent`),'List');

 await s.click('button[aria-label="Unstar DEV-1"]');
 await until(s,async()=> !await s.eval(`Boolean(document.querySelector('li[aria-label="DEV-1"]'))`));
 assert(!stars.has(1));
 await s.click('input[type="search"]');await s.send('Input.insertText',{text:'Saved issue 53'});
 await until(s,async()=>await s.eval(`document.querySelectorAll('main li[aria-label]').length===1 && document.querySelector('main').innerText.includes('Saved issue 53')`));
 await s.eval(`const input=document.querySelector('input[type="search"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'');input.dispatchEvent(new Event('input',{bubbles:true}));`);
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Saved issue 2'));
 await s.eval(`(()=>{const el=[...document.querySelectorAll('label')].find(e=>e.textContent.startsWith('Status')).querySelector('select');el.value='completed';el.dispatchEvent(new Event('change',{bubbles:true}));})()`);
 await until(s,async()=>await s.eval(`document.querySelectorAll('main li[aria-label]').length===1 && document.querySelector('main').innerText.includes('Saved issue 3')`));
 await s.eval(`(()=>{const el=[...document.querySelectorAll('label')].find(e=>e.textContent.startsWith('Status')).querySelector('select');el.value='all';el.dispatchEvent(new Event('change',{bubbles:true}));})()`);
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('Saved issue 50'));
 await s.click('button[aria-label="Collapse sidebar"]');
 assert(await s.eval(`Boolean(document.querySelector('a[aria-label="Starred"]'))`),'Collapsed navigation retains Starred');
 await s.click('button[aria-label="Expand sidebar"]');
 await s.screenshot('/tmp/radd-starred-list-proof.png');
 await s.click('button',t=>t==='Cards');
 assert(await s.eval(`Boolean(document.querySelector('ul[aria-label="Starred cards"]'))`));
 await s.screenshot('/tmp/radd-starred-proof.png');
 await s.click('button',t=>t==='List');
 await s.navigate(`${spa.origin}/starred`,1500);
 await until(s,async()=>await s.eval(`Boolean(document.querySelector('ul[aria-label="Starred list"]>li'))`));

 await s.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
 await s.screenshot('/tmp/radd-starred-list-mobile-proof.png');
 assert(await s.eval('document.documentElement.scrollWidth<=window.innerWidth'),'No horizontal page overflow');
 stars.clear();
 await s.navigate(`${spa.origin}/starred`,1500);
 await until(s,async()=> (await s.eval('document.body.innerText')).includes('No starred issues yet'));
 assert.deepEqual(s.consoleErrors.filter(e=>!e.includes('500')),[]);
 console.log('PASS: read-only quick stars, keyboard isolation, failure recovery, personal pin board, completed issues, cursor paging, search beyond first page, status filters mobile layout, list/card switching without refetch and persisted layout.');
}finally{browser?.close();await spa.close();}
