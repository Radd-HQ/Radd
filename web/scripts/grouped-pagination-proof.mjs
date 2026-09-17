/** RADD-1201: real built board/queue UI, bounded groups and server queue ordering. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
const dist=new URL('../dist/',import.meta.url).pathname;
const requests=[];
const project={id:'project',key:'DEV',name:'Development',permissions:['item.read'],created_at:'2026-01-01'};
const cycles=[{id:'active',name:'Current sprint',status:'active',start_date:'2026-09-10',end_date:'2026-09-24'}, {id:'draft',name:'Next sprint',status:'draft',start_date:null,end_date:null},{id:'closed',name:'Historical sprint',status:'completed'}];
const view={id:'planning',project_id:project.id,name:'Planning',view_type:'board',query:'',query_string:'project_id=project',group_by:'state',swimlane_by:null,quick_filters:[],columns:['item','priority','state'],column_order:[],hidden_columns:[],cycle_filter:null,can_edit:false,can_manage:false};
const item=(n,cycle=null)=>({id:`i-${n}`,key:`DEV-${n}`,number:n,project_id:project.id,title:`${cycle?'Sprint':'Backlog'} work ${n}`,description:'',state:{id:'todo',name:'To do',category:'todo',color:'#999'},priority:'high',kind:'issue',type:null,assignee:null,reporter:null,team:null,cycle,labels:[],custom_fields:{},starred:false,flagged:false,visibility:'public',created_at:'2026-09-01',updated_at:'2026-09-17',comment_count:0,attachment_count:0});
const sprintRows=Array.from({length:201},(_,i)=>item(15000+i,cycles[i===200?1:0]));
const backlog=Array.from({length:401},(_,i)=>item(i+1));
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://local');
 if(url.pathname.startsWith('/api/')){
  let data=[]; const p=url.pathname;
  if(p==='/api/v1/sla-queue-items'){requests.push({queue:url});data=[{...item(url.searchParams.get('offset')==='200'?901:900),title:url.searchParams.get('offset')==='200'?'Later queue page':'Overdue queue item'}];}
  else if(p==='/api/v1/items/grouped'){
   const request={item_offset:Number(url.searchParams.get('item_offset')??0),axis:url.searchParams.get('axis')};requests.push({group:request});
   const make=(n,state)=>({...item(n),title:`Board work ${n}`,state:{id:state,name:state==='todo'?'To do':'In progress',category:state==='todo'?'todo':'in_progress'}});
   const all=Array.from({length:30},(_,i)=>make(i+1,'todo'));const rare=make(300,'progress');
   data={cells:[{column:'todo',lane:'__all__',total:30,items:all.slice(request.item_offset,request.item_offset+25)},{column:'progress',lane:'__all__',total:1,items:request.item_offset?[]:[rare]}],total_groups:2,column_totals:{todo:30,progress:1},lane_totals:{__all__:31}};
  } else if(p==='/api/v1/items'||p==='/api/v1/items/count'){
   requests.push(url);
   const sprint=url.searchParams.getAll('cycle_id').length>0;
   const q=url.searchParams.get('q')??'';
   const pool=sprint?sprintRows:q.includes('cycle IS EMPTY')?backlog:Array.from({length:14704},(_,i)=>({...item(i+1,cycles[2]),state:{id:'done',name:'Done',category:'done'}}));
   data=p.endsWith('/count')?{total:view.view_type==='queue'?201:pool.length}:pool.slice(Number(url.searchParams.get('offset')??0),Number(url.searchParams.get('offset')??0)+Number(url.searchParams.get('limit')??50));
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
 browser=await openBrowser({port:19462,profile:await mkdtemp('/tmp/radd-grouped-proof-'),width:1600,height:1000});
 const s=browser.session;await s.navigate(`http://127.0.0.1:${server.address().port}/p/DEV/v/planning`,3500);
 const until=async (test)=>{for(let i=0;i<100;i++){if(await test())return;await new Promise(r=>setTimeout(r,50));}throw new Error(await s.eval('document.body.innerText')+'\n'+s.consoleErrors.join('\n'));};
 await until(async()=> (await s.eval('document.body.innerText')).includes('Board work 300'));
 let text=await s.eval('document.body.innerText');assert.ok(text.includes('Board work 1'));assert.ok(text.includes('26 loaded'));assert.ok(!text.includes('Board work 30\n'));
 assert.ok(requests.every(r=>r.group),'Board must never request a globally paged list/count');
 await s.click('button',text=>text==='Load more in these groups');
 await until(async()=> (await s.eval('document.body.innerText')).includes('31 loaded'));
 text=await s.eval('document.body.innerText');assert.ok(text.includes('Board work 300'));assert.ok(text.includes('31 loaded'));
 assert.equal(requests[1].group.item_offset,25);
 await s.screenshot('/tmp/radd-grouped-board-proof.png');assert.deepEqual(s.consoleErrors,[]);
 view.view_type='queue';view.group_by=null;requests.length=0;
 await s.navigate(`http://127.0.0.1:${server.address().port}/p/DEV/v/planning`,2000);
 await until(async()=> (await s.eval('document.body.innerText')).includes('Overdue queue item'));
 assert.ok(requests.some(r=>r.queue));assert.ok(!requests.some(r=>r.pathname?.endsWith('/items')));
 await s.click('button[aria-label="Next page"]');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Later queue page'));
 assert.ok(requests.some(r=>r.queue?.searchParams.get('offset')==='200'));
 assert.deepEqual(s.consoleErrors,[]);
 console.log('PASS: queue uses the server urgency endpoint across pagination.');
 console.log('PASS: board immediately shows rare state, loads further rows without losing other groups, displays full count and avoids global paging.');
}finally{browser?.close();await new Promise(resolve=>server.close(resolve));}
