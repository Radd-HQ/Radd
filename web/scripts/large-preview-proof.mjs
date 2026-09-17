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
   const request={item_offset:Number(url.searchParams.get('item_offset')??0),axis:url.searchParams.get('axis'),column_key:url.searchParams.get('column_key')};requests.push({group:request});
   const make=(n,state)=>({...item(n),child_count:n===1?120:0,title:`Board work ${n}`,state:{id:state,name:state==='todo'?'To do':'In progress',category:state==='todo'?'todo':'in_progress'}});
   const all=Array.from({length:30},(_,i)=>make(i+1,'todo'));const rare=make(300,'progress');
   data={cells:[{column:'todo',lane:'__all__',total:30,items:all.slice(request.item_offset,request.item_offset+25)},{column:'progress',lane:'__all__',total:1,items:request.item_offset?[]:[rare]}],total_groups:2,column_points:{todo:90,progress:3},column_totals:{todo:30,progress:1},lane_totals:{__all__:31}};
   if(request.column_key) data.cells=data.cells.filter(c=>c.column===request.column_key);
  } else if(p==='/api/v1/items'||p==='/api/v1/items/count'){
   requests.push(url);
   const sprint=url.searchParams.getAll('cycle_id').length>0;
   const q=url.searchParams.get('q')??'';
   const parent=url.searchParams.get('parent_id');
   const label=parent?'Child':q.includes('starred')?'Starred':q.includes('target <=')?'Due':'Assigned';
   const pool=Array.from({length:parent?120:60},(_,i)=>({...item(i+1000),title:`${label} preview ${i+1}`}));
   data=p.endsWith('/count')?{total:pool.length}:pool.slice(Number(url.searchParams.get('offset')??0),Number(url.searchParams.get('offset')??0)+Number(url.searchParams.get('limit')??50));
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
  else if(p.includes('/settings'))data={value:true};
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
 browser=await openBrowser({port:19463,profile:await mkdtemp('/tmp/radd-grouped-proof-'),width:1600,height:1000});
 const s=browser.session;await s.navigate(`http://127.0.0.1:${server.address().port}/p/DEV/v/planning`,3500);
 const until=async (test)=>{for(let i=0;i<100;i++){if(await test())return;await new Promise(r=>setTimeout(r,50));}throw new Error(await s.eval('document.body.innerText')+'\n'+s.consoleErrors.join('\n'));};
 await until(async()=> (await s.eval('document.body.innerText')).includes('Board work 300'));
 assert(!requests.some(r=>r.searchParams?.has('parent_id')),'Collapsed children make no request');
 await s.click('button[aria-label="Show children of DEV-1"]');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Child preview 50'));
 assert(!(await s.eval('document.body.innerText')).includes('Child preview 51'));
 assert(requests.some(r=>r.searchParams?.get('parent_id')==='i-1'&&r.searchParams.get('limit')==='50'));
 await s.click('button',t=>t.includes('Show 50 more children'));
 await until(async()=> (await s.eval('document.body.innerText')).includes('Child preview 100'));
 await s.click('button',t=>t.includes('Show 50 more children'));
 await until(async()=> (await s.eval('document.body.innerText')).includes('Child preview 120'));
 await s.screenshot('/tmp/radd-children-preview-proof.png');
 requests.length=0;
 await s.navigate(`http://127.0.0.1:${server.address().port}/`,2500);
 await until(async()=> (await s.eval('document.body.innerText')).includes('Due preview 25'));
 assert(!(await s.eval('document.body.innerText')).includes('Due preview 26'));
 assert((await s.eval('document.body.innerText')).includes('Starred preview 8'));
 assert(!(await s.eval('document.body.innerText')).includes('Starred preview 9'));
 assert(requests.some(r=>r.searchParams?.get('q')?.includes('ORDER BY target ASC, priority DESC, number DESC')));
 assert(requests.some(r=>r.searchParams?.get('q')?.includes('target IS EMPTY OR target >')));
 await s.click('section[aria-label="Due soon"] button',t=>t==='Show more');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Due preview 50'));
 await s.click('section[aria-label="Due soon"] button',t=>t==='Show more');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Due preview 60'));
 assert.equal(await s.eval(`document.querySelectorAll('section[aria-label="Due soon"] li').length`),60);
 await s.screenshot('/tmp/radd-my-work-preview-proof.png');
 assert.deepEqual(s.consoleErrors,[]);
 console.log('PASS: deferred children, 50-row progressive children to exhaustion, bounded My Work, server ordering, all matches reachable.');
}finally{browser?.close();await new Promise(resolve=>server.close(resolve));}
