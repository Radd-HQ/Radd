/** RADD-1197: real built Planning UI, HTTP fixtures with historical work before live work. */
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
const view={id:'planning',project_id:project.id,name:'Planning',view_type:'planning',query:'',query_string:'project_id=project',group_by:'cycle',swimlane_by:null,quick_filters:[],columns:['item','priority','state'],column_order:[],hidden_columns:[],cycle_filter:null,can_edit:false,can_manage:false};
const item=(n,cycle=null)=>({id:`i-${n}`,key:`DEV-${n}`,number:n,project_id:project.id,title:`${cycle?'Sprint':'Backlog'} work ${n}`,description:'',state:{id:'todo',name:'To do',category:'todo',color:'#999'},priority:'high',kind:'issue',type:null,assignee:null,reporter:null,team:null,cycle,labels:[],custom_fields:{},starred:false,flagged:false,visibility:'public',created_at:'2026-09-01',updated_at:'2026-09-17',comment_count:0,attachment_count:0});
const sprintRows=Array.from({length:201},(_,i)=>item(15000+i,cycles[i===200?1:0]));
const backlog=Array.from({length:401},(_,i)=>item(i+1));
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://local');
 if(url.pathname.startsWith('/api/')){
  let data=[]; const p=url.pathname;
  if(p==='/api/v1/items'||p==='/api/v1/items/count'){
   requests.push(url);
   const sprint=url.searchParams.getAll('cycle_id').length>0;
   const q=url.searchParams.get('q')??'';
   const pool=sprint?sprintRows:q.includes('cycle IS EMPTY')?backlog:Array.from({length:14704},(_,i)=>({...item(i+1,cycles[2]),state:{id:'done',name:'Done',category:'done'}}));
   data=p.endsWith('/count')?{total:pool.length}:pool.slice(Number(url.searchParams.get('offset')??0),Number(url.searchParams.get('offset')??0)+Number(url.searchParams.get('limit')??50));
  } else if(p==='/api/v1/auth/me')data={id:'person',name:'Tester',email:'tester@example.com',global_role:'member',instance_role:'member',permissions:[],timezone:'UTC'};
  else if(p==='/api/v1/views/planning')data=view;
  else if(p==='/api/v1/views')data=[view];
  else if(p==='/api/v1/projects/summary')data={total:1,related_count:1,permissions:['item.read']};
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
 let text=await s.eval('document.body.innerText');assert.ok(text.includes('Backlog work 1'));assert.ok(!text.includes('Historical sprint'));assert.ok(text.includes('201 / 201 sprint items'));
 assert.ok(requests.every(url=>url.searchParams.getAll('cycle_id').length||url.searchParams.get('q')?.includes('cycle IS EMPTY')),'No globally paged request');
 const before=requests.filter(u=>u.pathname.endsWith('/items')&&u.searchParams.has('cycle_id')).length;
 await s.click('button[aria-label="Next page"]');
 await until(async()=> (await s.eval('document.body.innerText')).includes('Backlog work 201'));
 text=await s.eval('document.body.innerText');assert.ok(text.includes('Sprint work 15200'));assert.ok(!text.includes('Backlog work 1\n'));
 assert.equal(requests.filter(u=>u.pathname.endsWith('/items')&&u.searchParams.has('cycle_id')).length,before,'Backlog paging must not reload sprint work');
 await s.screenshot('/tmp/radd-planning-pagination-proof.png');
 assert.deepEqual(s.consoleErrors,[]);
 console.log('PASS: 201 sprint items across API pages remain visible while 401 open backlog items paginate independently; historical global pages never fetched.');
}finally{browser?.close();await new Promise(resolve=>server.close(resolve));}
